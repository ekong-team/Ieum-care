"""입력 파일과 집단 키·숫자 범위를 확인한다. 원본 파일은 변경하지 않는다."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import csv
import hashlib
import json
import math
from pathlib import Path
from ai.analysis_agent.policy import REGIONS, AGES, KEYS, CARD, MOVEMENT, FILTERED, SEXES

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()

def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def number(value, *, minimum=None, maximum=None):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    try:
        n = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("올바른 숫자가 아닙니다.") from error
    if not n.is_finite() or not math.isfinite(float(n)) or minimum is not None and n < Decimal(str(minimum)) or maximum is not None and n > Decimal(str(maximum)):
        raise ValueError("invalid numeric value")
    return n

def month_number(value):
    if not isinstance(value, str) or len(value) != 6 or not value.isascii() or not value.isdigit():
        raise ValueError("month must be YYYYMM")
    d = datetime.strptime(value, "%Y%m")
    return d.year * 12 + d.month

def validate_rows(rows: list[dict]) -> list[dict]:
    """파일 입력과 직접 함수 호출에 동일한 검사를 적용한 사본을 돌려준다."""
    if not rows:
        raise ValueError("분석할 집단 자료가 없습니다.")
    clean, seen = [], set()
    for original in rows:
        row = dict(original)
        row["sex"] = row.get("sex", "all")
        if row["sex"] not in SEXES:
            raise ValueError("지원하지 않는 성별 코드입니다.")
        month_number(row["month"])
        if row["region"] not in REGIONS or row["age"] not in AGES:
            raise ValueError("지원하지 않는 지역 또는 연령입니다.")
        key = (row["month"], row["region"], row["age"], row["sex"])
        if key in seen:
            raise ValueError("duplicate group month")
        seen.add(key)
        for key, minimum, maximum in (
            ("card", 0, None), ("movement", -1, None),
            ("filtered_daily", -1, None), ("stored_daily", -1, None),
            ("age_coverage", 0, 1), ("common_location", 0, 1),
        ):
            row[key] = number(row.get(key), minimum=minimum, maximum=maximum)
        if row["card"] is not None and row["card"] != row["card"].to_integral_value():
            raise ValueError("카드 결제건수는 정수여야 합니다.")
        if row["movement"] is not None and (row["age_coverage"] == 0 or row["common_location"] == 0):
            raise ValueError("관측 범위가 0인데 유동량 변화율이 있습니다.")
        clean.append(row)
    return clean

def load_inputs(features_path, sensitivity_path, packet_path):
    """세 입력의 키와 형식을 대조하고, 재현용 출처 기록을 만든다."""
    def read(path, required):
        with Path(path).open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            if len(header) != len(set(header)) or not set(required) <= set(header):
                raise ValueError(f"필수 열 누락 또는 중복: {Path(path).name}")
            rows = list(reader)
            if any(None in row for row in rows):
                raise ValueError(f"열 개수가 맞지 않습니다: {Path(path).name}")
            return rows
    rows = read(features_path, (*KEYS, CARD, MOVEMENT, "통신_연령관측률", "통신_전월공통위치비율"))
    sensitivity = read(sensitivity_path, (*KEYS, FILTERED, "일평균_결제건수_전월변화율_전체"))
    def index(items):
        result = {}
        for row in items:
            key = (*[row[k] for k in KEYS], row.get("성별", "all"))
            if key in result:
                raise ValueError("duplicate group/month key")
            result[key] = row
        return result
    main, secondary = index(rows), index(sensitivity)
    if not main or set(main) != set(secondary):
        raise ValueError("feature/sensitivity keys differ")
    result = []
    for key, r in main.items():
        month_number(r["월"])
        if r["지역"] not in REGIONS or r["연령대"] not in AGES:
            raise ValueError("unsupported region/age")
        count = number(r[CARD], minimum=0)
        if count is not None and count != count.to_integral_value():
            raise ValueError("card count must be integer")
        result.append(dict(month=r["월"], region=r["지역"], age=r["연령대"], sex=r.get("성별", "all"),
            card=count, movement=number(r[MOVEMENT], minimum=-1),
            filtered_daily=number(secondary[key][FILTERED], minimum=-1),
            stored_daily=number(secondary[key]["일평균_결제건수_전월변화율_전체"], minimum=-1),
            age_coverage=number(r["통신_연령관측률"], minimum=0, maximum=1),
            common_location=number(r["통신_전월공통위치비율"], minimum=0, maximum=1)))
    packet = json.loads(Path(packet_path).read_text(encoding="utf-8"), parse_constant=reject_json_constant)
    if packet.get("schema_version") != "submission-review-context-v1":
        raise ValueError("지원하지 않는 배경 자료 형식입니다.")
    context = {}
    for record in packet["records"]:
        aid = record["analysis_id"]
        if aid in context:
            raise ValueError("duplicate context analysis id")
        context[aid] = record
    manifest = []
    project_root = Path(__file__).resolve().parents[2]
    paths = list(zip(("features", "industry_sensitivity", "context_packet"),
                     (features_path, sensitivity_path, packet_path)))
    preparation = Path(features_path).parent / "sex_preprocessing_manifest.json"
    if preparation.exists():
        prepared = json.loads(preparation.read_text(encoding="utf-8"))
        if prepared.get("schema_version") != "sex-preprocessing-v1" or prepared.get("status") != "passed":
            raise ValueError("성별 전처리가 완료되지 않았습니다.")
        for _, path in paths:
            if prepared["outputs"].get(Path(path).name) != file_hash(path):
                raise ValueError("성별 전처리 산출물이 변경됐습니다.")
        for source in prepared["sources"]:
            if file_hash(project_root / source["path"]) != source["sha256"]:
                raise ValueError("성별 전처리의 원본·비교 기준이 변경됐습니다.")
        if file_hash(project_root / "scripts/data_processing/build_sex_features.py") != prepared["script_sha256"]:
            raise ValueError("성별 전처리 코드 변경 후 재실행이 필요합니다.")
        paths.append(("sex_preprocessing", preparation))
    for role, path in paths:
        absolute = Path(path).resolve()
        relative = absolute.is_relative_to(project_root)
        manifest.append(dict(role=role, path=str(absolute.relative_to(project_root) if relative else absolute),
                             path_base="project" if relative else "absolute", sha256=file_hash(path)))
    manifest[2]["declared_upstream_hashes"] = packet.get("source_sha256", {})
    return validate_rows(result), context, manifest

def reject_json_constant(value):
    raise ValueError(f"JSON에 유한하지 않은 숫자가 있습니다: {value}")

def source_path(entry):
    """팀원 컴퓨터에서도 프로젝트 상대 경로로 출처 파일을 찾는다."""
    if entry.get("path_base") == "project":
        root = Path(__file__).resolve().parents[2]
        path = (root / entry["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("프로젝트 밖의 상대 출처 경로입니다.")
        return path
    return Path(entry["path"])
