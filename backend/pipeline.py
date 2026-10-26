"""통합 실행(기획 그래프) 시작·진행 조회·저장 결과 다시 보기. 설계 문서 6.1.

입력은 두 가지다.
- 직접 입력: {"mode", "profile": TargetProfile, "officer_request"?}
- 복지 추천 전달함: {"mode", "request_id"} → 저장된 기획 요청을 대상 프로필로 바꾸고,
  요청에 담긴 추천 결과를 그대로 쓴다 (복지 검색·LLM을 다시 부르지 않는다).
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import Lock, Thread
from uuid import UUID, uuid4

from ai.contracts import (CauseHypothesis, ExistingResources, GapItem, ProgramPlan, RiskInfo, Target, TargetProfile,
                          TrendReference, WelfareAnalysisContext)
from ai.graph.pipeline import Engines, PlanningInput, run_pipeline, state_to_json
from ai.graph.trace import TraceRecorder
from ai.nodes.context import NodeContext
from ai.nodes.welfare import attach_response_routes, to_existing_resources
from ai.welfare_agent.live_agent import config_status

SCHEMA_VERSION = "pipeline-run-0.1"
RUN_ID = re.compile(r"^run-[0-9a-f]{12}$")
MAX_OFFICER_REQUEST = 2000


def now():
    return datetime.now(timezone.utc).isoformat()


class RunNotFound(LookupError):
    pass


def profile_from_request(request: dict) -> tuple[TargetProfile, list, ExistingResources, list[str]]:
    """기획 요청(planning-request-0.1) → (대상 프로필, 원인 가설, 기존 자원, 안내). 검증은 전달함 저장 때 끝났다."""
    notes = []
    context = request.get("analysis_context")
    if context:
        parsed = WelfareAnalysisContext.model_validate(context)
        profile, causes = parsed.profile, parsed.causes
    else:
        risk = request.get("risk_assessment")
        target = request["target"]
        profile = TargetProfile(
            source="data" if risk else "manual",
            target=Target(region=target["region"], age_group=target["age_group"], sex=target.get("sex", "all")),
            period=risk["period"] if risk else request["created_at"][:7],
            risk=RiskInfo(level=risk["level"], status=risk["status"], model_version=risk["model_version"]) if risk else None,
            signals=[item["type"] for item in risk["signals"]] if risk else [],
            limitations=list(risk["limitations"]) if risk else ["위험도 결과 없이 담당자 요청으로 기획합니다."],
            is_example=request["has_example_context"])
        causes = []
        notes.append("분석 맥락(근거 수치)이 없는 요청이라 근거 수치 인용 없이 기획합니다.")

    lookup = request["welfare_lookup"]
    if lookup["status"] == "completed":
        snapshot = deepcopy(lookup["recommendation_snapshot"])
        if request["planning_type"] == "existing_resource_based":
            chosen = {item["id"] for item in request["selected_resources"]}
            snapshot["resources"] = [item for item in snapshot["resources"] if item["id"] in chosen]
            notes.append(f"기존 자원 활용 기획: 담당자가 고른 자원 {len(chosen)}개만 연계 대상으로 씁니다.")
        existing = to_existing_resources(snapshot, ["복지 추천 화면의 조회 결과를 재사용했습니다 (다시 검색하지 않음)."])
    else:
        existing = attach_response_routes(ExistingResources(
            status="unavailable", reason=f"복지 추천 조회 실패: {lookup['error']}",
            has_example_context=request["has_example_context"]))
    return profile, causes, existing, notes


class PipelineService:
    """한 번에 한 실행만 허용한다. live 실행은 복지 추천·분석과 같은 LIVE_SLOT을 쓴다."""

    def __init__(self, root, slot, inbox, *, runs_root=None, engines=None):
        self.runs_root = Path(runs_root or Path(root) / "data/runs")
        self.slot, self.inbox = slot, inbox
        self.engines = engines or Engines()  # 테스트에서 가짜 계산 함수로 바꿔 끼운다
        self.lock = Lock()
        self.runs: dict[str, dict] = {}
        self.active: str | None = None

    # ── 시작 ────────────────────────────────────────────────────────────────
    def start(self, request: dict) -> dict:
        if not isinstance(request, dict):
            raise ValueError("요청 객체가 필요합니다.")
        mode = request.get("mode", "offline")
        if mode not in ("live", "offline"):
            raise ValueError("지원하지 않는 실행 방식입니다.")
        engines, notes = self.engines, []
        if set(request) <= {"mode", "profile", "officer_request"} and "profile" in request:
            profile = TargetProfile.model_validate(request["profile"])
            officer = request.get("officer_request", "")
            if not isinstance(officer, str) or len(officer) > MAX_OFFICER_REQUEST:
                raise ValueError("담당자 요청은 2,000자 이내 문자열이어야 합니다.")
            source = {"kind": "manual"}
        elif set(request) <= {"mode", "request_id"} and "request_id" in request:
            planning = self._planning_request(request["request_id"])
            profile, causes, existing, notes = profile_from_request(planning)
            engines = replace(engines, recommend_existing=lambda ctx, p: existing)
            if causes:
                engines = replace(engines, analyze_causes=lambda ctx, p: causes)
            officer = planning["officer_prompt"]
            source = {"kind": "planning_request", "request_id": planning["request_id"],
                      "planning_type": planning["planning_type"]}
        else:
            raise ValueError("profile 또는 request_id 중 하나가 필요합니다.")
        if mode == "live" and not config_status()["configured"]:
            raise PermissionError("서버의 Gemini·Tavily 키 설정을 확인해주세요.")

        with self.lock:
            if self.active:
                raise BlockingIOError("다른 통합 실행이 진행 중입니다. 완료 후 다시 실행해주세요.")
            if mode == "live" and not self.slot.acquire(blocking=False):
                raise BlockingIOError("다른 AI 추천·분석이 실행 중입니다. 완료 후 다시 실행해주세요.")
            run_id = f"run-{uuid4().hex[:12]}"
            record = {"schema_version": SCHEMA_VERSION, "run_id": run_id, "status": "running", "mode": mode,
                      "source": source, "officer_request": officer, "notes": notes,
                      "target": profile.target.model_dump(mode="json"), "is_example": profile.is_example,
                      "started_at": now(), "finished_at": None, "result": None, "error": None}
            self.runs[run_id] = {"record": record, "recorder": TraceRecorder(run_id)}
            self.active = run_id
        Thread(target=self._work, args=(run_id, profile, engines), daemon=True).start()
        return self._public(record)

    def _planning_request(self, request_id) -> dict:
        try:
            if not isinstance(request_id, str) or str(UUID(request_id)) != request_id:
                raise ValueError
        except ValueError:
            raise ValueError("기획 요청 ID를 확인해주세요.") from None
        for envelope in self.inbox.list_requests():
            if envelope["request"]["request_id"] == request_id:
                return envelope["request"]
        raise RunNotFound("전달함에 없는 기획 요청입니다.")

    def _work(self, run_id, profile, engines):
        entry = self.runs[run_id]
        record = entry["record"]
        try:
            state = run_pipeline(profile, mode=record["mode"], engines=engines, recorder=entry["recorder"],
                                 run_id=run_id, officer_request=record["officer_request"])
            result = state_to_json(state)
            status = result["report"]["status"]
        except Exception as error:  # noqa: BLE001 - 그래프 밖 오류도 실행 기록으로 남긴다
            result, status = None, "failed"
            record["error"] = f"통합 실행 중 오류가 발생했습니다: {type(error).__name__}"
        with self.lock:
            record.update(status=status, result=result, finished_at=now())
            self.active = None
        if record["mode"] == "live":
            self.slot.release()
        try:
            self.runs_root.mkdir(parents=True, exist_ok=True)
            temporary = self.runs_root / f"{run_id}.tmp"
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.runs_root / f"{run_id}.json")
        except OSError:
            record["error"] = "실행 결과를 파일로 저장하지 못했습니다. 이 화면을 닫으면 다시 볼 수 없습니다."

    # ── 담당자 기획안 평가 ──────────────────────────────────────────────────
    def evaluate(self, request: dict) -> dict:
        """저장된 실행의 맥락(원인·기존 자원·공백·사례)으로 담당자 기획안 하나를 채점한다. 설계 문서 6.1.

        그래프를 다시 돌리지 않는다. 담당자 기획안은 근거 검증 대신 형식 검증(Pydantic)만 하고(설계 5.3),
        live면 실현 가능성 축만 Gemini 1회 호출한다. 짧은 작업이라 백그라운드 없이 바로 결과를 돌려준다.
        """
        if not isinstance(request, dict) or not {"run_id", "plan"} <= set(request) <= {"mode", "run_id", "plan"}:
            raise ValueError("run_id와 plan이 필요합니다.")
        mode = request.get("mode", "offline")
        if mode not in ("live", "offline"):
            raise ValueError("지원하지 않는 실행 방식입니다.")
        if not isinstance(request["plan"], dict):
            raise ValueError("기획안은 JSON 객체여야 합니다.")
        record = self.status(request["run_id"])
        if record["status"] != "completed":
            raise ValueError("완료된 실행만 평가 기준으로 쓸 수 있습니다.")
        result = record["result"]
        plan = ProgramPlan.model_validate({**request["plan"], "source": "manual"})
        profile = TargetProfile.model_validate(result["profile"])
        if plan.target != profile.target:
            raise ValueError("기획안의 대상(지역·연령·성별)이 기준 실행의 대상과 다릅니다.")
        planning = PlanningInput(
            run_id=record["run_id"], profile=profile,
            causes=[CauseHypothesis.model_validate(item) for item in result.get("causes") or []],
            existing=(ExistingResources.model_validate(result["existing_resources"]) if result.get("existing_resources")
                      else ExistingResources(status="unavailable", reason="기준 실행에 기존 자원 결과 없음")),
            trends=[TrendReference.model_validate(item) for item in result.get("trend_references") or []],
            gaps=[GapItem.model_validate(item) for item in result.get("gaps") or []],
            officer_request=record["officer_request"])
        if mode == "live":
            if not config_status()["configured"]:
                raise PermissionError("서버의 Gemini·Tavily 키 설정을 확인해주세요.")
            if not self.slot.acquire(blocking=False):
                raise BlockingIOError("다른 AI 추천·분석이 실행 중입니다. 완료 후 다시 실행해주세요.")
        ctx = NodeContext(run_id=record["run_id"], mode=mode)
        try:
            evaluation = self.engines.evaluate_plans(ctx, [plan], planning)[0]
        finally:
            if mode == "live":
                self.slot.release()
        original = next((item for item in result.get("evaluations") or [] if item["plan_id"] == plan.plan_id), None)
        return {"schema_version": "manual-evaluation-0.1", "run_id": record["run_id"], "mode": mode,
                "plan": plan.model_dump(mode="json"), "evaluation": evaluation.model_dump(mode="json"),
                "original_evaluation": original, "external_calls": dict(ctx.calls), "warnings": ctx.warnings}

    # ── 조회 ────────────────────────────────────────────────────────────────
    def status(self, run_id: str, after_seq: int = -1) -> dict:
        if not RUN_ID.match(run_id or ""):
            raise RunNotFound("실행 ID를 확인해주세요.")
        with self.lock:
            entry = self.runs.get(run_id)
            if entry:
                record = deepcopy(entry["record"])
                events = [e.model_dump(mode="json") for e in entry["recorder"].after(after_seq)]
            else:
                record, events = self._load(run_id), None
        if events is None:
            events = [e for e in (record.get("result") or {}).get("trace", []) if e["seq"] > after_seq]
        return {**self._public(record), "events": events,
                "result": record["result"] if record["status"] != "running" else None}

    def saved(self) -> list[dict]:
        items = []
        for path in self.runs_root.glob("run-*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("schema_version") != SCHEMA_VERSION or record.get("run_id") != path.stem:
                    continue
                report = (record.get("result") or {}).get("report") or {}
                items.append({**self._public(record), "summary": report.get("summary", record.get("error") or ""),
                              "recommended": len(report.get("recommended_plan_ids", []))})
            except (OSError, ValueError, AttributeError):
                continue
        return sorted(items, key=lambda item: item["started_at"], reverse=True)

    def _load(self, run_id) -> dict:
        path = self.runs_root / f"{run_id}.json"
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise RunNotFound("저장된 실행 결과가 없습니다.") from None
        if record.get("schema_version") != SCHEMA_VERSION or record.get("run_id") != run_id:
            raise RunNotFound("저장된 실행 결과 형식을 확인해주세요.")
        return record

    @staticmethod
    def _public(record: dict) -> dict:
        return {key: deepcopy(record[key]) for key in ("schema_version", "run_id", "status", "mode", "source",
                                                       "officer_request", "notes", "target", "is_example",
                                                       "started_at", "finished_at", "error")}
