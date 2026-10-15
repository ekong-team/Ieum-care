# Ieum care

사회적 고립 예방 및 대응 공모전 프로젝트. 데이터 정제·특징 분석·입력 검토와
팀 규칙 기반 활동 감소 신호 5단계 분류 v1을 구현했다. 개인 고립 예측이나 확률 모델은 아니다.
복지 에이전트와 별도 위험 점수는 개발 전이다.

## 폴더 구조

```text
Ieum-care/
├─ ai/
│  ├─ risk_model/
│  │  └─ classify_risk.py          # 활동 감소 5단계 판정·업종 제외 점검·근거 기록
│  ├─ welfare_agent/              # 복지 추천·프로그램 기획 예정
│  └─ evaluation/                 # 프로그램 평가·예산 분석 예정
├─ backend/                       # API 개발 예정
├─ frontend/                      # 화면 개발 예정
├─ data/
│  ├─ raw/                        # 통신·카드 원본과 정의서 (Git 제외)
│  ├─ processed/                  # 특징 CSV·분석표·검증 기록 (Git 제외)
│  └─ external/sgis/              # 경계 ZIP (Git 제외)·출처 README
├─ scripts/data_processing/
│  ├─ run_preprocessing.py        # 전체 실행 시작점
│  ├─ build_telecom_features.py   # 통신 정제
│  ├─ build_card_features.py      # 카드 정제
│  ├─ build_risk_features.py      # 월×지역×연령 특징 결합
│  ├─ analyze_features.py         # EDA·업종 민감도·입력 검토
│  ├─ validate_regions.py         # 코드·좌표·경계·공간 민감도
│  ├─ validate_processed.py       # 최종 데이터 검증·실행 기록
│  ├─ data_contract.py            # 공통 검증·계산·해시
│  └─ industry_classification.py  # 업종 분류 정의
├─ docs/
│  ├─ data_preprocessing.md       # 정제 기준·재현 방법
│  ├─ data_analysis.md            # 업종 기준·민감도·입력 후보
│  ├─ spatial_validation.md       # 지역 검증 방법·예외
│  └─ risk_model_design.md        # 팀 합의 5단계 규칙·판정 상태·실행 결과
├─ tests/
│  ├─ test_preprocessing.py       # 정제·업종·입력 검토 검사
│  ├─ test_spatial_validation.py  # 경계 판정 검사
│  └─ test_risk_model.py          # 5단계·연속성·업종 제외·보류 검사
├─ requirements.txt               # 설치 패키지 목록 하나로 관리
├─ .gitignore
└─ README.md
```

## 설치와 실행

Python 3.12 권장(최소 3.11). 프로젝트 최상위 폴더에서 실행한다.

```bash
python -m pip install -r requirements.txt
python scripts/data_processing/run_preprocessing.py
python -m unittest discover -s tests -v
```

기본 실행: 통신 정제 → 카드 정제 → 특징 결합 → EDA·업종 민감도·입력 검토 → 최종 검증.
통신 CSV 18개와 카드 TXT 2개가 `data/raw/` 바로 아래에 있어야 한다.
`data/external/sgis/bnd_sigungu_00_2025_2Q.zip`이 있다면 지역 검증까지 함께 실행한다.

```bash
python scripts/data_processing/run_preprocessing.py --with-spatial
```

분석만 다시 하려면 아래 명령을 사용한다. `--only` 없이 실행하면 해당 파일의 모든 단계를 실행한다.

| 작업 | 명령 |
| --- | --- |
| 특징 분석 전체 | `python scripts/data_processing/analyze_features.py` |
| EDA만 | `python scripts/data_processing/analyze_features.py --only eda` |
| 업종 민감도만 | `python scripts/data_processing/analyze_features.py --only industry` |
| 입력 후보 검토만 | `python scripts/data_processing/analyze_features.py --only inputs` |
| 지역 검증 전체 | `python scripts/data_processing/validate_regions.py` |
| 최종 검증 기록 갱신 | `python scripts/data_processing/validate_processed.py` |

## 데이터와 검증 범위

- `telecom_features.csv`: 월×소지역코드×좌표의 통신 특징.
- `card_features.csv`: 월×가맹점 지역×연령의 출처별 카드 특징.
- `risk_features.csv`: 통신+카드 결합 특징. 현재 6개월×2지역×6연령 = 72행·92열.
- `preprocessing_manifest.json`: 데이터 계약 검증 상태, 분석 기록 최신 여부, 환경과 파일 해시.

카드1·2 합계는 서로 더하지 않는다. 통신은 고유 방문자 수가 아니고, 카드는 거주민만의 소비가 아니다.
사회활동 후보 업종의 결제는 실제 교류를 직접 측정하지 않는다.
공간 대조는 UTM-K를 EPSG:5179로 해석한 조건부 결과이며 대상 좌표 2개 예외를 기록했다.
원본 좌표 기준·대표점 의미와 해석보류 업종의 상세 정의는 제공기관 확인 사항으로 남아 있다.
원본·생성 결과·가상환경은 Git에 올리지 않는다.

[정제 기준](docs/data_preprocessing.md) · [특징 분석과 입력 검토](docs/data_analysis.md) · [지역 경계 검증](docs/spatial_validation.md)

## 팀 규칙 기반 5단계 분류

정제와 입력 검증이 끝나고 카드1 원본이 있는 환경에서 실행한다.

```bash
python ai/risk_model/classify_risk.py
```

소비는 카드1 전체 개인 결제건수, 이동은 공통 위치의 연령 유동량 변화다.
3% 동시 감소·연속 두 번의 비교·현재 5% 감소·골프/레저타운놀이동산 제외 후 감소를 확인한다.
결과는 `data/processed/risk_model/risk_levels.csv`와 `summary.json`에 생성된다.
단계와 함께 판정완료/부분판정/판단보류 상태를 확인한다. 부분판정 단계는 확인된 하한이다.
7월을 1단계로 대체하지 않으며 원본과 기존 특징은 유지한다.
규칙과 실제 분포·제한 사항은 [위험 신호 설계](docs/risk_model_design.md)에 있다.

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
