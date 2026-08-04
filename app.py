"""
📈 AI 펀더멘털 & 뉴스 감성 주식 추천기 (국내 · 실시간)
------------------------------------------------------------
데이터: 네이버/KRX 스냅샷(GitHub 캐시, 전종목 시세·시총) + 야후(yfinance, 개별 재무·기술지표)
KRX 로그인 불필요. 코스피·코스닥 모두 지원.
추천 내역(추천일시·매수가·목표가·수익률)을 CSV로 저장/조회.

실행:  pip install -r requirements.txt  →  streamlit run app.py
"""

import pandas as pd
import streamlit as st
import engine as E

st.set_page_config(page_title="AI 종목 추천기", page_icon="📈", layout="wide")
HISTORY_PATH = "recommendation_history.csv"

st.markdown("""
<style>
.card{border:1px solid #e6e6e6;border-radius:16px;padding:18px 24px;margin-bottom:8px;
      background:linear-gradient(180deg,#ffffff 0%,#fafbff 100%);box-shadow:0 2px 10px rgba(0,0,0,.04);}
.rank{font-size:28px;font-weight:800;} .name{font-size:24px;font-weight:800;margin:2px 0;}
.code{color:#888;font-size:13px;}
.bar-wrap{background:#eef0f4;border-radius:6px;height:9px;margin:3px 0 10px;overflow:hidden;}
.bar{height:9px;border-radius:6px;}
.reason{background:#f6f8fc;border-left:4px solid #4c6ef5;border-radius:8px;padding:12px 14px;
        font-size:14.5px;line-height:1.6;color:#333;}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;
      background:#eef2ff;color:#4c6ef5;margin-right:6px;}
.mkt{background:#e6fcf5;color:#0ca678;}
</style>
""", unsafe_allow_html=True)

st.title("📊 AI 펀더멘털 & 뉴스 감성 종목 추천기")
st.markdown("네이버·야후 실시간 데이터로 **코스피·코스닥**을 분석해 오늘의 추천 종목과 "
            "매수가·목표가·추천 사유를 뽑고, **추천 내역과 수익률**을 관리합니다.")

now = E.now_kst()
status, desc = E.market_status(now)
h1, h2 = st.columns([1, 2])
h1.metric("현재 시각 (KST)", now.strftime("%Y-%m-%d %H:%M"))
h2.info(f"**{status}** — {desc}\n\n💡 장 마감(15:30) 전 오후 3시경 검토용으로 설계되었습니다.")
st.divider()

# --------------------------- 사이드바 ---------------------------
sb = st.sidebar
sb.header("⚙️ 설정")
source = sb.radio("데이터 소스", ["실시간 (네이버+야후)", "데모 데이터"],
                  help="실시간: 네이버 스냅샷 + 야후 개별 재무. 데모: 오프라인 예시 데이터.")
markets = sb.multiselect("대상 시장", ["KOSPI", "KOSDAQ"], default=["KOSPI", "KOSDAQ"])
cap_n = sb.slider("분석 유니버스 (시총 상위 N)", 50, 500, 200, 10)
short_k = sb.slider("정밀분석 후보 수 (야후 개별 조회)", 6, 40, 20, 2,
                    help="이 수만큼 야후에서 개별 재무를 조회합니다. 클수록 정확하지만 느립니다(각 1~2초).")

sb.subheader("가중치")
sb.caption("세 요소의 반영 비중 (자동 정규화)")
w_fund = sb.slider("펀더멘털", 0.0, 1.0, 0.5, 0.05)
w_sent = sb.slider("시장 심리 / 뉴스 감성", 0.0, 1.0, 0.2, 0.05)
w_upside = sb.slider("상승여력", 0.0, 1.0, 0.3, 0.05)
_t = w_fund + w_sent + w_upside or 1
sb.info(f"펀더멘털 {w_fund/_t*100:.0f}% · 심리 {w_sent/_t*100:.0f}% · 상승여력 {w_upside/_t*100:.0f}%")

top_n = sb.number_input("추천 종목 수", 1, 10, 3)
auto_save = sb.checkbox("분석 실행 시 내역 자동 저장", value=True)

with sb.expander("📰 뉴스 감성 (선택)"):
    st.caption("네이버 뉴스 검색 API 키를 넣으면 심리 지표가 '가격 모멘텀' 대신 "
               "'실제 뉴스 헤드라인 감성'으로 대체됩니다. (무료: developers.naver.com)")
    nv_id = st.text_input("Client ID", type="password")
    nv_secret = st.text_input("Client Secret", type="password")

sb.divider()
if sb.button("🔄 데이터 캐시 새로고침"):
    st.cache_data.clear(); st.rerun()
sb.warning("⚠️ 투자 참고용 도구이며 투자 자문·매매 권유가 아닙니다.")


# --------------------------- 캐시 로더 ---------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_universe(source, markets_key, cap_n, date_key):
    if source.startswith("실시간"):
        return E.load_universe_live(markets=tuple(markets_key), top_n_by_cap=cap_n)
    return E.DEMO_UNIVERSE.copy()

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_metrics_cached(ticker, market, price, chg, date_key):
    return E.fetch_metrics(ticker, market, fallback_price=price, fallback_chg=chg)

@st.cache_data(ttl=1800, show_spinner=False)
def load_current_prices(tickers, date_key):
    return E.get_current_prices(list(tickers))


def pick_shortlist(uni, k, markets):
    """시장별로 후보를 배분해 코스피·코스닥이 함께 포함되도록 상위 시총 종목 선정."""
    mkts = [m for m in markets if m in set(uni.get("시장", pd.Series()).unique())]
    if len(mkts) <= 1:
        return uni.head(k).copy()
    per = max(1, k // len(mkts))
    parts = [uni[uni["시장"] == m].head(per) for m in mkts]
    short = pd.concat(parts)
    if len(short) < k:
        rest = uni[~uni["티커"].isin(short["티커"])].head(k - len(short))
        short = pd.concat([short, rest])
    return short.reset_index(drop=True)


# --------------------------- 파이프라인 ---------------------------
def run_pipeline():
    date_key = now.strftime("%Y%m%d")
    live = source.startswith("실시간")
    uni = load_universe(source, tuple(markets or ["KOSPI"]), cap_n, date_key)
    asof = uni.attrs.get("asof", date_key) if hasattr(uni, "attrs") else date_key

    if live:
        short = pick_shortlist(uni, short_k, markets or ["KOSPI"])
        prog = st.progress(0.0, text="야후에서 개별 재무·기술 지표 수집 중...")
        rows, n = [], len(short)
        for i, (_, r) in enumerate(short.iterrows()):
            m = fetch_metrics_cached(r["티커"], r["시장"], float(r["현재가"]),
                                     float(r["등락률"]), date_key)
            rows.append({
                "티커": r["티커"], "종목명": r["종목명"], "시장": r["시장"],
                "시가총액": r["시가총액"],
                "현재가": m["현재가"] or r["현재가"], "등락률": m["등락률"],
                "PER": m["PER"], "PBR": m["PBR"], "ROE": m["ROE"], "DIV": m["DIV"],
                "_tech": {"high52": m["high52"], "ma20": m["ma20"], "low60": m["low60"]},
            })
            prog.progress((i + 1) / n, text=f"야후 수집 중... ({i+1}/{n})")
        prog.empty()
        df = pd.DataFrame(rows)
        for c in ["PER", "PBR", "ROE"]:
            med = df[c].median()
            df[c] = df[c].fillna(med if pd.notna(med) else 0.0)
        df["DIV"] = df["DIV"].fillna(0.0)
    else:
        df = uni.sort_values("시가총액", ascending=False).head(short_k).copy()
        df["_tech"] = df["현재가"].apply(lambda c: {"high52": c*1.22, "ma20": c*0.98, "low60": c*0.9})

    df = E.add_valuation_score(df)

    news = None
    if nv_id and nv_secret:
        news = {}
        for _, r in df.iterrows():
            s = E.naver_news_sentiment(r["종목명"], nv_id, nv_secret)
            if s is not None:
                news[r["티커"]] = s
        news = news or None
    df = E.add_momentum_sentiment(df, news_scores=news)

    buys, tgts, stops, ups = [], [], [], []
    for _, r in df.iterrows():
        su = (r["valuation_score"] + r["sentiment_score"]) / 2
        b, t, s, u = E.compute_price_targets(float(r["현재가"]), r["_tech"], su)
        buys.append(b); tgts.append(t); stops.append(s); ups.append(u)
    df["buy"], df["target"], df["stop"], df["upside"] = buys, tgts, stops, ups

    res = E.finalize(df, w_fund, w_sent, w_upside)
    res.attrs["asof"] = asof
    return res


def save_current_to_history(top_df, ran_at):
    rows = pd.DataFrame({
        "추천일시": ran_at, "티커": top_df["티커"].astype(str), "종목명": top_df["종목명"],
        "추천시_현재가": top_df["현재가"].astype(int), "매수가": top_df["buy"].astype(int),
        "목표가": top_df["target"].astype(int), "손절가": top_df["stop"].astype(int),
        "종합점수": top_df["total_score"].round(1),
    })
    E.append_history(rows, HISTORY_PATH)


def bar(label, value, color):
    pct = max(0, min(value, 1)) * 100
    return (f'<div style="font-size:12px;color:#555;">{label} <b>{pct:.0f}</b></div>'
            f'<div class="bar-wrap"><div class="bar" style="width:{pct:.0f}%;background:{color};"></div></div>')


# --------------------------- 탭 ---------------------------
tab_rec, tab_hist = st.tabs(["🎯 오늘의 추천", "📜 추천 내역"])

with tab_rec:
    if st.button("🚀 오늘의 추천 종목 분석 실행하기", type="primary"):
        if source.startswith("실시간"):
            with st.spinner("네이버 전종목 스냅샷 로딩 중..."):
                try:
                    result = run_pipeline()
                    note = f"실시간(네이버+야후) · 기준일 {result.attrs.get('asof','')}"
                except Exception as ex:
                    st.error(f"실시간 연동 실패 → 데모 데이터로 전환합니다.\n\n오류: {ex}")
                    globals()["source"] = "데모 데이터"
                    result = run_pipeline()
                    note = "⚠️ 데모 데이터 (실시간 연동 실패)"
        else:
            result = run_pipeline()
            note = "데모 데이터"

        ran_at = now.strftime("%Y-%m-%d %H:%M")
        st.session_state.update(result=result, ran_at=ran_at, note=note, top_n=int(top_n))
        if auto_save:
            save_current_to_history(result.head(int(top_n)), ran_at)
            st.session_state["saved_msg"] = ran_at

    if "result" in st.session_state:
        result = st.session_state["result"]; ran_at = st.session_state["ran_at"]
        top = result.head(st.session_state.get("top_n", int(top_n))).reset_index(drop=True)
        st.success(f"분석 완료! · {st.session_state['note']} · 추천일시 {ran_at}")
        if st.session_state.pop("saved_msg", None):
            st.toast("📌 추천 내역이 저장되었습니다.")
        st.subheader(f"🏆 오늘의 추천 종목 TOP {len(top)}")

        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        for i, row in top.iterrows():
            src_pill = "뉴스 감성" if row.get("sentiment_src") == "뉴스" else "모멘텀 심리"
            mkt = row.get("시장", "")
            st.markdown(f"""
            <div class="card"><div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;">
              <span class="rank">{medals.get(i,'🔹')} {i+1}위</span>
              <span class="name">{row['종목명']}</span><span class="code">{row['티커']}</span>
              {f'<span class="pill mkt">{mkt}</span>' if mkt else ''}
              <span class="pill">종합 {row['total_score']:.1f}점</span>
              <span class="pill">{src_pill}</span>
            </div></div>""", unsafe_allow_html=True)

            c1, c2 = st.columns([1.1, 1])
            with c1:
                m1, m2 = st.columns(2)
                m1.metric("현재가", f"{int(row['현재가']):,}원")
                m2.metric("추천 매수가", f"{int(row['buy']):,}원")
                m3, m4 = st.columns(2)
                m3.metric("추천 목표가", f"{int(row['target']):,}원", delta=f"{row['upside']*100:.1f}%")
                m4.metric("참고 손절가", f"{int(row['stop']):,}원")
            with c2:
                st.markdown(bar("펀더멘털", row["valuation_score"], "#4c6ef5")
                            + bar("시장 심리 / 감성", row["sentiment_score"], "#22b8cf")
                            + bar("상승여력", row["upside_score"], "#40c057"), unsafe_allow_html=True)
            st.markdown(f'<div class="reason">💡 <b>추천 사유</b><br>{E.build_reason(row)}</div>',
                        unsafe_allow_html=True)
            st.write("")

        if st.button("📌 이 추천 내역 저장"):
            save_current_to_history(top, ran_at); st.toast("📌 저장 완료! '추천 내역' 탭에서 확인하세요.")

        with st.expander("📋 정밀분석 후보 전체 순위표"):
            cols = ["종목명", "티커", "시장", "현재가", "buy", "target", "stop", "upside",
                    "ROE", "PER", "PBR", "DIV", "total_score"]
            cols = [c for c in cols if c in result.columns]
            tbl = result[cols].rename(columns={"buy": "매수가", "target": "목표가",
                     "stop": "손절가", "upside": "상승여력", "total_score": "종합점수"})
            if "상승여력" in tbl: tbl["상승여력"] = (tbl["상승여력"]*100).round(1)
            if "종합점수" in tbl: tbl["종합점수"] = tbl["종합점수"].round(1)
            for c in ["ROE", "PER", "PBR", "DIV"]:
                if c in tbl: tbl[c] = tbl[c].round(2)
            st.dataframe(tbl, use_container_width=True, hide_index=True)

        st.caption("📢 알고리즘 기반 참고 자료이며 매수·매도를 권유하지 않습니다. 매수가·목표가·손절가는 "
                   "기술적·밸류에이션 참고 기준일 뿐 수익을 보장하지 않습니다. 일부 종목은 야후에 재무가 없어 "
                   "중립값으로 처리될 수 있습니다.")
    else:
        st.info("사이드바에서 시장·가중치를 확인한 뒤 **'분석 실행하기'** 버튼을 눌러주세요.\n\n"
                "실시간 첫 실행은 야후 개별 조회로 30초~1분가량 걸릴 수 있습니다.")

with tab_hist:
    hist = E.load_history(HISTORY_PATH)
    if hist.empty:
        st.info("아직 저장된 추천 내역이 없습니다. '오늘의 추천' 탭에서 분석 후 저장하세요.")
    else:
        st.caption("추천 매수가 대비 현재가 기준 수익률입니다. (🔴 상승 · 🔵 하락 — 국내 관례)")
        tickers = tuple(sorted(hist["티커"].astype(str).unique()))
        prices = {}
        with st.spinner("현재가 조회 및 수익률 계산 중..."):
            try:
                if source.startswith("실시간"):
                    prices = load_current_prices(tickers, now.strftime("%Y%m%d"))
                else:
                    demo = E.DEMO_UNIVERSE.set_index("티커")["현재가"].to_dict()
                    prices = {t: demo.get(t) for t in tickers}
            except Exception as ex:
                st.warning(f"현재가 조회 실패 → 추천 당시 가격 기준으로 표시합니다. ({ex})")
        enr = E.enrich_history(hist, prices)

        valid = enr.dropna(subset=["수익률"])
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("총 추천 건수", f"{len(enr)}건")
        k2.metric("평균 수익률", f"{valid['수익률'].mean():.2f}%" if len(valid) else "-")
        win = (valid["수익률"] > 0).mean()*100 if len(valid) else 0
        k3.metric("수익 종목 비율", f"{win:.0f}%")
        k4.metric("목표 달성", f"{(enr['상태']=='🎯 목표달성').sum()}건")

        dates = sorted(enr["추천일시"].unique(), reverse=True)
        pick = st.multiselect("추천일시 필터", dates, default=[])
        view = enr[enr["추천일시"].isin(pick)] if pick else enr

        disp = view[["추천일시", "종목명", "티커", "매수가", "목표가", "손절가",
                     "현재가", "수익률", "목표까지", "상태", "종합점수"]].copy()
        disp = disp.rename(columns={"수익률": "수익률(%)", "목표까지": "목표까지(%)"})

        def _color(v):
            if pd.isna(v): return ""
            if v > 0: return "color:#e03131;font-weight:700"
            if v < 0: return "color:#1971c2;font-weight:700"
            return ""
        styler = (disp.style.map(_color, subset=["수익률(%)"])
                  .format({"매수가": "{:,.0f}", "목표가": "{:,.0f}", "손절가": "{:,.0f}",
                           "현재가": "{:,.0f}", "수익률(%)": "{:+.2f}",
                           "목표까지(%)": "{:+.2f}", "종합점수": "{:.1f}"}))
        st.dataframe(styler, use_container_width=True, hide_index=True)

        d1, d2, d3 = st.columns([1, 1, 2])
        d1.download_button("📥 내역 CSV 다운로드", disp.to_csv(index=False).encode("utf-8-sig"),
                           file_name="추천내역_수익률.csv", mime="text/csv")
        if d2.checkbox("삭제 확인"):
            if d3.button("🗑 추천 내역 전체 삭제"):
                E.clear_history(HISTORY_PATH); st.toast("내역을 삭제했습니다."); st.rerun()

st.caption("데이터 출처: 네이버/KRX 스냅샷(전종목 시세·시총) + 야후(개별 재무·기술지표). KRX 직접 로그인 불필요.")
