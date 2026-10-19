"""무료 TAGO 파일 품질 확인. 시 전체 정류장 기록을 구 단위로 오인하지 않는다."""
from pathlib import Path
import hashlib
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'data/external/public_context/bus_stops_20251031.csv'


def main():
    d = pd.read_csv(SOURCE, encoding='cp949', dtype=str)
    required = ['정류장번호','정류장명','위도','경도','정보수집일','도시명']
    if not set(required).issubset(d.columns):
        raise ValueError('버스정류장 원본 스키마 확인 필요')
    lat, lon = pd.to_numeric(d['위도'],errors='coerce'), pd.to_numeric(d['경도'],errors='coerce')
    valid = lat.between(33,39) & lon.between(124,132)
    selected = d.loc[d['도시명'].isin(['서울특별시','강원특별자치도 춘천시'])].copy()
    selected['좌표범위통과'] = valid.loc[selected.index]
    out = ROOT/'data/processed/eda/public_context'
    out.mkdir(parents=True,exist_ok=True)
    selected.to_csv(out/'seoul_chuncheon_bus_records.csv',index=False,encoding='utf-8-sig')
    report = {'source_url':'https://www.data.go.kr/data/15067528/fileData.do',
        'download_url':'https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003558143&fileDetailSn=1&insertDataPrcus=N',
        'checked_date':'2026-10-13', 'cost':'무료', 'license':'이용허락범위 제한 없음',
        'sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        'actual_rows':len(d), 'portal_described_rows':206022,
        'portal_row_count_matches':len(d)==206022,
        'dates':sorted(d['정보수집일'].dropna().unique().tolist()),
        'duplicate_ids':int(d['정류장번호'].duplicated().sum()),
        'invalid_or_missing_coordinates':int((~valid).sum()),
        'target_city_record_counts':selected['도시명'].value_counts().to_dict(),
        'integration_status':'not_in_risk_model',
        'limitations':['포털 행 수와 실제 파일 행 수 불일치 확인; 원본 해시·실제 수 보존',
            '서울특별시 표시는 강남구가 아님; 경계 공간 대조 필요',
            '정류장 ID 수는 물리적 정류장 수나 이용 가능 교통량과 같지 않음',
            '2025-10-31 단일 시점; 월별·연령별 값으로 복제해 독립 표본 취급 금지',
            '거리·배차·운행시간과 실제 이용 장애 확인 전 접근성 점수 생성 금지']}
    (out/'bus_context_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
