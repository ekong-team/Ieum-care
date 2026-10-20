# 분석 에이전트 실행 환경

Python3.12와 프로젝트 .venv-agent를 사용한다. 기존 .venv는 원본 분석·그래프·공간 패키지 기록이 있어 유지한다. 가상환경 자체를 Git이나 ZIP에 넣지 않는다.

새 PC에서는 프로젝트 루트에서 다음처럼 만든다.

```powershell
py -3.12 -m venv .venv-agent
./.venv-agent/Scripts/python.exe -m pip install -r requirements-agent.txt
```

requirements-agent.txt는 현재 분석 Agent의 검증된 직접 의존성이다. NumPy·Pandas도 포함하므로 성별 전처리와 Agent를 같은 환경에서 실행할 수 있다. 팀 공통 requirements.txt와 LangGraph/Pydantic의 정확한 고정 버전이 다르므로 두 목록을 한 번의 pip install에 동시에 넣지 않는다. 현재 환경의 전체 고정 버전은 requirements-agent-lock.txt다.

기본 카드·통신/성별 전처리는 NumPy·Pandas를 사용한다. 과거 상세 보고서 재생성에는 matplotlib, 선택적 경계 검증에는 shapely·pyproj·pyshp가 추가로 필요하다. 그 환경은 requirements-analysis.txt와 팀 공통 requirements.txt를 참고해 별도로 구성한다. 일부 환경에서 공간 테스트를 생략했다는 것을 경계 검증 완료로 표현하지 않는다.

설정 확인은 키 값을 노출하지 않는다.

```powershell
./.venv-agent/Scripts/python.exe scripts/integration/run_analysis_agent.py --check-config
./.venv-agent/Scripts/python.exe -m unittest discover -s tests -p "test_analysis*.py"
```

기본 임시폴더 권한 때문에 설치/테스트가 실패할 때는 프로젝트 안 임시폴더를 사용한다.

```powershell
New-Item -ItemType Directory -Force .venv-agent/test_tmp
$env:TEMP=(Resolve-Path .venv-agent/test_tmp).Path
$env:TMP=$env:TEMP
```

위 명령은 현재 프로세스의 임시 경로만 바꾼다. 시스템 권한을 변경하지 않는다. 과거 제안·사용자 선택·검증 경위는 troubleshooting.md에 실제 기여대로 기록한다.

전체 데이터 흐름은 [한수 분석 처리 과정](hansu_analysis_pipeline.md)을 참고한다. 실제 API 호출은 명시적 옵션·설정·승인된 집단/횟수 범위를 확인한 뒤 수행한다.
