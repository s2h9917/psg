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
.sig{background:#fff4e6;color:#e8590c;} .rsipill{background:#eef2ff;color:#4c6ef5;}
@keyframes mcShiver{0%,100%{transform:translateX(-1.6px) rotate(-1.5deg);}50%{transform:translateX(1.6px) rotate(1.5deg);}}
@keyframes mcPant{0%,100%{transform:translateY(0);}50%{transform:translateY(-3px);}}
.mc-cold{animation:mcShiver .16s infinite;transform-origin:center;}
.mc-hot{animation:mcPant .55s ease-in-out infinite;transform-origin:center;}
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
h2.info(f"**{status}** — {desc}\n\n"
        f"💡 장 시작(09:00) 전 오전 08시30분경 시초가에 공략할 수 있도록 설계되었습니다.\n\n"
        f"💡 장 마감(15:30) 전 오후 3시경 종가무렵에 공략할 수 있도록 설계되었습니다.")
st.divider()

# --------------------------- 관리자 설정(사이드바) ---------------------------
# 기본값(배포 사용자에게 자동 적용). 관리자만 사이드바에서 변경할 수 있습니다.
source = "실시간 (네이버+야후)"
markets = ["KOSPI", "KOSDAQ"]
cap_n, short_k = 200, 14
w_fund, w_supply, w_sent, w_upside = 0.40, 0.20, 0.15, 0.25
supply_days, per_market = 20, 3
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
    per_market = sb.number_input("시장별 추천 수 (코스피/코스닥 각각)", 1, 5, 3)
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


@st.cache_data(ttl=300, show_spinner=False)
def load_dashboard(bucket_key):
    return E.fetch_dashboard()


def demo_dashboard():
    def q(p, c): return {"price": p, "chg": c, "pct": c / (p - c) * 100 if (p - c) else 0, "time": "09:43"}
    return {"domestic": [("코스피", q(6291.01, -14.51)), ("코스닥", q(801.25, -4.83))],
            "fx": [("원/달러", q(1382.50, 3.20))],
            "global": [("나스닥", q(26348.35, -120.0)), ("S&P500", q(6520.10, -8.4)), ("다우", q(53885.10, -95.0))],
            "commodity": [("WTI유가", q(71.20, 0.85)), ("금", q(2418.6, 12.4))]}


def _big_idx_html(label, d):
    if not d:
        return f"<div style='padding:6px 0'><span style='font-size:14px;color:#666'>{label}</span><br>" \
               f"<span style='font-size:26px;color:#999'>—</span></div>"
    up = d["chg"] >= 0
    color = "#e5342a" if up else "#1668dc"   # 상승=빨강, 하락=파랑 (국내 관례)
    arrow = "▲" if up else "▼"
    return (f"<div style='padding:6px 0'>"
            f"<span style='font-size:14px;color:#666'>{label}</span><br>"
            f"<span style='font-size:32px;font-weight:800;font-family:monospace;letter-spacing:-1px'>{d['price']:,.2f}</span> "
            f"<span style='font-size:17px;color:{color};font-weight:700'>{arrow}{abs(d['chg']):,.2f} ({d['pct']:+.2f}%)</span>"
            f"</div>")


def demo_breadth():
    d = E.DEMO_UNIVERSE
    out = {"asof": now.strftime("%Y-%m-%d"), "markets": {}}
    for m in ["KOSPI", "KOSDAQ"]:
        sub = d[d["시장"] == m]["등락률"]
        adv, dec = int((sub > 0).sum()), int((sub < 0).sum())
        ratio = adv / (adv + dec) * 100 if (adv + dec) else 50.0
        out["markets"][m] = {"adv": adv, "dec": dec, "total": len(sub),
                             "ratio": round(ratio, 1), "avg": round(float(sub.mean()), 2)}
    allc = d["등락률"]
    adv, dec = int((allc > 0).sum()), int((allc < 0).sum())
    ratio = adv / (adv + dec) * 100 if (adv + dec) else 50.0
    out["total"] = {"adv": adv, "dec": dec, "ratio": round(ratio, 1), "avg": round(float(allc.mean()), 2)}
    out["mood"] = ("🔴 상승 우위 (강세)" if ratio >= 60 else
                   "⚪ 혼조세" if ratio >= 45 else "🔵 하락 우위 (약세)")
    return out


@st.cache_data(ttl=900, show_spinner=False)
def load_sentiment(bucket_key):
    return E.fear_greed_index()


def demo_sentiment():
    return {"score": 63, "label": "탐욕", "emoji": "😃",
            "components": [("시장 모멘텀", 78), ("20일 추세", 61), ("변동성(안정)", 72),
                           ("당일 강도", 55), ("안전자산 선호", 49)]}


def _gauge_svg(score):
    x = 20 + (score / 100.0) * 560
    return f"""<svg viewBox="0 0 600 92" width="100%" style="max-width:600px">
      <defs><linearGradient id="fg" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#1668dc"/><stop offset="0.5" stop-color="#40c057"/>
        <stop offset="1" stop-color="#e5342a"/></linearGradient></defs>
      <rect x="20" y="40" width="560" height="16" rx="8" fill="url(#fg)"/>
      <polygon points="{x-9:.0f},32 {x+9:.0f},32 {x:.0f},46" fill="#0e1726"/>
      <text x="{x:.0f}" y="24" font-size="17" font-weight="800" fill="#0e1726" text-anchor="middle">{score}</text>
      <text x="20" y="78" font-size="12" fill="#1668dc">🥶 공포 0</text>
      <text x="300" y="78" font-size="12" fill="#888" text-anchor="middle">중립 50</text>
      <text x="580" y="78" font-size="12" fill="#e5342a" text-anchor="end">탐욕 100 🥵</text>
    </svg>"""


def _zolaman_svg(score):
    hot = score >= 60
    cold = score < 40
    color = "#e5342a" if hot else ("#1668dc" if cold else "#2f9e44")
    if hot:
        mouth = '<ellipse cx="80" cy="52" rx="7" ry="5" fill="#0e1726"/>'
    elif cold:
        mouth = '<path d="M72 52 q4 -4 8 0 q4 4 8 0" stroke="#0e1726" stroke-width="2" fill="none"/>'
    else:
        mouth = '<path d="M72 50 q8 8 16 0" stroke="#0e1726" stroke-width="2.5" fill="none"/>'
    extras = ""
    if hot:
        extras = ('<path d="M104 34 q6 8 0 12 q-6 -4 0 -12" fill="#4dabf7"/>'
                  '<path d="M112 44 q5 7 0 10 q-5 -3 0 -10" fill="#4dabf7"/>'
                  '<path d="M120 20 q4 6 -2 10" stroke="#e5342a" stroke-width="2" fill="none"/>'
                  '<path d="M128 24 q4 6 -2 10" stroke="#e5342a" stroke-width="2" fill="none"/>')
    if cold:
        extras = ('<path d="M36 40 l6 -5 l-6 -5" stroke="#1668dc" stroke-width="2" fill="none"/>'
                  '<path d="M124 40 l-6 -5 l6 -5" stroke="#1668dc" stroke-width="2" fill="none"/>')
    body = ('<rect x="66" y="66" width="28" height="42" rx="8" fill="#4c6ef5"/>' if cold else
            f'<line x1="80" y1="66" x2="80" y2="112" stroke="{color}" stroke-width="4"/>')
    if cold:
        arms = ('<path d="M80 80 q-14 4 -14 18 M80 80 q14 4 14 18" stroke="'
                + color + '" stroke-width="4" fill="none"/>')
    else:
        arms = (f'<line x1="80" y1="78" x2="58" y2="96" stroke="{color}" stroke-width="4"/>'
                f'<line x1="80" y1="78" x2="102" y2="96" stroke="{color}" stroke-width="4"/>')
    return f"""<svg viewBox="0 0 160 150" width="140" height="132">
      {extras}
      <circle cx="80" cy="44" r="22" fill="none" stroke="{color}" stroke-width="4"/>
      <circle cx="72" cy="40" r="2.5" fill="#0e1726"/><circle cx="88" cy="40" r="2.5" fill="#0e1726"/>
      {mouth}
      {body}{arms}
      <line x1="80" y1="112" x2="66" y2="138" stroke="{color}" stroke-width="4"/>
      <line x1="80" y1="112" x2="94" y2="138" stroke="{color}" stroke-width="4"/>
    </svg>"""


def render_sentiment():
    cur = E.now_kst()
    try:
        fg = (load_sentiment(cur.strftime("%Y%m%d%H"))
              if source.startswith("실시간") else demo_sentiment())
    except Exception:
        fg = None
    if not fg:
        return
    st.markdown("#### 🌡️ 오늘의 투자 심리 온도계")
    zc = "#e5342a" if fg["score"] >= 60 else ("#1668dc" if fg["score"] < 40 else "#2f9e44")
    anim = "mc-hot" if fg["score"] >= 60 else ("mc-cold" if fg["score"] < 40 else "")
    c1, c2 = st.columns([1, 3])
    with c1:
        st.markdown(f"<div style='text-align:center'>"
                    f"<div class='{anim}' style='display:inline-block'>{_zolaman_svg(fg['score'])}</div>"
                    f"<div style='font-size:34px'>{fg['emoji']}</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div style='font-size:15px;color:#666'>현재 시장 심리</div>"
                    f"<div style='font-size:40px;font-weight:800;color:{zc};line-height:1.1'>"
                    f"{fg['score']} <span style='font-size:22px'>· {fg['label']}</span></div>",
                    unsafe_allow_html=True)
        st.markdown(_gauge_svg(fg["score"]), unsafe_allow_html=True)
    with st.expander("🔎 심리 구성 지표"):
        for n, v in fg["components"]:
            st.markdown(f"<div style='font-size:12px;color:#555'>{n} <b>{v}</b></div>"
                        f"<div style='background:#eef0f4;border-radius:5px;height:7px'>"
                        f"<div style='width:{max(v,3)}%;height:7px;border-radius:5px;background:{zc}'></div></div>",
                        unsafe_allow_html=True)
        st.caption("0(극단적 공포) ~ 100(극단적 탐욕) · 코스피 모멘텀·추세·변동성·강도·환율(안전자산)로 산출한 참고 지표입니다.")
    st.divider()


@st.fragment(run_every=60)
def render_breadth():
    cur = E.now_kst()
    st.markdown("#### 🧭 실시간 시장 (지연시세)")
    try:
        dash = (load_dashboard(cur.strftime("%Y%m%d%H%M"))   # 분 단위 키 → 자동 갱신 시 신선한 데이터
                if source.startswith("실시간") else demo_dashboard())
    except Exception:
        dash = None
    if not dash:
        st.info("실시간 시세를 불러오지 못했습니다. 잠시 후 자동 갱신됩니다.")
        st.divider(); return

    dom = dict(dash.get("domestic", []))
    itime = next((q["time"] for _, q in dash.get("domestic", []) if q), "")

    big = st.columns(2)
    big[0].markdown(_big_idx_html("코스피", dom.get("코스피")), unsafe_allow_html=True)
    big[1].markdown(_big_idx_html("코스닥", dom.get("코스닥")), unsafe_allow_html=True)
    st.caption(f"⏱️ 지수 기준 {itime} · 지연시세 · 조회 {cur.strftime('%H:%M:%S')} (KST) · 60초마다 자동 갱신")

    small = dash.get("fx", []) + dash.get("global", []) + dash.get("commodity", [])
    cols = st.columns(len(small))
    for c, (label, q) in zip(cols, small):
        if q:
            c.metric(label, f"{q['price']:,.2f}", f"{q['pct']:+.2f}%", delta_color="inverse")
        else:
            c.metric(label, "—")
    st.divider()

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


def top_by_market(res, per_market, markets):
    """시장별 상위 per_market 종목 선정 (코스피 3 + 코스닥 3)."""
    mkts = [m for m in markets if "시장" in res.columns and m in set(res["시장"].unique())]
    if not mkts:
        return res.head(per_market).reset_index(drop=True)
    parts = [res[res["시장"] == m].head(per_market) for m in mkts]
    return pd.concat(parts).reset_index(drop=True)


# --------------------------- 파이프라인 ---------------------------
def run_pipeline(session="close"):
    # 세션별 가중치: 시초가=수급·모멘텀 중심 / 종가=관리자 설정(밸런스형)
    if session == "open":
        wf, wsup, wse, wup = 0.15, 0.40, 0.35, 0.10
    else:
        wf, wsup, wse, wup = w_fund, w_supply, w_sent, w_upside
    date_key = now.strftime("%Y%m%d")
    live = source.startswith("실시간")
    uni = load_universe(source, tuple(markets or ["KOSPI"]), cap_n, date_key)
    asof = uni.attrs.get("asof", date_key) if hasattr(uni, "attrs") else date_key
    use_supply = wsup > 0

    if live:
        short = pick_shortlist(uni, short_k, markets or ["KOSPI"])
        prog = st.progress(0.0, text="머니캐치 알고리즘이 개별 지표 분석 중...")
        rows, n = [], len(short)
        for i, (_, r) in enumerate(short.iterrows()):
            m = fetch_metrics_cached(r["티커"], r["시장"], float(r["현재가"]),
                                     float(r["등락률"]), date_key)
            cur = m.get("현재가") or r["현재가"]
            # 수급강도 = 최근 N일 기관+외국인 순매수 ÷ 상장주식수
            supply_intensity = None
            if use_supply:
                sup = fetch_supply_cached(r["티커"], supply_days, date_key)
                if sup.get("net") is not None and cur:
                    shares_out = (float(r["시가총액"]) * 1e8) / cur
                    if shares_out > 0:
                        supply_intensity = sup["net"] / shares_out
            _tech = {"high52": m.get("high52") or cur * 1.2,
                     "ma20": m.get("ma20") or cur * 0.98,
                     "low60": m.get("low60") or cur * 0.9}
            rows.append({
                "티커": r["티커"], "종목명": r["종목명"], "시장": r["시장"], "시가총액": r["시가총액"],
                "현재가": cur, "등락률": m.get("등락률", 0.0),
                "PER": m.get("PER"), "PBR": m.get("PBR"),
                "ROE": m.get("ROE"), "DIV": m.get("DIV"), "수급강도": supply_intensity,
                "vol_ratio": m.get("vol_ratio"), "spark": m.get("spark"),
                "rsi": m.get("rsi"), "ma20": _tech["ma20"],
                "ma60": m.get("ma60"), "high52": _tech["high52"],
                "_tech": _tech,
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
        df["ma20"] = df["현재가"] * 0.98
        df["ma60"] = df["현재가"] * 0.95
        df["high52"] = df["현재가"] * 1.22
        df["rsi"] = df["등락률"].apply(lambda x: round(min(88, max(12, 50 + x * 3)), 1))

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

    res = E.finalize(df, wf, wse, wup, wsup)
    res.attrs["asof"] = asof
    return res


def save_current_to_history(top_df, ran_at, gubun=""):
    rows = pd.DataFrame({
        "추천일시": ran_at, "구분": gubun, "티커": top_df["티커"].astype(str), "종목명": top_df["종목명"],
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

    _tags = E.signal_tags(row)
    _rsi = row.get("rsi")
    _chips = ""
    if _rsi is not None and pd.notna(_rsi):
        _lvl = "과매수" if _rsi >= 70 else ("과매도" if _rsi <= 30 else "중립")
        _chips += f'<span class="pill rsipill">과열도 RSI {_rsi:.0f} · {_lvl}</span>'
    for _t in _tags:
        if "과매" not in _t:
            _chips += f'<span class="pill sig">{_t}</span>'
    if _chips:
        st.markdown(f'<div style="margin:-2px 0 8px;">{_chips}</div>', unsafe_allow_html=True)

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


# --------------------------- 심리 온도계 + 시장 상태(공통, 탭 위) ---------------------------
render_sentiment()
render_breadth()

# --------------------------- 탭 ---------------------------
tab_rec, tab_hist, tab_bt, tab_fv, tab_cal = st.tabs(
    ["**🎯 오늘의 추천**", "**📜 추천 내역**", "**📈 성과·백테스트**", "**💎 적정주가**", "**📅 증시 캘린더**"])

with tab_rec:
    _hr = int(now.strftime("%H"))
    session_label = st.radio(
        "추천 세션",
        ["🌅 시초가 추천 (장 시작 전 08:30~08:50)", "🌆 종가 추천 (장 마감 전 15:00~15:20)"],
        index=(0 if _hr < 12 else 1), horizontal=True)
    session = "open" if "시초가" in session_label else "close"
    session_name = "시초가" if session == "open" else "종가"

    if st.button("🚀 오늘의 추천 종목 분석 실행하기", type="primary"):
        if source.startswith("실시간"):
            with st.spinner("머니캐치 알고리즘 로딩 중..."):
                try:
                    result = run_pipeline(session)
                except Exception as ex:
                    st.error(f"실시간 연동 실패 → 데모로 전환합니다.\n\n오류: {ex}")
                    globals()["source"] = "데모 데이터"
                    result = run_pipeline(session)
        else:
            result = run_pipeline(session)
        ran_at = now.strftime("%Y-%m-%d %H:%M")
        picks = top_by_market(result, per_market, markets or ["KOSPI", "KOSDAQ"])
        st.session_state.update(result=result, picks=picks, ran_at=ran_at,
                                session_name=session_name, per_market=int(per_market))
        if auto_save:
            save_current_to_history(picks, ran_at, session_name)
            st.session_state["saved_msg"] = ran_at

    if "result" in st.session_state:
        result = st.session_state["result"]; ran_at = st.session_state["ran_at"]
        picks = st.session_state.get("picks")
        sname = st.session_state.get("session_name", "종가")
        st.success(f"분석 완료! · MTN PICK '머니캐치' ({sname}) · 추천일시 {ran_at}")
        if st.session_state.pop("saved_msg", None):
            st.toast("📌 추천 내역이 저장되었습니다.")

        if oneshot:
            st.subheader(f"🎯 원샷 — {sname} 최우선 1종목")
            render_card(0, result.head(1).reset_index(drop=True).iloc[0], hero=True)
        else:
            icon = "🌅" if sname == "시초가" else "🌆"
            st.subheader(f"{icon} {sname} 추천 종목 (코스피·코스닥 각 {st.session_state.get('per_market', per_market)}종목)")
            for mcode, mlabel in [("KOSPI", "🔵 코스피"), ("KOSDAQ", "🟢 코스닥")]:
                part = (picks[picks["시장"] == mcode].reset_index(drop=True)
                        if (picks is not None and "시장" in picks.columns) else None)
                if part is not None and len(part):
                    st.markdown(f"### {mlabel} TOP {len(part)}")
                    for i, row in part.iterrows():
                        render_card(i, row)

        if st.button("📌 이 추천 내역 저장"):
            save_current_to_history(picks, ran_at, sname); st.toast("📌 저장 완료!")

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
        base_cols = ["추천일시", "종목명", "티커", "매수가", "목표가", "손절가",
                     "현재가", "수익률", "목표까지", "상태", "종합점수"]
        if "구분" in view.columns:
            base_cols.insert(1, "구분")
        disp = view[base_cols].copy()
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
            with st.spinner("과거 시세 조회 중..."):
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

with tab_fv:
    st.subheader("💎 적정주가 분석 (다중 모델)")
    st.caption("종목명 또는 6자리 코드를 입력하면 여러 방식의 적정주가와 현재가 대비 저평가/고평가를 계산합니다.")
    q = st.text_input("종목명 또는 코드", placeholder="예: 삼성전자 또는 005930")
    # 기본 가정값(사용자 공통). 관리자만 조정 가능.
    rf, mrp, g, tp_in = 0.03, 0.055, 0.02, 0.0
    if is_admin:
        with st.expander("⚙️ 계산 가정 (관리자 전용)"):
            fc1, fc2, fc3 = st.columns(3)
            rf = fc1.number_input("무위험수익률 rf", 0.0, 0.10, 0.03, 0.005, format="%.3f")
            mrp = fc2.number_input("시장위험프리미엄 mrp", 0.0, 0.15, 0.055, 0.005, format="%.3f")
            g = fc3.number_input("장기 성장률 g", 0.0, 0.08, 0.02, 0.005, format="%.3f")
            tp_in = st.number_input("목표 PER (0=자동)", 0.0, 100.0, 0.0, 0.5)

    if st.button("💎 적정주가 분석하기", type="primary"):
        if not q.strip():
            st.warning("종목명 또는 코드를 입력하세요.")
        else:
            with st.spinner("적정주가 계산 중..."):
                try:
                    if source.startswith("실시간"):
                        info = E.resolve_ticker(q)
                        if info is None:
                            st.error("해당 종목을 찾을 수 없습니다. 정확한 종목명 또는 6자리 코드를 입력해주세요.")
                            st.stop()
                        fund = E.fetch_fundamentals_naver(info["code"])
                        per, pbr, roe, div = fund["PER"], fund["PBR"], fund["ROE"], fund.get("DIV")
                    else:  # 데모
                        d = E.DEMO_UNIVERSE
                        row = d[d["종목명"].str.contains(q.strip(), na=False) | (d["티커"] == q.strip())]
                        if row.empty:
                            st.error("데모 데이터에서 종목을 찾을 수 없습니다. (예: 삼성전자)")
                            st.stop()
                        r0 = row.iloc[0]
                        info = {"code": r0["티커"], "name": r0["종목명"], "market": r0["시장"], "current": float(r0["현재가"])}
                        per, pbr, roe, div = float(r0["PER"]), float(r0["PBR"]), float(r0["ROE"]), float(r0["DIV"])
                except Exception as ex:
                    st.error(f"조회 실패: {ex}"); st.stop()

            cur = info["current"]
            import numpy as _np
            div = 0.0 if (div is None or (isinstance(div, float) and _np.isnan(div))) else div
            target_per = None if tp_in == 0 else tp_in
            models, notes, meta = E.fair_value(cur, per, pbr, roe, div, rf, mrp, g, target_per)

            if not models:
                st.warning("이 종목은 공개 재무(PER/PBR)가 부족해 적정주가를 계산할 수 없습니다.")
            else:
                st.markdown(f"### {info['name']} ({info['code']}) · KRW")
                integ = models.get("통합")
                s1, s2, s3 = st.columns(3)
                s1.metric("현재가", f"{cur:,.0f}원")
                if integ:
                    diff = (cur - integ) / integ * 100
                    verdict = "🔴 저평가" if diff < -5 else ("🔵 고평가" if diff > 5 else "⚪ 적정")
                    s2.metric("통합 적정주가", f"{integ:,.0f}원", f"{-diff:+.1f}% (현재가)")
                    s3.metric("평가", verdict)
                st.divider()
                order = ["통합", "수익기반", "자산/이익력", "배당기반"]
                labels = {"통합": "A. 통합(가중평균)", "수익기반": "B. 수익기반",
                          "자산/이익력": "C. 자산/이익력", "배당기반": "D. 배당기반"}
                for k in order:
                    if k in models:
                        v = models[k]; diff = (cur - v) / v * 100
                        cc1, cc2 = st.columns([1, 2])
                        tag = "🔴 저평가" if diff < -5 else ("🔵 고평가" if diff > 5 else "⚪ 적정")
                        cc1.metric(labels[k], f"{v:,.0f}원", f"{-diff:+.1f}%")
                        cc2.markdown(f"<div style='padding-top:8px;color:#555;font-size:13.5px'>"
                                     f"{notes.get(k,'')}<br><span style='color:#888'>현재가 대비 {tag}</span></div>",
                                     unsafe_allow_html=True)
                with st.expander("🔍 계산 상세"):
                    st.markdown(
                        f"- 현재가 **{cur:,.0f}원** · PER **{per}** · PBR **{pbr}** · "
                        f"ROE **{meta['roe']}%** · 배당수익률 **{div}%**\n"
                        f"- 요구수익률 r = rf {rf*100:.1f}% + mrp {mrp*100:.1f}% = **{meta['r']*100:.1f}%** (베타 1 가정)\n"
                        f"- 목표 PER **{meta['target_per']}** · EPS **{meta['eps']:,.0f}** · "
                        f"BPS **{(meta['bps'] or 0):,.0f}** · DPS **{meta['dps']:,.0f}** · 성장률 g **{g*100:.1f}%**\n"
                        f"- 데이터: 네이버(PER/PBR/배당) + 스냅샷(시세) · **투자자문 아님**")
                st.caption("※ 현금흐름(EV/EBITDA) 모델은 재무제표(DART) 데이터가 필요해 이번 버전에서는 제외했습니다. "
                           "적정주가는 가정에 민감한 참고값이며 매매 권유가 아닙니다.")

with tab_cal:
    st.subheader("📅 증시 캘린더")
    st.caption("금리 결정·CPI·고용·GDP 등 증시에 영향을 주는 주요 경제 일정입니다. (실시간 제공: TradingView)")
    fc1, fc2 = st.columns(2)
    imp = fc1.radio("중요도", ["중간+높음", "높음만", "전체"], horizontal=True, index=0)
    scope = fc2.radio("국가", ["한국·미국 중심", "주요국 전체"], horizontal=True, index=0)
    imp_map = {"중간+높음": "0,1", "높음만": "1", "전체": "-1,0,1"}
    country = "kr,us" if scope == "한국·미국 중심" else "kr,us,eu,jp,cn,gb,hk"
    widget = """
    <div class="tradingview-widget-container" style="height:640px;">
      <div class="tradingview-widget-container__widget"></div>
      <script type="text/javascript"
        src="https://s3.tradingview.com/external-embedding/embed-widget-events.js" async>
      {
        "colorTheme": "light",
        "isTransparent": true,
        "locale": "kr",
        "countryFilter": "%COUNTRY%",
        "importanceFilter": "%IMP%",
        "width": "100%",
        "height": 620
      }
      </script>
    </div>
    """.replace("%COUNTRY%", country).replace("%IMP%", imp_map[imp])
    components.html(widget, height=660, scrolling=True)
    st.caption("경제지표 일정은 발표 시각·수치가 지연되거나 변경될 수 있습니다. 투자 참고용입니다.")

st.divider()
st.caption("유의사항: 투자 참고 용도이며, 투자자문 및 매매 권유가 아닙니다. 투자의 최종 책임은 본인에게 있습니다.")
