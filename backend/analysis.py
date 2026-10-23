"""로컬 분석 실행·조회. 고정된 입력과 실행기만 사용하고 한 번에 한 작업만 허용한다."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock, Thread
from uuid import uuid4

from ai.analysis_agent.model import config_status
from ai.welfare_agent.analysis_input import prepare_analysis_inputs


def now():
    return datetime.now(timezone.utc).isoformat()


class AnalysisService:
    def __init__(self, root, slot, on_publish=lambda: None, runner=None):
        self.root, self.slot, self.on_publish = Path(root), slot, on_publish
        self.runner = runner or self._execute
        self.lock = Lock()
        self.job = None

    def _bundle(self):
        root = (self.root / 'data/processed/analysis_current').resolve()
        pointer = json.loads((root / 'latest.json').read_text(encoding='utf-8'))
        folder = (root / pointer['directory']).resolve()
        if folder == root or not folder.is_relative_to(root):
            raise ValueError('invalid_result_path')
        status = json.loads((folder / 'run_status.json').read_text(encoding='utf-8'))
        bundle = json.loads((folder / 'analysis_bundle.json').read_text(encoding='utf-8'))
        if status.get('status') != 'passed' or pointer.get('bundle_hash') != bundle.get('bundle_hash') or status.get('bundle_hash') != bundle.get('bundle_hash'):
            raise ValueError('result_not_verified')
        # 기존 추천 수신 계약과 같은 해시·순위 검증을 사용한다.
        prepare_analysis_inputs(bundle)
        return bundle, folder

    def result(self):
        bundle, folder = self._bundle()
        period = bundle['priority_review']['period']
        cohorts = [c for c in bundle['cohorts'] if c['profile']['period'] == period and c['profile']['target']['sex'] in ('female', 'male')]
        order = {item['analysis_id']: i for i, item in enumerate(bundle['priority_review']['ranked_cohorts'])}
        cohorts.sort(key=lambda c: order.get(c['analysis_id'], len(order)))
        return dict(schema_version='analysis-screen-0.1', batch_id=bundle['bundle_hash'],
            period=period, periods=sorted({c['profile']['period'] for c in bundle['cohorts']}),
            total_records=len(bundle['cohorts']), counts=dict(Counter(c['profile']['risk']['status'] for c in bundle['cohorts'])),
            method=bundle['method'], cohorts=[dict(analysis_id=c['analysis_id'], profile=c['profile'],
                interpretation=c['interpretation'], background_context=c['background_context']) for c in cohorts],
            priority=bundle['priority_review'], execution=bundle['execution'], trace=bundle['trace'],
            verification=json.loads((folder / 'verification.json').read_text(encoding='utf-8')),
            configuration=config_status())

    def state(self):
        with self.lock:
            return dict(schema_version='analysis-job-0.1', job=deepcopy(self.job))

    def start(self, request):
        if not isinstance(request, dict) or set(request) - {'mode', 'analysis_id', 'period', 'allow_external'}:
            raise ValueError('분석 요청 형식을 확인해주세요.')
        mode = request.get('mode')
        if mode not in ('offline', 'gemini'):
            raise ValueError('지원하지 않는 분석 방식입니다.')
        bundle, _ = self._bundle()
        periods = {c['profile']['period'] for c in bundle['cohorts']}
        period = request.get('period', bundle['priority_review']['period'])
        if not isinstance(period, str) or period not in periods:
            raise ValueError('현재 입력에 있는 기준월을 선택해주세요.')
        aid = request.get('analysis_id')
        if mode == 'gemini':
            if request.get('allow_external') is not True:
                raise ValueError('선택 집단 요약과 공식 자료의 외부 전송 확인이 필요합니다.')
            match = next((c for c in bundle['cohorts'] if c['analysis_id'] == aid and c['profile']['period'] == period), None)
            if not match or match['profile']['target']['sex'] not in ('female', 'male') or match['profile']['risk']['status'] != 'complete':
                raise ValueError('판정 완료된 남녀 개별 집단을 선택해주세요.')
            configured = config_status()
            if not configured['gemini_configured'] or not configured['tavily_configured']:
                raise ValueError('서버의 Gemini·Tavily 키 설정을 확인해주세요.')
        elif aid is not None or request.get('allow_external') not in (None, False):
            raise ValueError('기본 분석에는 외부 호출 설정을 넣지 않습니다.')
        if not self.slot.acquire(blocking=False):
            raise BlockingIOError('다른 분석 또는 AI 추천이 실행 중입니다. 완료 후 다시 실행해주세요.')
        with self.lock:
            self.job = dict(id=uuid4().hex, status='running', mode=mode, period=period,
                analysis_id=aid, started_at=now(), message='분석·검증 중입니다. 완료 전에는 기존 결과를 유지합니다.')
            snapshot = deepcopy(self.job)
        Thread(target=self._work, args=(snapshot,), daemon=True).start()
        return dict(schema_version='analysis-job-0.1', job=snapshot)

    def _work(self, job):
        try:
            self.runner(job)
            bundle, _ = self._bundle()
            self.on_publish()
            review_status = bundle['execution']['llm_status']
            job.update(status='completed', batch_id=bundle['bundle_hash'], finished_at=now(),
                message=('데이터 분석·검증 완료. 외부 검색·AI는 호출하지 않았습니다.' if job['mode'] == 'offline' else
                    '분석·검증 완료. 외부 근거 검토 상태와 호출 기록을 확인해주세요.'),
                review_status=review_status)
        except Exception:
            # 제공자 응답·명령 출력·로컬 경로·키는 브라우저로 보내지 않는다.
            job.update(status='failed', finished_at=now(), message='분석 실행 또는 검증에 실패했습니다. 마지막 검증 결과를 유지합니다. 입력 파일과 서버 설정을 확인해주세요.')
        finally:
            with self.lock:
                self.job = job
            self.slot.release()

    def _execute(self, job):
        command = [sys.executable, str(self.root / 'scripts/integration/run_analysis_agent.py'),
                   '--period', job['period'].replace('-', '')]
        if job['mode'] == 'gemini':
            command += ['--mode', 'gemini', '--web-search', '--research-mode', 'adaptive',
                        '--analysis-id', job['analysis_id'], '--allow-external']
        environment = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
        completed = subprocess.run(command, cwd=self.root, env=environment, capture_output=True,
            timeout=600, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if completed.returncode:
            raise RuntimeError('analysis_execution_failed')
