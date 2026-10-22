"""제공 원본·공식 인구 → 분석 입력 → 분석 검증 → 복지 추천 대기열. LLM 호출 없음."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ai.welfare_agent.analysis_input import latest_analysis_inputs


def preparation_steps(*, rebuild_base=False):
    steps = []
    base = ('telecom_features.csv', 'card_features.csv', 'risk_features.csv')
    if rebuild_base or any(not (ROOT / 'data/processed' / name).is_file() for name in base):
        steps.extend((f'scripts/data_processing/{name}.py', []) for name in
                     ('build_telecom_features', 'build_card_features', 'build_risk_features'))
    # 기존 합산 결과는 원본 카드와 성별 통신 합계 대조로 다시 확인한다.
    steps.extend([
        ('scripts/data_processing/analyze_card_complete.py', []),
        ('ai/risk_model/build_activity_levels.py', []),
        ('ai/risk_model/build_activity_evidence.py', []),
        ('scripts/data_processing/collect_population_context.py', []),
        ('scripts/data_processing/build_population_context_review.py', []),
        ('scripts/data_processing/prepare_submission_data_pack.py', ['--context-only']),
        ('scripts/data_processing/build_sex_features.py', []),
    ])
    return steps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--period', default='202512')
    parser.add_argument('--rebuild-base', action='store_true', help='통신·카드·통합 기초 특징도 원본에서 재생성')
    parser.add_argument('--allow-download', action='store_true', help='미보유 공식 인구 CSV의 무료 다운로드 허용')
    parser.add_argument('--send-to-welfare', action='store_true', help='완료 후 켜둔 localhost 추천 서버로 전달')
    args = parser.parse_args()
    originals = [ROOT / 'data/raw' / f'flow_age_pop_2025{month:02}.csv' for month in range(7, 13)]
    originals += [ROOT / 'data/raw' / f'신한카드_빅콘테스트2026_데이터{number}.txt' for number in (1, 2)]
    missing = [str(path.relative_to(ROOT)) for path in originals if not path.is_file()]
    if missing:
        parser.error('제공 원본이 없습니다: ' + ', '.join(missing))
    cached_population = ROOT / 'data/external/public_context/context_research_20261015'
    if not args.allow_download and any(not (cached_population / f'mois_age_2025{month:02}.csv').is_file() for month in range(6, 13)):
        parser.error('공식 인구 원본이 없습니다. 무료 공개 CSV 수집은 --allow-download로 허용하세요.')
    steps = preparation_steps(rebuild_base=args.rebuild_base)
    analysis_args = ['--period', args.period, '--mode', 'offline']
    if args.send_to_welfare:
        analysis_args.append('--send-to-welfare')
    steps += [('scripts/integration/run_analysis_agent.py', analysis_args),
              ('scripts/integration/verify_analysis_agent.py', [])]
    for script, options in steps:
        print(f'실행: {script} {" ".join(options)}', flush=True)
        subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / script), *options], cwd=ROOT, check=True)
    inputs = latest_analysis_inputs(ROOT / 'data/processed/analysis_current')
    result = dict(status='passed', period=inputs['period'], analysis_batch_id=inputs['batch_id'],
                  welfare_targets=len(inputs['entries']),
                  partial=len(inputs['priority']['partial_assessments']), held=len(inputs['priority']['held_cohorts']),
                  external_llm_calls=0, welfare_recommendations_executed=False,
                  completed_steps=[script for script, _ in steps])
    (ROOT / 'data/processed/analysis_welfare_preparation.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
