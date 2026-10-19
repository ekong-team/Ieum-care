# 수정 에이전트 개발 환경

2026-10-18 갱신: `.venv-agent`에 실제 LangGraph·SQLite 체크포인트·jsonschema를 설치하고 검증했다. 정확한 직접 의존성은 requirements-agent.txt, 전체 고정 버전은 requirements-agent-lock.txt. 최신 실행 안내는 study_revision_20261019.md와 revision_implementation_20261018.md를 우선한다. 아래 '설치하지 않았다'는 10월16일 당시 기록이다.

2026-10-16 구성·실행 확인. Python3.12.14, pip25.0.1, 프로젝트 `.venv-agent`.
기존 `.venv`는 분석 패키지와 캐시를 보관하므로 보존한다. `.venv-agent`는 Git 제외다.

## 실행 방법

PowerShell에서 프로젝트 폴더로 이동한다.

```powershell
Set-Location 'C:/Users/namo2/Desktop/ai빅콘테스트/Ieum-care'
& './.venv-agent/Scripts/python.exe' --version
& './.venv-agent/Scripts/python.exe' -m pip --version
& './.venv-agent/Scripts/python.exe' -m unittest discover -s tests -p test_revision_agent.py
```

환경의 Python을 직접 지정하므로 활성화 명령 없이 같은 환경으로 실행된다. 검증에서 테스트6개 통과.
현재 외부 모델 SDK·LangGraph·LangChain·분석 패키지는 설치하지 않았다. 기본 수정 코드에 불필요한 의존성을 먼저 추가하지 않는다. pip check 성공은 현재 설치 패키지의 의존성 충돌이 없다는 뜻이며 모델 성능 검증은 아니다.

## 재생성과 이번 오류

현재 환경은 Codex 번들 Python을 기반으로 생성됐다. 다른 PC에서는 팀이 설치한 Python3.12의 경로를 사용해 새 환경을 만들고 필요 패키지 목록으로 구성한다. 이 폴더를 복사해 공유하지 않는다.

이번 생성은 ensurepip 기본 임시폴더 권한 오류로 일부만 생성된 후, 프로젝트 내부 임시폴더로 재시도해 완료했다. 상세 원인·사용자 선택·해결·검증은 troubleshooting.md의 ENV-002에 기록했다. 시스템의 실행 정책이나 권한은 바꾸지 않았다.
