# Ieum care

## 폴더 구조

```text
Ieum-care/
├─ frontend/
├─ backend/
├─ ai/
│  ├─ risk_model/
│  ├─ welfare_agent/
│  └─ evaluation/
├─ data/
│  ├─ raw/
│  ├─ processed/
│  │  ├─ telecom_features.csv
│  │  ├─ card_features.csv
│  │  └─ risk_features.csv
│  └─ external/
├─ scripts/
│  └─ data_processing/
│     ├─ build_telecom_features.py
│     ├─ build_card_features.py
│     ├─ industry_classification.py
│     ├─ data_contract.py
│     ├─ build_risk_features.py
│     ├─ analyze_risk_features.py
│     ├─ audit_region_mapping.py
│     ├─ validate_region_boundaries.py
│     ├─ analyze_spatial_sensitivity.py
│     ├─ analyze_industry_sensitivity.py
│     ├─ audit_model_inputs.py
│     ├─ validate_processed.py
│     └─ run_preprocessing.py
├─ docs/
├─ tests/
├─ requirements.txt
├─ requirements-spatial.txt
├─ .gitignore
└─ README.md
```

`processed`의 세 CSV 이름은 최종 산출물 구조를 나타내며, 실제 생성 여부는 처리 단계에 따라 다릅니다.
원본과 처리 결과 데이터는 Git에 업로드하지 않고 로컬에 보관합니다.
카드 스크립트는 `card_features.csv`와 업종 검토용 `industry_classification_review.csv`를 생성합니다. 특징의 한 행은 월×가맹점 지역×연령이며,
카드1 전체 금액·건수, 업종그룹별 금액·건수, 카드2 전체 금액·건수를 출처별 열로 보존합니다.
카드1·2 수치를 서로 더하지 않습니다. 고객 거주지는 카드2 합계에서 모두 포함하며,
이 표는 거주민만의 소비를 나타내지 않습니다. 업종그룹에 기록이 없는 경우의 0은
제공 데이터의 관측 기록 기준입니다. 업종 분류 v2는 활동 목적별 분류안이며 위험도 검증을 의미하지 않습니다.
분류 정의는 `industry_classification.py`, 업종별 배정과 주의사항은 [업종 분류 문서](docs/industry_classification.md)에 있습니다.
알려진 포괄 업종은 `해석보류`, 분류표에 없는 새 업종은 `미분류`로 유지합니다.
기존 중간 CSV 4개는 로컬에 보존하지만 새 실행에서는 다시 생성하지 않습니다.
`risk_features.csv`는 통신을 지역별로 요약한 뒤 카드와 월×지역×연령 단위로 결합한 특징 표입니다.
사회활동 관련 후보 업종의 건수·비중·전월 변화도 포함하며, 실제 교류나 고립 정답을 나타내지 않습니다.
활동 위축 검토 5단계 시범 규칙과 설명 근거·민감도 분석 코드를 구현했습니다. 개인 고립 위험 점수·확률의 검증을 뜻하지 않습니다. 상세 결과는 로컬에 보관하고, 공개 범위와 실행 준비는 [작업 브랜치 안내](docs/hansu_branch_handoff.md)를 참고합니다.
카드·통신 데이터와 테이블 정의서 ZIP은 로컬의 `data/raw/`에 압축 해제합니다.
카드 TXT와 통신 `flow_*.csv` 파일은 `data/raw/` 바로 아래에 놓습니다.
카드 스크립트는 이 경로에서 원본을 읽고 `data/processed/`에 결과를 저장합니다.

업종 분류 변경 후 아래 순서로 특징과 EDA를 다시 생성합니다. 통신 원본/전처리 변경 시에는 통신 스크립트부터 실행합니다.

```bash
python scripts/data_processing/build_card_features.py
python scripts/data_processing/build_risk_features.py
python scripts/data_processing/analyze_risk_features.py
```

EDA 보고서와 분석표는 `data/processed/eda/`에 저장되며 Git에서 제외됩니다.

전체 정제·EDA·최종 검증은 Python 3.12 환경에서 다음과 같이 실행합니다.

```bash
python -m pip install -r requirements.txt
python scripts/data_processing/run_preprocessing.py
python -m unittest discover -s tests -v
```

실행 환경, 결측·중복 처리, 단위, 지역 매핑의 검증 범위는 [정제 기준과 재현 방법](docs/data_preprocessing.md)에 있습니다.
`preprocessing_manifest.json`에는 입력·코드·주요 결과 해시와 환경 버전이 기록됩니다.
2025년 2분기 SGIS 경계로 조건부 공간 대조를 수행했고 대상 좌표 2개 예외를 기록했습니다.
원본 좌표계·좌표 의미 및 보류 업종 상세 정의는 제공기관 확인 사항으로 남아 있습니다.
공간 검증은 [지역 매핑 검증](docs/spatial_validation.md), 업종 처리 기준과 민감도는
[업종 검증 기록](docs/industry_validation.md), 특징별 목적·결측·관측 범위는
[모델 입력 검토](docs/model_input_review.md)에 정리했습니다.

정제 후 아래 분석을 실행하면 기존 특징을 유지하면서 검토표를 생성합니다.

```bash
python scripts/data_processing/analyze_industry_sensitivity.py
python scripts/data_processing/audit_model_inputs.py
python scripts/data_processing/validate_processed.py
```

공간 검증에는 별도로 `requirements-spatial.txt` 설치와 SGIS 경계 원본이 필요합니다.
입력 검토 후보 3개는 탐색용입니다. 현재 5단계는 설계 가정을 명시한 시범 규칙이며 독립 고립 정답에 대한 정확도 검증은 없습니다.
iPad Codespaces에서 필요한 데이터·설치·실행 순서는 [Codespaces 작업 안내](docs/codespaces_workflow.md)에 있습니다.

## 주제
사회적 고립 예방 및 대응을 위한 AI Agent 개발

## 프로젝트 목표
통신·카드 데이터를 활용해 지역 및 인구집단의
사회적 고립 위험 신호를 조기에 탐지하고,
위험 수준과 특성에 따라 적절한 복지자원을 추천한다.

또한 기존 복지 프로그램으로 해결하기 어려운 경우
AI를 활용해 신규 프로그램 또는 개선안을 제안한다.

## 주요 기능

1. 사회적 고립 위험 신호 탐지
2. 고립 위험도 5단계 분류
3. 위험 유형 및 원인 분석
4. 기존 공공·복지 서비스 추천
5. 기존 복지 프로그램 개선안 생성
6. 신규 복지 프로그램 기획
7. 프로그램 성과 및 예산 분석

## 역할

한수 담당은 데이터 분석과 수정 에이전트입니다. 수정 v2의 구현 범위는 [구현 보고](docs/revision_implementation_20261018.md), 입출력은 [팀 연결 약속](docs/revision_team_integration_v2.md)에 있습니다. 이번 브랜치는 기존 로컬 작업 기준으로 분리했으며 원격 main의 이후 추천·화면 구현과 아직 통합하지 않았습니다. 원본·가공 데이터와 상세 결과는 업로드하지 않습니다.

### 1. 데이터 분석 / 위험 분류
- 통신·카드 데이터 분석
- Feature Engineering
- 고립 위험도 산출
- 위험 유형 분석
- 모델 검증

### 2. 복지자원 추천 / 프로그램 기획
- 공공·복지 자원 데이터 구축
- 위험 단계별 복지 서비스 추천
- 기존 프로그램 개선
- 신규 프로그램 기획 Agent

### 3. 프로그램 평가 / 성과·예산 분석
- 프로그램 적합성 평가
- 예상 성과 분석
- 예산 분석
- 기존안 / 개선안 비교

### 공통
- Frontend
- 서비스 통합
- 발표 및 문서화

## 데이터
- 이동통신 유동인구 데이터
- 카드 결제 데이터
- 외부 공공·복지 데이터

※ 공모전 제공 원본 데이터는 Repository에 업로드하지 않음.

## Tech Stack

### Frontend
- React
- Vite

### Backend
- 미정

### AI / Data
- Python
- Pandas
- Scikit-learn
- LLM / RAG
