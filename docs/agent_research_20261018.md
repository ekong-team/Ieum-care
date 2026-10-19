# 에이전트 설계 근거 조사

확인일2026-10-18. 공식 기술문서·연구 원문 초록과 공개 기술 본문을 확인했다. 논문 전체 실험을 재현한 것은 아니다. 문헌의 결과를 우리 복지 프로젝트의 성능 보장으로 전이하지 않는다. 아래 적용 결정은 AI의 설계 판단이며 사용자 또는 팀이 제안했다고 기록하지 않는다.

|자료|확인한 요지|우리 적용 판단·한계|
|---|---|---|
|[Building effective agents, Anthropic, 2024-12-19](https://www.anthropic.com/engineering/building-effective-agents)|정해진 워크플로와 모델이 동적으로 경로를 정하는 에이전트를 구분. 평가-개선 패턴과 간단한 구조 우선 제안|평가·수정은 명시적 루프로 설계. 역할4개라는 이유만으로 자율성 주장하지 않음. 글이 초기 SDK환경의 한계를 명시하므로 제품·버전 추천 근거로는 사용하지 않음|
|[Effective context engineering, Anthropic, 2025-09-29](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)|도구·검색·상태 등 모델에 주는 정보의 구성 관리|원본전체 대신 선택집단 근거+배경+기획+관련 평가·자원을 전달. 자료 압축시 수치·제한사항 보존|
|[Harness design for long-running apps, Anthropic, 2026-03-24](https://www.anthropic.com/engineering/harness-design-long-running-apps)|계획·생성·평가, 구조화된 인계, 검증 기준의 운영 사례|최근 사례에서 artifact 인계와 측정가능 기준만 채택. 장시간 코딩 시스템의 성공을 복지 기획에 대한 효능 근거로 삼지 않음|
|[Persistence, LangGraph 공식문서](https://docs.langchain.com/oss/python/langgraph/persistence)|checkpoint와 thread에 상태를 보존하는 설계|LangGraph+지속 저장소를 후보로 선택. 라이브러리 설치만으로 복구·권한·중복방지 완료가 아님|
|[MCP architecture, 공식문서](https://modelcontextprotocol.io/docs/learn/architecture)|host/client/server를 통해 tools/resources/prompts 연결|공유 요구가 생길 때 도구 어댑터. MCP는 정확성 보증이나 에이전트 자체가 아님|
|[Demystifying evals for AI agents, Anthropic, 2026-01-09](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)|실행 결과와 trace, 여러 종류의 grader를 활용한 평가 설계|코드·사람·보조모델 평가를 분리하고 회귀 사례/개발외 사례를 준비. 모델이 자기 점수를 정하는 것만으로 pass하지 않음|
|[Self-Refine, Madaan et al., 2023, arXiv2303.17651](https://arxiv.org/abs/2303.17651)|여러 생성 과제에서 반복 피드백/수정의 이점을 보고|수정 루프를 시험할 동기. 해당 과제·당시 모델의 결과이며 우리 품질개선율을 주장하지 않음|
|[Large Language Models Cannot Self-Correct Reasoning Yet, Huang et al., 2023, arXiv2310.01798](https://arxiv.org/abs/2310.01798)|외부 피드백 없는 내재적 추론 자가수정의 실패·악화 가능성을 검토|근거·코드 검사·사람 피드백을 추가. 모든 현재 모델/모든 과제에서 자가수정 불가능하다는 명제로 확대하지 않음|
|[Why Do Multi-Agent LLM Systems Fail?, Cemri et al., 2025, arXiv2503.13657v3](https://arxiv.org/abs/2503.13657)|시스템설계·에이전트간 불일치·작업검증 등 실패분류|새 LLM역할 추가보다 계약·전달·종료를 먼저. 특정 프레임워크 실패율을 우리 예상치로 사용하지 않음|
|[Judging LLM-as-a-Judge, Zheng et al., 2023, arXiv2306.05685](https://arxiv.org/abs/2306.05685)|위치·장황함·자기선호 등 judge 편향 검토|수정전후 비교의 순서를 섞고 사람검토·코드 검사 병행. 논문상 사람 선호 일치가 복지 사실 정확도를 보장하지 않음|

## 최신 기술 적용 기준

2026년 하네스·평가 운영 사례와 현재 공식 상태저장·MCP 문서를 조사했다. '최신'이라는 이유만으로 새 라이브러리·새 모델·관리형 플랫폼을 추가하지 않는다. 현재 문제인 데이터 전달 누락, 구버전 평가, 반복 종료, 실제 자원 부재를 해결하는 기술만 우선한다. 모델·가격은 선정하지 않았고 성능/비용 비교도 하지 않았다.

핵심 판단: 도구와 역할을 많이 붙이는 것보다, 출처가 확인된 입력과 버전이 맞는 피드백으로 수정하고 실제로 개선됐는지 확인하는 구조가 우선이다. 이 결론은 위 자료를 종합한 우리 설계상의 판단이다.
