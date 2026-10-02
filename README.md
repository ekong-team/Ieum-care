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
│     ├─ build_risk_features.py
│     └─ analyze_risk_features.py
├─ docs/
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
위험 점수와 5단계 분류는 아직 구현 전입니다.
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
