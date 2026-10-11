# iPad Codespaces에서 이어서 작업하기

Codespaces는 PC 폴더와 별도 환경이다. Git에 올린 코드·문서는 가져오지만,
Git에서 제외한 raw/processed 데이터와 SGIS ZIP은 자동으로 복사되지 않는다.
PC에서 코드를 커밋·push한 뒤 같은 저장소의 Codespace를 연다.
가능하면 PC에서 해당 Codespace에 데이터를 한 번 준비한 뒤 iPad에서 같은 Codespace를 다시 사용한다.

아래 명령은 Codespaces 터미널의 Bash에서, README.md가 있는 프로젝트 최상위 폴더에서 실행한다.
현재 프로젝트에 별도 devcontainer 설정은 없다. 먼저 Python 버전을 확인한다.

```bash
python3 --version
```

Python 3.12 권장, 최소 3.11이다. 3.9/3.10이라면 해당 인터프리터로 설치하지 말고
Codespaces의 Python 개발 컨테이너를 3.12로 설정하거나 사용 가능한 3.12 인터프리터로 환경을 만든다.
[GitHub Python 환경 설정 안내](https://docs.github.com/en/codespaces/setting-up-your-project-for-codespaces/adding-a-dev-container-configuration/setting-up-your-python-project-for-codespaces)

## 최초 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Python 3.12가 별도 `python3.12` 명령으로 제공되는 경우 첫 줄에서 그 명령을 사용한다.
Windows의 `.venv` 폴더는 복사하지 않는다. Codespaces에서 Linux용 가상환경을 새로 만든다.
아래 `python` 명령들은 가상환경을 활성화한 터미널에서 실행한다.

## A. 검증된 특징으로 위험도 개발을 이어갈 때

현재 PC에서 검증한 다음 파일을 Codespace의 `data/processed/`에 복사한다.

- `risk_features.csv`
- `card_features.csv`
- `industry_classification_review.csv`

세 파일이면 현재 입력 검토와 업종 민감도 분석을 실행할 수 있다.
작업 시 근거 확인을 위해 PC의 `preprocessing_manifest.json`과 검토 결과 JSON도 함께 보관하는 것이 좋다.
이 경로는 검증된 특징을 가져와 사용하는 것이며 Codespaces에서 원본 정제를 재검증하는 것은 아니다.

```bash
source .venv/bin/activate
python scripts/data_processing/analyze_industry_sensitivity.py
python scripts/data_processing/audit_model_inputs.py
python -m unittest discover -s tests -v
```

공간 라이브러리를 설치하지 않았다면 공간 테스트 3개는 `skipped`로 표시된다.
이 상태를 전체 공간 테스트 통과로 표현하지 않는다.
현재 위험 모델 실행 파일은 아직 없으므로 `ai/risk_model/`에서 실행할 프로그램은 없다.
이후 위험도 개발에서 모델 실행 방법을 추가한다.

## B. 원본부터 정제·분석 전체를 재현할 때

`data/raw/` 바로 아래에 다음 20개 원본을 준비한다.

- `flow_age_pop_202507.csv`~`flow_age_pop_202512.csv`: 6개
- `flow_time_pop_202507.csv`~`flow_time_pop_202512.csv`: 6개
- `flow_wkdy_pop_202507.csv`~`flow_wkdy_pop_202512.csv`: 6개
- `신한카드_빅콘테스트2026_데이터1.txt`
- `신한카드_빅콘테스트2026_데이터2.txt`

테이블 정의서 XLSX는 해석 근거이므로 함께 보관하면 좋지만 파이프라인 실행 필수 파일은 아니다.
ZIP 안에 폴더가 중첩된 경우 실제 CSV/TXT가 `data/raw/` 바로 아래에 오도록 한다.

```bash
source .venv/bin/activate
python scripts/data_processing/run_preprocessing.py
python scripts/data_processing/audit_region_mapping.py
python scripts/data_processing/analyze_industry_sensitivity.py
python scripts/data_processing/audit_model_inputs.py
```

`run_preprocessing.py` 하나가 통신 정제 → 카드 정제 → 특징 결합 → EDA → 최종 검증을 실행한다.
통합 실행 뒤 업종·입력 검토는 위 두 분석 명령으로 별도 갱신한다.
`industry_classification.py`와 `data_contract.py`는 다른 스크립트가 읽는 공통 정의이므로 단독 실행하지 않는다.

공간 대조도 재현하려면 `data/external/sgis/bnd_sigungu_00_2025_2Q.zip`을 준비하고 추가로 실행한다.

```bash
python -m pip install -r requirements-spatial.txt
python scripts/data_processing/validate_region_boundaries.py
python scripts/data_processing/analyze_spatial_sensitivity.py
```

모든 분석 후 최종 기록과 테스트를 갱신한다.

```bash
python scripts/data_processing/validate_processed.py
python -m unittest discover -s tests -v
```

원본 정제를 다시 수행하면 이전 분석 기록은 해시 확인이 필요하다.
`status: passed`만 읽지 말고 manifest의 `spatial_validation`, `industry_sensitivity`,
`model_input_review`가 최신인지 함께 확인한다. 오류가 나면 이후 단계를 계속 진행하지 않는다.

## 이후 매번 접속할 때

같은 Codespace에 데이터와 가상환경이 그대로 있다면 설치·전체 정제를 매번 반복할 필요가 없다.

```bash
source .venv/bin/activate
git status
git branch --show-current
```

다른 PC에서 변경한 코드가 있다면 현재 변경사항을 확인하고 정리한 뒤 해당 브랜치의 최신 커밋을 가져온다.
가상환경·데이터는 Git으로 기기 간 동기화되지 않는다.
코드·원본·분류 정의가 바뀐 경우 영향받는 정제/분석부터 다시 실행한다.

## 위험도 브랜치 시작

PC에서 main의 정제 마무리 커밋을 push한 뒤 Codespace에서 작업 트리가 깨끗한지 확인한다.
아직 브랜치가 없다면:

```bash
git switch main
git pull --ff-only
git switch -c hyeonji/risk-model
git push -u origin hyeonji/risk-model
```

이미 원격 브랜치가 있다면 새로 만들지 말고:

```bash
git fetch origin
git switch hyeonji/risk-model
```

위험도 설계 전 남은 CRS·좌표 의미·업종 정의 확인 사항은
[모델 입력 검토](model_input_review.md)와 [정제 기준](data_preprocessing.md)에 명시되어 있다.
현재 확인은 Windows 로컬에서 수행했으며 이 문서의 Linux 명령을 실제 Codespace에서 실행한 것은 아니다.
