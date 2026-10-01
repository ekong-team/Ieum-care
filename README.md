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
│     └─ build_card_features.py
├─ docs/
├─ .gitignore
└─ README.md
```

`processed`의 세 CSV 이름은 최종 산출물 구조를 나타내며, 실제 생성 여부는 처리 단계에 따라 다릅니다.
원본과 처리 결과 데이터는 Git에 업로드하지 않고 로컬에 보관합니다.
카드 스크립트는 `card_features.csv` 하나를 생성합니다. 한 행은 월×가맹점 지역×연령이며,
카드1 전체 금액·건수, 업종그룹별 금액·건수, 카드2 전체 금액·건수를 출처별 열로 보존합니다.
카드1·2 수치를 서로 더하지 않습니다. 고객 거주지는 카드2 합계에서 모두 포함하며,
이 표는 거주민만의 소비를 나타내지 않습니다. 업종그룹에 기록이 없는 경우의 0은
제공 데이터의 관측 기록 기준입니다. 업종 분류는 초기안이며 위험도 검증을 의미하지 않습니다.
기존 중간 CSV 4개는 로컬에 보존하지만 새 실행에서는 다시 생성하지 않습니다.
`risk_features.csv`는 통신·카드 결합 단계에서 생성할 예정입니다.
카드·통신 데이터와 테이블 정의서 ZIP은 로컬의 `data/raw/`에 압축 해제합니다.
카드 TXT와 통신 `flow_*.csv` 파일은 `data/raw/` 바로 아래에 놓습니다.
카드 스크립트는 이 경로에서 원본을 읽고 `data/processed/`에 결과를 저장합니다.

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
