"""
📈 AI 펀더멘털·수급 종목 추천기 (국내 · 실시간)
------------------------------------------------------------
데이터: 네이버(전종목 스냅샷 + 재무 + 기관/외국인 수급) + 야후(주가/기술지표)
팩터: 펀더멘털 · 수급(기관·외국인) · 시장심리 · 상승여력  (KRX 로그인 불필요)
기능: 추천 · 추천내역/수익률 · 백테스트 · (스케줄 알림은 notify.py 참고)

실행:  pip install -r requirements.txt  →  streamlit run app.py
"""

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import engine as E

st.set_page_config(page_title="머니캐치", page_icon="📈", layout="wide")
HISTORY_PATH = "recommendation_history.csv"

st.markdown("""
<style>
.card{border:1px solid #e6e6e6;border-radius:16px;padding:18px 24px;margin-bottom:8px;
      background:linear-gradient(180deg,#ffffff 0%,#fafbff 100%);box-shadow:0 2px 10px rgba(0,0,0,.04);}
.hero{border:2px solid #4c6ef5;background:linear-gradient(180deg,#f4f7ff 0%,#ffffff 100%);}
.rank{font-size:28px;font-weight:800;} .name{font-size:24px;font-weight:800;margin:2px 0;}
.code{color:#888;font-size:13px;}
.bar-wrap{background:#eef0f4;border-radius:6px;height:9px;margin:3px 0 10px;overflow:hidden;}
.bar{height:9px;border-radius:6px;}
.reason{background:#f6f8fc;border-left:4px solid #4c6ef5;border-radius:8px;padding:12px 14px;
        font-size:14.5px;line-height:1.6;color:#333;}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;
      background:#eef2ff;color:#4c6ef5;margin-right:6px;}
.mkt{background:#e6fcf5;color:#0ca678;} .hot{background:#fff0f0;color:#e03131;}
.mascot{font-size:13px;color:#5c7cfa;background:#eef2ff;border-radius:10px;padding:6px 12px;display:inline-block;}
button[data-baseweb="tab"] p{font-weight:800 !important;font-size:16px !important;}
</style>
""", unsafe_allow_html=True)

st.title("💰 MTN의 AI 알고리즘이 PICK한 '머니캐치'")
st.markdown('<span class="mascot">🤖 머니캐치: 안녕하세요! 오늘도 코스피·코스닥에서 <b>가치+수급</b>이 좋은 종목을 골라드릴게요.</span>',
            unsafe_allow_html=True)
st.write("")

now = E.now_kst()
status, desc = E.market_status(now)
h1, h2 = st.columns([1, 2])
with h1:
    components.html("""
    <div style="font-family:-apple-system,'Malgun Gothic',sans-serif;padding:2px 0;">
      <div style="font-size:13px;color:#6b7684;">현재 시각 (KST)</div>
      <div id="kstclock" style="font-family:'SF Mono','Roboto Mono',monospace;
           font-size:26px;font-weight:700;color:#0e1726;letter-spacing:-.5px;">--:--:--</div>
    </div>
    <script>
      function updClock(){
        var n = new Date();
        var kst = new Date(n.getTime() + n.getTimezoneOffset()*60000 + 9*3600000);
        var p = function(x){return String(x).padStart(2,'0');};
        document.getElementById('kstclock').textContent =
          kst.getFullYear()+'-'+p(kst.getMonth()+1)+'-'+p(kst.getDate())+' '+
          p(kst.getHours())+':'+p(kst.getMinutes())+':'+p(kst.getSeconds());
      }
      updClock(); setInterval(updClock, 1000);
    </script>
    """, height=70)
h2.info(f"**{status}** — {desc}\n\n💡 장 마감(15:30) 전 오후 3시경 종가무렵에 공략할 수 있도록 설계되었습니다.")
st.divider()

# --------------------------- 관리자 설정(사이드바) ---------------------------
# 기본값(배포 사용자에게 자동 적용). 관리자만 사이드바에서 변경할 수 있습니다.
source = "실시간 (네이버+야후)"
markets = ["KOSPI", "KOSDAQ"]
cap_n, short_k = 200, 14
w_fund, w_supply, w_sent, w_upside = 0.40, 0.20, 0.15, 0.25
supply_days, top_n = 20, 3
oneshot, auto_save = False, True
nv_id = nv_secret = ""

# 관리자 판별: 주소 끝에 ?admin=<키> 를 붙이면 설정이 보입니다. (키는 Secrets의 ADMIN_KEY로 변경 가능)
try:
    ADMIN_KEY = st.secrets["ADMIN_KEY"]
except Exception:
    ADMIN_KEY = "mtnadmin"
is_admin = st.query_params.get("admin") == ADMIN_KEY

if not is_admin:
    # 일반 사용자에게는 설정(사이드바)을 완전히 숨김
    st.markdown('<style>section[data-testid="stSidebar"]{display:none;} '
                'button[kind="header"]{display:none;}</style>', unsafe_allow_html=True)
else:
    sb = st.sidebar
    sb.header("⚙️ 설정 (관리자 전용)")
    source = sb.radio("데이터 소스", ["실시간 (네이버+야후)", "데모 데이터"])
    markets = sb.multiselect("대상 시장", ["KOSPI", "KOSDAQ"], default=["KOSPI", "KOSDAQ"])
    cap_n = sb.slider("분석 유니버스 (시총 상위 N)", 50, 500, 200, 10)
    short_k = sb.slider("정밀분석 후보 수 (개별 조회)", 6, 30, 14, 2,
                        help="이 수만큼 네이버·야후에서 개별 조회합니다. 클수록 정확하지만 느립니다.")
    sb.subheader("가중치 (자동 정규화)")
    w_fund = sb.slider("펀더멘털", 0.0, 1.0, 0.40, 0.05)
    w_supply = sb.slider("수급 (기관·외국인)", 0.0, 1.0, 0.20, 0.05)
    w_sent = sb.slider("시장 심리 / 뉴스", 0.0, 1.0, 0.15, 0.05)
    w_upside = sb.slider("상승여력", 0.0, 1.0, 0.25, 0.05)
    _t = w_fund + w_supply + w_sent + w_upside or 1
    sb.info(f"펀더멘털 {w_fund/_t*100:.0f}% · 수급 {w_supply/_t*100:.0f}% · "
            f"심리 {w_sent/_t*100:.0f}% · 상승여력 {w_upside/_t*100:.0f}%")
    supply_days = sb.slider("수급 집계 일수", 5, 40, 20, 5)
    top_n = sb.number_input("추천 종목 수", 1, 10, 3)
    oneshot = sb.checkbox("🎯 원샷 모드 (1위만 크게)", value=False)
    auto_save = sb.checkbox("분석 실행 시 내역 자동 저장", value=True)
    with sb.expander("📰 뉴스 감성 (선택)"):
        st.caption("네이버 뉴스 검색 API 키를 넣으면 심리 지표가 실제 뉴스 헤드라인 감성으로 대체됩니다.")
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
def fetch_supply_cached(ticker, ndays, date_key):
    return E.fetch_supply(ticker, ndays)

@st.cache_data(ttl=1800, show_spinner=False)
def load_current_prices(tickers, date_key):
    return E.get_current_prices(list(tickers))

@st.cache_data(ttl=1800, show_spinner=False)
def backtest_cached(pick_tuple, months, date_key):
    return E.backtest_picks(list(pick_tuple), months)


def pick_shortlist(uni, k, markets):
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
    use_supply = w_supply > 0

    if live:
        short = pick_shortlist(uni, short_k, markets or ["KOSPI"])
        prog = st.progress(0.0, text="네이버·야후에서 개별 지표 분석 중...")
        rows, n = [], len(short)
        for i, (_, r) in enumerate(short.iterrows()):
            m = fetch_metrics_cached(r["티커"], r["시장"], float(r["현재가"]),
                                     float(r["등락률"]), date_key)
            cur = m["현재가"] or r["현재가"]
            # 수급강도 = 최근 N일 기관+외국인 순매수 ÷ 상장주식수
            supply_intensity = None
            if use_supply:
                sup = fetch_supply_cached(r["티커"], supply_days, date_key)
                if sup["net"] is not None and cur:
                    shares_out = (float(r["시가총액"]) * 1e8) / cur
                    if shares_out > 0:
                        supply_intensity = sup["net"] / shares_out
            rows.append({
                "티커": r["티커"], "종목명": r["종목명"], "시장": r["시장"], "시가총액": r["시가총액"],
                "현재가": cur, "등락률": m["등락률"], "PER": m["PER"], "PBR": m["PBR"],
                "ROE": m["ROE"], "DIV": m["DIV"], "수급강도": supply_intensity,
                "vol_ratio": m["vol_ratio"], "spark": m["spark"],
                "_tech": {"high52": m["high52"], "ma20": m["ma20"], "low60": m["low60"]},
            })
            prog.progress((i + 1) / n, text=f"개별 지표 분석 중... ({i+1}/{n})")
        prog.empty()
        df = pd.DataFrame(rows)
    else:
        df = uni.sort_values("시가총액", ascending=False).head(short_k).copy()
        df["_tech"] = df["현재가"].apply(lambda c: {"high52": c*1.22, "ma20": c*0.98, "low60": c*0.9})
        import numpy as _np
        df["vol_ratio"] = [1.0 + abs(x)/10 for x in df["등락률"]]
        df["spark"] = df["현재가"].apply(lambda c: [round(c*(1+_np.sin(i/3)/25), 1) for i in range(30)])

    # 시장 심리를 "보이는 최근 주가(스파크라인)" 기준 1개월 모멘텀으로 재계산 → 차트와 값 일치
    def _spark_mom(sp):
        if isinstance(sp, list) and len(sp) >= 6:
            base = sp[-min(21, len(sp))]
            if base:
                return (sp[-1] / base - 1) * 100
        return None
    if "spark" in df.columns:
        df["등락률"] = df.apply(lambda r: _spark_mom(r["spark"])
                               if _spark_mom(r["spark"]) is not None else r.get("등락률", 0.0), axis=1)

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
    df = E.add_supply_score(df)

    buys, tgts, stops, ups = [], [], [], []
    for _, r in df.iterrows():
        su = (r["valuation_score"] + r["sentiment_score"]) / 2
        b, t, s, u = E.compute_price_targets(float(r["현재가"]), r["_tech"], su)
        buys.append(b); tgts.append(t); stops.append(s); ups.append(u)
    df["buy"], df["target"], df["stop"], df["upside"] = buys, tgts, stops, ups

    res = E.finalize(df, w_fund, w_sent, w_upside, w_supply)
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
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    if v != v:  # NaN 방어
        v = 0.0
    pct = max(0.0, min(v, 1.0)) * 100
    return (f'<div style="font-size:12px;color:#555;">{label} <b>{pct:.0f}</b></div>'
            f'<div class="bar-wrap"><div class="bar" style="width:{pct:.0f}%;background:{color};"></div></div>')


def render_card(i, row, hero=False):
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    src_pill = "뉴스 감성" if row.get("sentiment_src") == "뉴스" else "모멘텀 심리"
    mkt = row.get("시장", "")
    vr = row.get("vol_ratio")
    hot = f'<span class="pill hot">🔥 거래량 {vr:.1f}배</span>' if (vr and pd.notna(vr) and vr >= 2) else ""
    cls = "card hero" if hero else "card"
    st.markdown(f"""
    <div class="{cls}"><div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;">
      <span class="rank">{medals.get(i,'🔹')} {i+1}위</span>
      <span class="name">{row['종목명']}</span><span class="code">{row['티커']}</span>
      {f'<span class="pill mkt">{mkt}</span>' if mkt else ''}
      <span class="pill">종합 {row['total_score']:.1f}점</span>
      <span class="pill">{src_pill}</span>{hot}
    </div></div>""", unsafe_allow_html=True)

    c1, c2 = st.columns([1.1, 1])
    with c1:
        m1, m2 = st.columns(2)
        m1.metric("현재가", f"{int(row['현재가']):,}원")
        m2.metric("추천 매수가", f"{int(row['buy']):,}원")
        m3, m4 = st.columns(2)
        m3.metric("추천 목표가", f"{int(row['target']):,}원", delta=f"{row['upside']*100:.1f}%")
        m4.metric("참고 손절가", f"{int(row['stop']):,}원")
        spark = row.get("spark")
        if isinstance(spark, list) and len(spark) > 2:
            st.caption("최근 주가 흐름 (약 3개월 · 일봉)")
            _idx = pd.bdate_range(end=pd.Timestamp(now.date()), periods=len(spark))
            st.line_chart(pd.DataFrame({"종가": spark}, index=_idx), height=120)
    with c2:
        st.markdown(bar("펀더멘털", row["valuation_score"], "#4c6ef5")
                    + bar("수급(기관·외국인)", row["supply_score"], "#f76707")
                    + bar("시장 심리 / 뉴스", row["sentiment_score"], "#22b8cf")
                    + bar("상승여력", row["upside_score"], "#40c057"), unsafe_allow_html=True)
    st.markdown(f'<div class="reason">💡 <b>추천 사유</b><br>{E.build_reason(row)}</div>',
                unsafe_allow_html=True)
    st.write("")


# --------------------------- 탭 ---------------------------
tab_rec, tab_hist, tab_bt = st.tabs(["**🎯 오늘의 추천**", "**📜 추천 내역**", "**📈 성과·백테스트**"])

with tab_rec:
    if st.button("🚀 오늘의 추천 종목 분석 실행하기", type="primary"):
        if source.startswith("실시간"):
            with st.spinner("머니캐치 알고리즘 로딩 중..."):
                try:
                    result = run_pipeline()
                    note = f"실시간(네이버+야후) · 기준일 {result.attrs.get('asof','')}"
                except Exception as ex:
                    st.error(f"실시간 연동 실패 → 데모로 전환합니다.\n\n오류: {ex}")
                    globals()["source"] = "데모 데이터"
                    result = run_pipeline(); note = "⚠️ 데모 데이터 (실시간 실패)"
        else:
            result = run_pipeline(); note = "데모 데이터"
        ran_at = now.strftime("%Y-%m-%d %H:%M")
        st.session_state.update(result=result, ran_at=ran_at, note=note, top_n=int(top_n))
        if auto_save:
            save_current_to_history(result.head(int(top_n)), ran_at)
            st.session_state["saved_msg"] = ran_at

    if "result" in st.session_state:
        result = st.session_state["result"]; ran_at = st.session_state["ran_at"]
        top = result.head(st.session_state.get("top_n", int(top_n))).reset_index(drop=True)
        st.success(f"분석 완료! · MTN PICK '머니캐치' · 추천일시 {ran_at}")
        if st.session_state.pop("saved_msg", None):
            st.toast("📌 추천 내역이 저장되었습니다.")

        if oneshot:
            st.subheader("🎯 원샷 — 오늘의 최우선 1종목")
            render_card(0, top.iloc[0], hero=True)
        else:
            st.subheader(f"🏆 오늘의 추천 종목 TOP {len(top)}")
            for i, row in top.iterrows():
                render_card(i, row)

        if st.button("📌 이 추천 내역 저장"):
            save_current_to_history(top, ran_at); st.toast("📌 저장 완료!")

        with st.expander("📋 정밀분석 후보 전체 순위표"):
            cols = ["종목명", "티커", "시장", "현재가", "buy", "target", "stop", "upside",
                    "ROE", "PER", "PBR", "DIV", "vol_ratio", "total_score"]
            cols = [c for c in cols if c in result.columns]
            tbl = result[cols].rename(columns={"buy": "매수가", "target": "목표가", "stop": "손절가",
                     "upside": "상승여력", "vol_ratio": "거래량배수", "total_score": "종합점수"})
            if "상승여력" in tbl: tbl["상승여력"] = (tbl["상승여력"]*100).round(1)
            if "종합점수" in tbl: tbl["종합점수"] = tbl["종합점수"].round(1)
            if "거래량배수" in tbl: tbl["거래량배수"] = tbl["거래량배수"].round(2)
            for c in ["ROE", "PER", "PBR", "DIV"]:
                if c in tbl: tbl[c] = tbl[c].round(2)
            st.dataframe(tbl, use_container_width=True, hide_index=True)
        st.caption("📢 알고리즘 기반 참고 자료이며 매수·매도를 권유하지 않습니다. 수급강도는 최근 N일 "
                   "기관·외국인 순매수 ÷ 상장주식수(%)이며, 일부 종목은 재무·수급이 미확보될 수 있습니다.")
    else:
        st.info("**'오늘의 추천 종목 분석 실행하기'** 버튼을 눌러주세요. "
                "실시간 첫 실행은 개별 조회로 다소 걸릴 수 있습니다.")

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
                st.warning(f"현재가 조회 실패 → 추천 당시 가격 기준 표시. ({ex})")
        enr = E.enrich_history(hist, prices)
        valid = enr.dropna(subset=["수익률"])

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("총 추천 건수", f"{len(enr)}건")
        k2.metric("평균 수익률", f"{valid['수익률'].mean():.2f}%" if len(valid) else "-")
        win = (valid["수익률"] > 0).mean()*100 if len(valid) else 0
        k3.metric("수익 종목 비율", f"{win:.0f}%")
        k4.metric("목표 달성", f"{(enr['상태']=='🎯 목표달성').sum()}건")

        if len(valid):
            st.caption("📊 종목별 수익률 (%)")
            chart_df = valid.assign(라벨=valid["종목명"] + " (" + valid["추천일시"].str.slice(5, 10) + ")")
            st.bar_chart(chart_df.set_index("라벨")["수익률"], height=240, color="#4c6ef5")

        dates = sorted(enr["추천일시"].unique(), reverse=True)
        pick = st.multiselect("추천일시 필터", dates, default=[])
        view = enr[enr["추천일시"].isin(pick)] if pick else enr
        disp = view[["추천일시", "종목명", "티커", "매수가", "목표가", "손절가",
                     "현재가", "수익률", "목표까지", "상태", "종합점수"]].copy()
        disp = disp.rename(columns={"수익률": "수익률(%)", "목표까지": "목표까지(%)"})

        def _color(v):
            if pd.isna(v): return ""
            return "color:#e03131;font-weight:700" if v > 0 else ("color:#1971c2;font-weight:700" if v < 0 else "")
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

with tab_bt:
    st.subheader("📈 선정 종목 과거 수익률 (사후 참고)")
    st.caption("현재 추천 종목을 '過去 N개월 전에 매수했다면'의 수익률입니다. "
               "워크포워드 백테스트가 아니라 선정 종목의 과거 성과 확인용입니다.")
    if "result" not in st.session_state:
        st.info("먼저 '오늘의 추천' 탭에서 분석을 실행하세요.")
    else:
        res = st.session_state["result"]
        c1, c2 = st.columns([1, 3])
        months = c1.selectbox("기간", [3, 6, 12], index=0)
        n_bt = c2.slider("검증 종목 수 (상위)", 3, min(15, len(res)), min(8, len(res)))
        if st.button("📉 과거 수익률 확인"):
            picks = tuple((r["티커"], r.get("시장", "KOSPI"), r["종목명"])
                          for _, r in res.head(n_bt).iterrows())
            with st.spinner("야후에서 과거 시세 조회 중..."):
                if source.startswith("실시간"):
                    bt = backtest_cached(picks, months, now.strftime("%Y%m%d"))
                else:  # 데모: spark로 근사
                    import numpy as _np
                    bt = pd.DataFrame([{"종목명": r["종목명"], "티커": r["티커"],
                        f"{months}개월 수익률(%)": round((r["spark"][-1]/r["spark"][0]-1)*100, 1)
                        if isinstance(r.get("spark"), list) and len(r["spark"]) > 2 else _np.nan}
                        for _, r in res.head(n_bt).iterrows()])
            col = f"{months}개월 수익률(%)"
            valid = bt.dropna(subset=[col])
            if len(valid):
                m1, m2, m3 = st.columns(3)
                m1.metric("평균 수익률", f"{valid[col].mean():+.1f}%")
                m2.metric("플러스 비율", f"{(valid[col]>0).mean()*100:.0f}%")
                m3.metric("최고 / 최저", f"{valid[col].max():+.0f}% / {valid[col].min():+.0f}%")
                st.bar_chart(valid.set_index("종목명")[col], height=240,
                             color="#f76707")
            st.dataframe(bt, use_container_width=True, hide_index=True)
        st.caption("과거 수익률은 미래 수익을 보장하지 않습니다.")

st.divider()
st.caption("유의사항: 투자 참고 용도이며, 투자자문 및 매매 권유가 아닙니다. 투자의 최종 책임은 본인에게 있습니다.")
