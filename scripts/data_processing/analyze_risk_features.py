"""위험도 설계 전 EDA. 실행: python scripts/data_processing/analyze_risk_features.py

원본/특징 파일은 변경하지 않고 data/processed/eda/에 분석표와 HTML 보고서를 저장.
필요 패키지: pandas, numpy. 보고서의 그래프는 외부 서비스 없이 SVG로 표시한다.
이 분석은 관측된 활동 변화를 설명하며 사회적 고립의 정답을 만들어내지 않는다.
"""

from html import escape
from pathlib import Path
import json

import numpy as np
import pandas as pd

import build_risk_features as builder
from industry_classification import ALL_GROUPS, classification_table


REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "data" / "processed" / "eda"
KEYS = builder.KEYS
CHANGE_COLS = ["통신_연령유동량_전월변화율", "카드1_전체_결제건수_전월변화율",
               "카드2_결제건수_전월변화율"]


def save_table(name, table):
    table.to_csv(OUTPUT / f"{name}.csv", index=False, encoding="utf-8-sig")


def audit_raw_telecom():
    """월별 원본에 중복 키·부분 결측이 있는지 확인. 파생변수 이전 품질 점검."""
    rows = []
    for kind in ["age", "time", "wkdy"]:
        paths = sorted((REPO / "data" / "raw").glob(f"flow_{kind}_pop_*.csv"))
        if not paths:
            raise FileNotFoundError(f"원본 통신 {kind} 파일이 없습니다.")
        for path in paths:
            raw = pd.read_csv(path, sep="|", dtype={"STD_YM": str, "BLOCK_CD": str})
            keys = ["STD_YM"] + builder.LOCATION
            metrics = raw.drop(columns=keys).apply(pd.to_numeric, errors="raise")
            missing = metrics.isna().sum(axis=1)
            rows.append({"파일": path.name, "종류": kind, "행수": len(raw),
                         "완전중복행수": int(raw.duplicated().sum()),
                         "중복제거후_중복키수": int(raw.drop_duplicates().duplicated(keys).sum()),
                         "키결측행수": int(raw[keys].isna().any(axis=1).sum()),
                         "부분결측행수": int(((missing > 0) & (missing < len(metrics.columns))).sum()),
                         "전체결측행수": int((missing == len(metrics.columns)).sum()),
                         "음수셀수": int((metrics < 0).sum().sum()),
                         "무한대셀수": int(np.isinf(metrics.to_numpy(dtype=float)).sum())})
    return pd.DataFrame(rows)


def audit_industries():
    """현재 업종 그룹 밖의 실제 업종을 나열. 분류 기준은 임의로 바꾸지 않는다."""
    path = REPO / "data" / "raw" / "신한카드_빅콘테스트2026_데이터1.txt"
    raw = pd.read_csv(path, sep="\t", encoding="cp949", dtype=str,
                      usecols=["SEX_CCD", "AGE_CCD", "MCT_RY_CD", "USE_CNT"])
    if (raw["SEX_CCD"].eq("법인") != raw["AGE_CCD"].eq("법인")).any():
        raise ValueError("카드 법인 표시 불일치")
    raw = raw.loc[~raw["SEX_CCD"].eq("법인")].copy()
    raw["USE_CNT"] = pd.to_numeric(raw["USE_CNT"], errors="raise")
    grouped = raw.groupby("MCT_RY_CD", dropna=False)["USE_CNT"].sum().rename("결제건수").reset_index()
    grouped = grouped.rename(columns={"MCT_RY_CD": "업종"}).merge(
        classification_table(), on="업종", how="left", validate="one_to_one")
    grouped["업종그룹"] = grouped["업종그룹"].fillna("미분류")
    grouped = grouped.rename(columns={"업종그룹": "현재그룹"})
    grouped["전체결제건수비중"] = grouped["결제건수"] / grouped["결제건수"].sum()
    return grouped.sort_values("결제건수", ascending=False)


def heatmap(data, title, limit=0.2, percent=True, diverging=True):
    """고정 색 범위로 월별·집단별 변화 비교. 색은 위험 등급을 의미하지 않음."""
    cell_w, cell_h, left, top = 94, 32, 170, 58
    width, height = left + cell_w * len(data.columns) + 10, top + cell_h * len(data) + 34
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
             f'<text x="8" y="22" font-size="16" font-weight="bold">{escape(title)}</text>']
    for j, col in enumerate(data.columns):
        parts.append(f'<text x="{left+j*cell_w+cell_w/2}" y="45" text-anchor="middle">{escape(str(col))}</text>')
    for i, (index, row) in enumerate(data.iterrows()):
        label = " · ".join(map(str, index)) if isinstance(index, tuple) else str(index)
        y = top + i * cell_h
        parts.append(f'<text x="4" y="{y+21}">{escape(label)}</text>')
        for j, value in enumerate(row):
            if pd.isna(value):
                color, label = "#e5e7eb", "—"
            else:
                strength = min(abs(float(value)) / limit, 1) if diverging else min(max(float(value), 0), 1)
                target = (185, 220, 247) if value >= 0 or not diverging else (250, 185, 175)
                color = '#' + ''.join(f'{round(255+(c-255)*strength):02x}' for c in target)
                label = f"{value:.1%}" if percent else f"{value:.3f}"
            x = left + j * cell_w
            parts.append(f'<rect x="{x}" y="{y}" width="{cell_w-2}" height="{cell_h-2}" fill="{color}"/>')
            parts.append(f'<text x="{x+cell_w/2}" y="{y+21}" text-anchor="middle">{label}</text>')
    legend = "음수: 주황 / 양수: 파랑 / 색 포화: ±20% / 회색: 계산 불가" if diverging else "파랑: 비율 / 회색: 계산 불가"
    parts.append(f'<text x="8" y="{height-8}" font-size="11">{legend}</text></svg>')
    return ''.join(parts)


def html_table(table):
    return table.to_html(index=False, border=0, float_format=lambda n: f"{n:,.4f}", na_rep="—")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    risk = pd.read_csv(builder.PROCESSED_DIR / "risk_features.csv", dtype={key: str for key in KEYS})
    telecom, card = builder.load_inputs()
    # 저장 결과가 현재 입력/코드와 일치하는지 재계산하여 확인한다.
    expected = builder.add_card_features(card).merge(
        builder.summarize_telecom(telecom).merge(builder.common_location_changes(telecom),
                                                on=KEYS, validate="one_to_one"),
        on=KEYS, validate="one_to_one").sort_values(KEYS).reset_index(drop=True)
    builder.check_unique(risk, KEYS, "risk_features")
    pd.testing.assert_frame_equal(risk.sort_values(KEYS).reset_index(drop=True)[expected.columns],
                                  expected, check_dtype=False, rtol=1e-10, atol=1e-8)
    print("현재 입력과 risk_features.csv 일치 확인 완료")
    raw_audit = audit_raw_telecom()
    industries = audit_industries()
    if industries["결제건수"].sum() != risk["카드1_전체_결제건수"].sum():
        raise ValueError("카드1 개인 원본과 최종 특징의 결제건수 합계가 다릅니다.")
    if raw_audit[["중복제거후_중복키수", "키결측행수", "음수셀수", "무한대셀수"]].to_numpy().any():
        raise ValueError("통신 원본 키/숫자 품질 오류. 위험도 설계 전에 수정하세요.")

    numeric = risk.select_dtypes(include="number")
    missing = pd.DataFrame({"컬럼": numeric.columns, "결측수": numeric.isna().sum().values,
                            "결측률": numeric.isna().mean().values,
                            "고유값수": numeric.nunique().values})
    descriptions = numeric.describe(percentiles=[.05, .25, .5, .75, .95]).T.reset_index(names="컬럼")
    coverage_cols = ["통신_전체관측위치수", "통신_연령관측률", "통신_시간관측률",
                     "통신_요일관측률", "통신_전월공통위치비율"]
    coverage = risk[["월", "지역"] + coverage_cols].drop_duplicates().sort_values(["월", "지역"])
    assert not coverage.duplicated(["월", "지역"]).any()
    correlation = risk[CHANGE_COLS].corr()
    correlation_counts = risk[CHANGE_COLS].notna().astype(int).T.dot(risk[CHANGE_COLS].notna().astype(int))
    # 감소 후보는 관찰 목록일 뿐 고립 판정/우선 지원 대상 확정이 아니다.
    joint = risk.loc[risk[CHANGE_COLS[:2]].lt(0).all(axis=1),
                     KEYS + CHANGE_COLS[:2] + ["통신_전월공통위치비율"]].copy()
    group_cols = [f"카드1_{name}_결제건수" for name in ALL_GROUPS]
    shares = risk.groupby(["월", "지역"])[group_cols + ["카드1_전체_결제건수"]].sum()
    for col in group_cols:
        shares[col] = shares[col] / shares["카드1_전체_결제건수"]
    shares = shares[group_cols].rename(columns={c: c.replace("카드1_", "").replace("_결제건수", "") for c in group_cols}).reset_index()
    unclassified = risk["카드1_미분류_결제건수"].sum() / risk["카드1_전체_결제건수"].sum()
    deferred = risk["카드1_해석보류_결제건수"].sum() / risk["카드1_전체_결제건수"].sum()
    partial = int(raw_audit["부분결측행수"].sum())
    summary = {"행수": len(risk), "컬럼수": len(risk.columns), "지역수": risk["지역"].nunique(),
               "월수": risk["월"].nunique(), "연령대수": risk["연령대"].nunique(),
               "동시감소관측수": len(joint), "비교가능관측수": int(risk[CHANGE_COLS[:2]].notna().all(axis=1).sum()),
               "미분류결제건수비중_전체가중": float(unclassified),
               "해석보류결제건수비중_전체가중": float(deferred),
               "카드1카드2_건수변화율상관": float(correlation.loc[CHANGE_COLS[1], CHANGE_COLS[2]]),
               "통신원본부분결측행수": partial}
    tables = {"raw_telecom_quality": raw_audit, "missing_values": missing,
              "feature_statistics": descriptions, "telecom_coverage": coverage,
              "industry_groups": shares, "industry_review": industries,
              "joint_decline_candidates": joint,
              "change_correlations": correlation.reset_index(names="컬럼"),
              "correlation_sample_counts": correlation_counts.reset_index(names="컬럼")}
    for name, table in tables.items():
        save_table(name, table)
    (OUTPUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    panels = []
    for col, title in zip(CHANGE_COLS[:2], ["통신: 전월 공통 위치 연령유동량 변화", "카드1: 전체 결제건수 전월 변화"]):
        panels.append(heatmap(risk.pivot(index=["지역", "연령대"], columns="월", values=col), title))
    panels.append(heatmap(coverage.pivot(index="지역", columns="월", values="통신_시간관측률"),
                          "시간대 자료 관측률 (3종 결합 위치 기준)", diverging=False))
    top = industries.loc[industries["현재그룹"].isin(["미분류", "해석보류"])].head(15)
    report = f'''<!doctype html><html lang="ko"><meta charset="utf-8">
<title>Ieum care 데이터 분석 및 다음 단계</title>
<style>body{{font:15px/1.7 'Malgun Gothic',sans-serif;background:#f5f7fa;color:#17243a;margin:0}}
main{{max-width:1080px;margin:auto;padding:28px}}section{{background:white;padding:24px;margin:20px 0;border-radius:12px}}
h1,h2{{line-height:1.3}}svg{{width:100%;max-width:850px;display:block;margin:24px auto;font-family:'Malgun Gothic',sans-serif;font-size:12px}}
table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{padding:8px;border-bottom:1px solid #dde3eb;text-align:right}}th:first-child,td:first-child{{text-align:left}}
.scroll{{overflow:auto}}.tag{{background:#e5edf8;padding:8px 14px;border-radius:8px;display:inline-block;margin:4px}}
li{{margin:8px 0}}code{{background:#edf1f5;padding:3px}}</style><main>
<h1>Ieum care · 위험도 설계 전 EDA</h1><p>생성 시각: {pd.Timestamp.now().isoformat(timespec='seconds')} (실행 PC 기준)</p>
<p>입력: telecom_features.csv / card_features.csv / risk_features.csv 및 로컬 통신·카드1 원본.</p>
<span class="tag">{len(risk)}행 × {len(risk.columns)}열</span><span class="tag">{summary['지역수']}지역 · {summary['월수']}개월 · {summary['연령대수']}연령</span>
<section><h2>현재 진행 상태</h2><p>통신 3종·카드 2종 정제、업종 분류 v2、월×지역×연령 집계 및 파생변수 생성 완료.
이번 실행에서 원본 품질·특징 일치 검증과 EDA를 수행했다. 위험도 4축, 5단계 분류, 위험유형, Agent 연결은 아직 구현하지 않았다.</p>
<p>유동인구는 고유 방문자 수가 아니며 카드도 거주민만의 소비가 아니다. 개인별 사회적 고립 정답 라벨은 현재 특징 파일에 없다.</p></section>
<section><h2>주요 발견과 해석</h2><ul>
<li>분류표에 없는 미분류 비중은 <b>{unclassified:.1%}</b>, 활동 목적을 특정하기 어려워 남긴 해석보류 비중은 <b>{deferred:.1%}</b>다. 모두 사회활동 부재를 뜻하지 않는다.</li>
<li>생활 소비·의료·교육·교통·금융 등으로 목적을 구분했다. 사회활동 관련 후보는 외식·카페/문화·오락/운동이며, 실제 대인 교류의 측정값이나 검증된 고립 지표는 아니다.</li>
<li>카드1·2 건수 변화율 상관은 <b>{summary['카드1카드2_건수변화율상관']:.6f}</b>다. 겹치는 거래/집계 가능성이 있어 두 자료를 독립 위험축으로 중복 반영하지 않는다.</li>
<li>통신·카드1 건수가 함께 감소한 관측은 <b>{len(joint)}/{summary['비교가능관측수']}</b>개다. 이것은 계절·상권·방문 변화 등을 확인할 후보 목록이며 고립 판정은 아니다.</li>
<li>통신 자료별 관측 위치가 다르다. 관측률은 3종 결합 위치 중 해당 자료가 있는 비율이며, 지역 전체 인구 대비 대표성은 아니다.</li>
<li>시간대·요일 특징은 연령별 측정이 아니라 지역 공통 값이다. 72행 중 해당 특징의 서로 다른 월×지역 관측은 12개뿐이다.</li>
<li>원본 부분 결측은 {partial:,}행이다. 부분 결측이 있으면 기존 합계/평균의 결측 건너뛰기 영향을 추가 점검해야 한다.</li>
</ul></section><section><h2>월별 활동 변화</h2><p>0.1 = 10% 증가. 첫 달은 전월 자료가 없어 회색이다. 그래프 색은 위험 등급이 아니다.
통신 변화는 전월 공통 위치만 비교하며, 카드 변화는 전체 관측 거래 기준이다.</p>{''.join(panels)}</section>
<section><h2>관측 범위</h2><div class="scroll">{html_table(coverage)}</div></section>
<section><h2>카드 업종 그룹 비중</h2><p>각 월·지역의 전체 카드1 결제건수를 분모로 계산. 표의 0.2는 20%.</p><div class="scroll">{html_table(shares)}</div>
<h3>해석보류·미분류 상위 업종</h3><p>ZZ_나머지·컴퓨터/소프트웨어·유통 채널 등은 추가 정의 확인 전 위험 지표에서 제외할 후보로 남겼다.</p><div class="scroll">{html_table(top)}</div></section>
<section><h2>변화율 상관</h2><p>탐색용 Pearson 상관. 집단의 반복 관측과 소수 지역으로 구성되어 독립 표본 검정이나 인과 주장에 사용하지 않는다.</p>
{html_table(correlation.reset_index(names='컬럼'))}<h3>쌍별 유효 관측 수</h3>{html_table(correlation_counts.reset_index(names='컬럼'))}</section>
<section><h2>통신·카드 동시 감소 후보</h2><p>감소율의 부호만 사용한 탐색 목록. 정책 지원 우선순위를 확정한 표가 아니다.</p><div class="scroll">{html_table(joint)}</div></section>
<section><h2>결측과 원본 품질</h2><p>첫 달 전월 변화율은 정상적인 계산 불가이며 0으로 채우지 않았다. 모델 입력 시 결측 처리는 학습 구간에만 맞춘다.</p>
{html_table(missing.loc[missing['결측수'] > 0])}<div class="scroll">{html_table(raw_audit)}</div></section>
<section><h2>다음 할 일: 위험 지표와 검증 설계</h2><ol>
<li><b>분류안 검토:</b> v2 분류표와 업종별 근거를 검토하고, 후보 업종 범위를 바꾸었을 때 결과의 민감도를 확인한다. 소비만으로 실제 관계망을 측정한다고 주장하지 않는다.</li>
<li><b>4축의 정의:</b> 이동활동 변화, 소비활동 변화, 사회활동 관련 소비 구성, 변화의 지속성 등을 후보로 검토. 마지막 축은 다른 축과 중복될 수 있어 독립 축으로 채택할지는 검증해야 한다. 지역 복지 접근성/취약성은 외부 데이터로 보완할 후보다.</li>
<li><b>점수·5단계:</b> 지표 방향, 기준 기간, 가중치, 단계 임계값을 문서화한다. 현재 지역은 2개·기간은 6개월이므로 상대 점수를 실제 고립 확률로 해석하지 않는다. 기준은 과거 구간에서 정하고 이후 월에 적용한다.</li>
<li><b>검증:</b> 원본·집계 일치, 관측 위치/업종 분류/가중치/임계값 변경에 대한 민감도, 월별 안정성, 외부 공개 통계와의 비교 및 전문가 검토를 수행한다. 실제 정답 없이 정확도·F1을 임의로 제시하지 않는다.</li>
<li><b>연계:</b> 판단 근거와 데이터 품질을 위험 결과에 함께 제공하고, 검토된 위험유형을 복지 추천 Agent에 전달한다.</li>
</ol><p>계절성·학사 일정·공휴일·상권 특성과 관측 누락이 대안 설명일 수 있다. 6개월 변화만으로 고립의 원인이나 프로그램 효과를 확정할 수 없다.</p></section>
</main></html>'''
    (OUTPUT / "report.html").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"분석 보고서: {OUTPUT / 'report.html'}")


if __name__ == "__main__":
    main()
