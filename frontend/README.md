# 이음케어 React 프론트엔드

React + Vite로 구성한다. 복지 추천과 기획 요청 전달함을 제공하며, 대시보드·분석·평가·예산은 팀원 구현을 위한 빈 화면이다. 주소 해시로 탭을 이동한다.

## 설치·실행

Node.js 22.12 이상과 npm이 필요하다. 실제 검증 환경은 Node.js 24다. Python 환경과 API 키는 기존 프로젝트 설정을 사용한다. 비밀 키는 루트 `.env`에만 두며 `VITE_` 환경 변수로 옮기지 않는다.

프로젝트 루트에서:

```powershell
cd frontend
npm ci
npm run build
cd ..
python backend/server.py
```

<http://127.0.0.1:5175/#recommendations>에서 확인한다. Python 서버는 `frontend/dist`만 제공한다. React 화면 수정 후에는 `npm run build`를 다시 실행한다. node_modules·dist는 Git에 올리지 않으며 package.json과 package-lock.json을 함께 커밋한다.

개발 중에는 두 터미널을 사용한다.

```powershell
# 터미널 1: 프로젝트 루트
python backend/server.py
```

```powershell
# 터미널 2: 프로젝트 루트
cd frontend
npm run dev
```

개발 화면은 <http://127.0.0.1:5173/#recommendations>이다. `/api`만 5175 Python 서버로 전달한다. 5173과 5175는 주소가 달라 브라우저 저장 결과도 별도로 유지된다. 기존 결과가 없다고 자동 재조회하지 않는다.

## 파일

```text
frontend/
├─ index.html                       # React 진입 HTML
├─ package.json / package-lock.json # 실행 명령·라이브러리 고정 버전
├─ vite.config.js                   # 개발 API 프록시·빌드·테스트 설정
└─ src/
   ├─ main.jsx                      # React 마운트·스타일 연결
   ├─ App.jsx                       # 공통 메뉴·페이지·기획 전달함
   ├─ useWelfare.js                 # 분석 수신·순차 추천·중지·결과 저장
   ├─ domain.js                     # API·계약·검토표·기획 요청 변환
   ├─ styles.css                    # 기존 초록 계열 디자인·반응형 스타일
   ├─ components/
   │  └─ RecommendationParts.jsx    # 대상 설정·분석 목록·자원 카드·기획 준비
   ├─ App.test.jsx / domain.test.js # React 동작·데이터 계약 자동 검사
   └─ test-setup.js                 # 화면 테스트 초기화
```

## 현재 동작과 정리한 기능

- ‘담당자가 확인한 지원 필요’ 체크박스는 지원 목적과 중복되어 제거했다. 담당자는 지원 목적만 선택한다. 팀원의 연결 입력에 이미 있는 `confirmed_support_needs`는 그대로 전달하고, 지역·연령·성별을 바꾸어 일반 탐색하면 빈 목록을 전달한다. 선택한 지원 목적을 확인된 필요로 자동 변환하지 않는다.

- 화면은 실시간 Tavily·Gemini 추천만 제공한다. 저장 자료 테스트 모드, 예시 위험도 버튼, 수동 JSON 입력은 제거했다. 집단 선택은 팀원의 분석 결과를 사용하며 지역·연령·성별을 직접 바꾸면 분석 없이 일반 탐색한다.
- 분석 수신·집단 선택·화면 진입은 검색·LLM을 실행하지 않는다. 일괄 추천은 첫 오류에서 중지하며 자동 재시도·다른 모델 전환·저장 자료 대체는 하지 않는다.
- 같은 배치·조건의 실시간 결과만 브라우저에서 복원한다. 과거 offline 결과는 실시간 결과로 복원하지 않는다. 성공 0개도 일괄 실행에서 건너뛰며 개별 추천 버튼은 새 조회다. 선택 자원·기획 프롬프트는 브라우저에 저장하지 않는다.
- 2차 대응 검토표는 후보 확보·미확보·실패·미조회를 구분한다. 위험 단계·1차 순위는 유지하며 최종 지원 순위를 확정하지 않는다.
- 기획 요청 미리보기·JSON 내려받기·서버 검증·로컬 전달함 저장을 유지한다. 실제 기획 Agent는 연결 전이며 기획서는 생성하지 않는다. 요청을 수정하면 이전 미리보기를 폐기한다.
- Python의 offline 조회·그래프 테스트용 엔진은 팀원 코드·자동 검증에 사용되어 유지했다. 화면의 불필요한 테스트 조작만 제거했다. 구형 DOM 테스트는 실제 React 테스트로 교체했다.

## 검증

```powershell
cd frontend
npm test
npm run build
```

자동 테스트는 외부 검색·모델을 호출하지 않는다. API 입력·기획 요청 형식은 [복지 추천 문서](../docs/welfare_agent.md)를 참고한다.
