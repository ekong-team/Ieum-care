# SGIS 행정경계 원본

- 출처: https://sgis.mods.go.kr/view/pss/openDataIntrcn
- 자료: 센서스용 행정구역 경계, 시군구, 전국, 2025년 2분기
- 파일: `bnd_sigungu_00_2025_2Q.zip`
- 내부 `BASE_DATE`: 20250630
- 내부 PRJ: EPSG:5179 (GRS80, UTM-K)
- 사용자 파일 수령 및 로컬 재현일: 2026-10-14. 실제 다운로드 날짜는 별도 확인 필요.
- ZIP SHA-256: `3413451b0243d7f3a4b41636fec27bbb19cf855e7f7bdca84bd33fbad91fcbbc`
- 재현 결과: `docs/spatial_revalidation_20261014.md`. 통신 좌표 EPSG:5179 해석에 따른 조건부 결과.
- ZIP 안의 SHP·SHX·DBF·PRJ·CPG 파일을 함께 유지한다.

원본 ZIP은 Git에서 제외한다. 팀원은 SGIS에서 같은 자료를 신청하여 이 폴더에 둔다.
자료 출처를 결과물에 명시하고, 신청 화면에서 동의한 결과물 제출 조건을 이행한다.
검증 실행 시 원본 SHA-256과 라이브러리 버전을 `data/processed/spatial_validation_summary.json`에 기록한다.
