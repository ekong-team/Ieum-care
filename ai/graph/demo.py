"""그래프를 한 번 실행해 판단 기록 타임라인을 출력한다. API 키 없이 동작한다 (offline).

    python -m ai.graph.demo                    # 예시 프로필로 실행
    python -m ai.graph.demo --profile 파일.json  # 다른 대상 프로필로 실행
    python -m ai.graph.demo --mermaid          # 그래프 구조를 Mermaid 다이어그램으로 출력 (문서·발표용)
"""

import argparse
import json
from pathlib import Path

from ai.contracts import TargetProfile
from ai.graph.pipeline import build_graph, run_pipeline

EXAMPLE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "target_profile_example.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", type=Path, default=EXAMPLE)
    parser.add_argument("--mermaid", action="store_true")
    args = parser.parse_args()

    if args.mermaid:
        print(build_graph().get_graph().draw_mermaid())
        return

    profile = TargetProfile.model_validate(json.loads(args.profile.read_text(encoding="utf-8")))
    state = run_pipeline(profile, mode="offline")

    print(f"\n실행 {state['run_id']}  대상: {profile.target.region} {profile.target.age_group}대 ({profile.source})\n")
    for event in state["trace"]:
        if event.status == "started":
            continue
        mark = {"done": "✓", "failed": "✗", "skipped": "-"}[event.status]
        print(f"{event.seq:>3} {mark} {event.node:<18} {event.decision}")
        for reason in event.reasons[:3]:
            if reason:
                print(f"{'':>24}· {reason}")
    report = state["report"]
    print(f"\n결과: {report.summary}  추천: {report.recommended_plan_ids}")
    for note in report.notes:
        print(f"  {note}")
    for text in state.get("warnings", []):
        print(f"  주의: {text}")


if __name__ == "__main__":
    main()
