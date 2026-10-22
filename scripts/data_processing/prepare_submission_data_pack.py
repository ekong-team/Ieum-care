"""Build a local review bundle with explicit inclusions and unresolved approvals.

Never uploads. Does not include weather/CPI exploratory results or secrets.
"""
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'data/processed/submission_data_review_20261015'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    # Versioned review folder; never clear or recursively overwrite user folders.
    DEST.mkdir(parents=True, exist_ok=True)
    included = []

    def copy(relative, category):
        source = ROOT / relative
        assert source.is_file(), source
        target = DEST / 'files' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        included.append(dict(path=target.relative_to(DEST).as_posix(), source=relative,
                             category=category, bytes=target.stat().st_size, sha256=digest(target)))

    for relative in ['docs/analysis.md',
                     'docs/literature_and_evidence.md', 'docs/spatial_validation.md',
                     'data/processed/agent_activity_evidence.json',
                     'data/processed/activity_review_levels.csv',
                     'data/processed/external_context_20261015/population_age_sex.csv',
                     'data/processed/external_context_20261015/population_activity_review.json',
                     'data/processed/external_context_20261015/population_summary.json',
                     'data/external/public_context/context_research_20261015/population_manifest.json',
                     'scripts/data_processing/collect_population_context.py',
                     'scripts/data_processing/build_population_context_review.py']:
        copy(relative, 'analysis_and_reproduction')
    # Snapshot the basic report with all its local chart dependencies.
    for path in sorted((ROOT / 'data/processed/eda/final_analysis_20261014').rglob('*')):
        if path.is_file():
            copy(path.relative_to(ROOT).as_posix(), 'base_report')
    for path in sorted((ROOT / 'data/external/public_context/context_research_20261015').glob('mois_age_2025*.csv')):
        copy(path.relative_to(ROOT).as_posix(), 'used_external_original')
    # Provided originals and SGIS remain local dependencies, not public attachments.
    dependencies = []
    for path in sorted((ROOT / 'data/raw').iterdir()):
        if path.is_file() and path.suffix.lower() in ('.csv', '.txt'):
            dependencies.append(dict(path=path.relative_to(ROOT).as_posix(), bytes=path.stat().st_size,
                                     sha256=digest(path), kind='competition_provided_original'))
    for path in sorted((ROOT / 'data/external/sgis').glob('*.zip')):
        dependencies.append(dict(path=path.relative_to(ROOT).as_posix(), bytes=path.stat().st_size,
                                 sha256=digest(path), kind='conditional_spatial_validation_dependency'))
    # This is a human transcription of calendar date facts, not a copied website/API response.
    facts = dict(source_kind='human_transcribed_calendar_date_facts',
                 source_url='https://www.kasi.re.kr/kor/publication/post/newsMaterial/30071',
                 crosscheck_url='https://www.korea.kr/multi/visualNewsView.do?newsId=148936865',
                 scope='2025-07-01 through 2025-12-31; Saturdays and Sundays computed using Gregorian calendar',
                 dates={'2025-08-15': '광복절', '2025-10-03': '개천절', '2025-10-05': '추석연휴',
                        '2025-10-06': '추석', '2025-10-07': '추석연휴', '2025-10-08': '대체공휴일',
                        '2025-10-09': '한글날', '2025-12-25': '기독탄신일'})
    raw_calendar = DEST / 'calendar_date_facts.json'
    raw_calendar.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding='utf-8')
    calendars = []
    import calendar
    for month in range(7, 13):
        days = [date(2025, month, d) for d in range(1, calendar.monthrange(2025, month)[1]+1)]
        weekends = {d for d in days if d.weekday() >= 5}
        holidays = {d for d in days if d.isoformat() in facts['dates']}
        calendars.append(dict(month=f'2025{month:02}', days=len(days), weekend_days=len(weekends),
                              named_holiday_days=len(holidays), overlap=len(weekends & holidays),
                              weekend_or_holiday_days=len(weekends | holidays),
                              weekday_nonholiday_days=len(days)-len(weekends | holidays)))
    (DEST / 'calendar_monthly.json').write_text(json.dumps(calendars, ensure_ascii=False, indent=2), encoding='utf-8')
    joined = json.loads((ROOT / 'data/processed/external_context_20261015/population_activity_review.json').read_text(encoding='utf-8'))
    for record in joined['records']:
        record['calendar_context'] = next(c for c in calendars if c['month'] == record['analysis_id'][:6])
    joined['schema_version'] = 'submission-review-context-v1'
    joined['release_status'] = 'draft_pending_team_review'
    joined['user_decisions'] = dict(confirmed_on='2026-10-15',
        result_label='활동 위축 검토 단계', interpretation='집단 활동 변화의 참고 근거; 개인 고립 확정 아님',
        included_context=['resident_population', 'calendar'], excluded_context=['weather', 'CPI'],
        context_use='배경정보만 병기; 점수 가중치 미추가',
        sensitivity='기존 시범 기준과 조건 변경 결과를 함께 제시',
        team_consensus='not_recorded')
    joined['excluded_context'] = ['weather', 'CPI']
    (DEST / 'analysis_with_population_calendar.json').write_text(json.dumps(joined, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    original = json.loads((ROOT / 'data/processed/agent_activity_evidence.json').read_text(encoding='utf-8'))
    assert [r['analysis_evidence'] for r in joined['records']] == original['records']
    assert len(joined['records']) == len({r['analysis_id'] for r in joined['records']}) == 72
    assert len(dependencies) >= 20
    decisions = '''# 데이터 제출 전 검토·결정표

2026-10-15. 분석 준비본이며 팀 합의·공모전 최종 제출 완료가 아니다.

|항목|이번 준비본의 결정|상태|
|---|---|---|
|분석 이름|활동 위축 검토 단계; 고립 진단·확률로 표현하지 않음|사용자 확정 2026-10-15|
|기본 기준|3%·큰 감소5%·동시감소2회·관측90%/75%|팀 합의 대기|
|7월|전월 카드·통신 부재로 보류; 외부6월 인구로 해제하지 않음|구현 반영|
|춘천40대|업종 제외 민감도와 함께 제시|구현 반영|
|인구|공식무료·이용허락범위 제한없음, 원본7개·조회조건·해시 보존|배경정보 포함, 사용자 확정|
|달력|공식 발표에서 날짜 사실만 수동 전사, 주말 계산, 웹 사진·화면 복제 없음|배경정보 포함, 사용자 확정|
|기온·물가|현재 수집 경로의 개별 재이용 표시 확인 실패; 탐색 자료는 별도 보관|이번 준비본 제외, 사용자 확정|
|배경자료 적용|단계 가중치 추가 없이 기존 분석 옆에 병기|사용자 확정|
|민감도|기준·업종·지속 조건을 바꿨을 때의 결과 차이를 기본 결과와 함께 설명|사용자 확정|
|공간|조건부 좌표 해석·예외 병기, SGIS 신청 시 동의한 조건과 결과물 제출 의무 확인|팀 확인 대기|
|원본|공모전 제공20개와 공간ZIP은 해시·경로만 기록|별도 로컬 의존성|
|최종 제출|대회 요구 형식·첨부 범위·팀 기준 승인 후 제출본 구성|미제출|

## 팀이 기록할 내용

- 검토자·검토일: 미기입
- 사용자 확인(2026-10-15): 결과 명칭·고립 확정 금지·인구/달력 배경정보 포함·기온/물가 제외·민감도 병기 확정. 다른 팀원 전체 합의는 별도 미기록.
- 기준안 승인/변경/보류와 사유: 미기입
- 공간 제공조건·기관 좌표 정의 확인 결과: 미기입
- 최종 제출물 규격·외부 원본 첨부 확인자: 미기입

새 성별 카드·통신 분석, 강수·적설·강남AWS·장기 계절성은 이번 완료 범위 밖이다. 인구·기온·물가로 단계 가중치를 재학습한 적이 없다.
'''
    (DEST / 'TEAM_REVIEW.md').write_text(decisions, encoding='utf-8')
    source_doc = '''# 외부자료 출처·수집 방법

인구: 행정안전부 연령별 주민등록 인구, https://jumin.mois.go.kr/ageStatMonth.do
무료·이용허락범위 제한없음 명세: https://www.data.go.kr/data/3033304/fileData.do
조회: 2025년6~12월, 전국 시군구·10세 구간·남녀/계, 공개 CSV POST 다운로드.
정확한 요청주소·매개변수·해시는 첨부 population_manifest.json에 보존. CP949 원본7개 포함.
춘천5111000000·강남1168000000에서 10~50대와60세 이상을 추출, 남+여=계 및 모든 연령 합계를 검증.
분석 연결은 남녀 합계만 사용. 6월은 인구 전월비 기준이며 7월 카드·통신 비교를 만들지 않는다.

달력: 한국천문연구원 2025년도 월력요항 발표, 2024-06-20,
https://www.kasi.re.kr/kor/publication/post/newsMaterial/30071
교차확인: 행정안전부 달력 날짜 안내 https://www.korea.kr/multi/visualNewsView.do?newsId=148936865
원문 화면·사진·도표를 복제하지 않고 날짜 사실을 사람이 전사한 calendar_date_facts.json이 입력 원본이다.
토·일요일은 표준 달력 계산, 휴일은 합집합으로 계산하며 임의 휴무일은 추가하지 않는다.

제외 자료: 기상청 웹 기온 및 국가데이터처 공개 조회 CPI. 열람·탐색 수집 완료는 재이용 허용 확인과 다르다.
기상청 https://www.weather.go.kr/kma/guide/copyright.jsp 와
국가데이터처 https://mods.go.kr/menu.es?mid=a10706000000 의 정책을 2026-10-15 재확인했다.
공공누리 미부착 자료의 사전 협의 안내가 있으므로 별도 허용을 추정하지 않았다.
외부 연락·문의 발송·유료 구매·공개 업로드·대회 제출은 하지 않았다.
'''
    (DEST / 'SOURCES_AND_COLLECTION.md').write_text(source_doc, encoding='utf-8')
    readme = '''# 데이터 분석 제출 준비본

기본 카드·통신 분석 + 인구·달력 배경을 묶은 로컬 검토용 파일이다. 기온·물가는 제외했다.
전체 결과: files/data/processed/eda/final_analysis_20261014/report.html
연결 JSON: analysis_with_population_calendar.json (72건, 기존 단계 불변)
팀 결정: TEAM_REVIEW.md / 출처·수집: SOURCES_AND_COLLECTION.md

external_raw.zip은 포함한 외부 원본(인구7CSV+수동 달력 날짜 입력)만 별도로 담는다.
공모전 제공 카드·통신20개와 SGIS는 복제하지 않고 dependency_manifest.json의 경로·해시로 참조한다.
따라서 이 준비본은 전체 원본을 포함한 독립 재현 패키지가 아니다. 재현 시 해당 로컬 의존성이 필요하다.
SGIS는 조건부 공간 검증용이며 제출·재배포 범위는 신청 시 동의한 조건 확인이 필요하다.
공개 Git에 올리지 말고, 대회가 허용한 제출 경로와 최종 규격을 확인한 뒤 사용한다.
팀 기준 합의와 최종 제출 형식 확인은 남아 있다. 합의·제출 완료로 표시하지 않는다.
'''
    (DEST / 'README.md').write_text(readme, encoding='utf-8')
    (DEST / 'dependency_manifest.json').write_text(json.dumps(dependencies, ensure_ascii=False, indent=2), encoding='utf-8')
    with zipfile.ZipFile(DEST / 'external_raw.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in included:
            if item['category'] == 'used_external_original':
                archive.write(DEST / item['path'], Path(item['source']).name)
        archive.write(raw_calendar, raw_calendar.name)
    inventory = []
    for path in sorted(DEST.rglob('*')):
        if path.is_file() and path.name != 'package_manifest.json':
            inventory.append(dict(path=path.relative_to(DEST).as_posix(), bytes=path.stat().st_size, sha256=digest(path)))
    package = dict(status='draft_pending_team_review', generated_at_utc=datetime.now(timezone.utc).isoformat(),
                   excluded=['weather', 'CPI', 'provided_raw_copies', 'sgis_zip_copy'],
                   file_count=len(inventory), files=inventory,
                   validations=['72 unique analysis IDs', 'all original evidence records unchanged', 'CPI/weather absent from release JSON'])
    (DEST / 'package_manifest.json').write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding='utf-8')
    # Separate ready-to-review status note in version-controlled docs.
    (ROOT / 'docs/data_submission_ready_review_20261015.md').write_text(
        '# 데이터 분석 제출 준비 상태\n\n2026-10-15. 로컬 검토 묶음 생성 완료.\n\n'
        '위치: data/processed/submission_data_review_20261015/README.md\n\n'
        '포함: 기본72개 카드·통신 분석, 보고서·그래프, 인구 원본7개·달력 날짜 입력, 출처·수집 조건·해시, 팀 결정표.\n\n'
        '제외: 기온·물가(현재 수집경로 재이용 허용 표시 미확인). 탐색 결과는 별도 유지한다. API 인증키나 실제 담당자 허용 없이 채택했다고 표시하지 않는다.\n\n'
        '원본20개 및 SGIS는 해시·경로 참조이며 독립 재현/최종 제출 묶음이 아니다. 공개 업로드·제출·외부 문의 발송 없음.\n\n'
        '남은 실제 사람 결정: 시범 기준·표현 팀 합의, SGIS 동의조건·좌표 정의, 최종 제출 규격·첨부 범위 확인.\n', encoding='utf-8')
    print(json.dumps(dict(bundle=str(DEST), packaged_files=len(inventory), provided_dependencies=len(dependencies),
                          external_zip_bytes=(DEST / 'external_raw.zip').stat().st_size, records=72), ensure_ascii=False))


if __name__ == '__main__':
    main()
