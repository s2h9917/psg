"""
engine.py — 국내 주식 추천 분석 엔진 (Streamlit 비의존)
------------------------------------------------------------
데이터 소스: pykrx(전종목 재무/시세) + FinanceDataReader/pykrx OHLCV(기술적 지표)
스코어링: 유니버스 내 백분위(percentile) 랭킹 기반 → 이상치에 강건함.

주의: 여기서 산출되는 매수가/목표가/손절가는 기술적·밸류에이션 참고 기준이며,
증권사 컨센서스나 투자 권유가 아닙니다.
"""

from __future__ import annotations
import os
from datetime import datetime, timedelta, time
import pandas as pd
import numpy as np

try:
    from zoneinfo import ZoneInfo
    _KST = ZoneInfo("Asia/Seoul")

    def now_kst():
        return datetime.now(_KST)
except Exception:
    def now_kst():
        return datetime.utcnow() + timedelta(hours=9)


# ====================================================================
# 데모(오프라인) 유니버스 — 실시간 연동 실패 시 UI 테스트용 폴백
# ====================================================================
DEMO_UNIVERSE = pd.DataFrame([
    # 티커, 종목명, 현재가, 시가총액(억), PER, PBR, EPS, BPS, DIV, 등락률(1M %)
    ["005930", "삼성전자",        72000, 4300000, 14.2, 1.4, 5070, 51000, 2.1,  4.5],
    ["000660", "SK하이닉스",     175000, 1270000, 11.5, 1.9, 15200, 92000, 1.2, 9.8],
    ["005380", "현대차",         240000,  510000,  5.8, 0.7, 41300, 340000, 4.0, 3.2],
    ["000270", "기아",           105000,  420000,  4.9, 0.9, 21400, 116000, 4.8, 2.1],
    ["005490", "POSCO홀딩스",    380000,  320000, 12.0, 0.6, 31600, 620000, 3.1, -1.5],
    ["051910", "LG화학",         320000,  225000, 18.0, 0.9, 17700, 355000, 1.0, -3.4],
    ["035420", "NAVER",          195000,  310000, 22.4, 1.3,  8700, 150000, 0.6, 1.0],
    ["055550", "신한지주",        52000,  270000,  6.5, 0.5,  8000, 104000, 5.2, 5.5],
    ["207940", "삼성바이오로직스", 780000,  555000, 55.0, 6.5, 14100, 120000, 0.0, 6.2],
    ["035720", "카카오",          48000,  213000, 35.1, 1.5,  1360, 32000, 0.2, -4.0],
    ["373220", "LG에너지솔루션",  350000,  819000, 60.0, 3.2,  5800, 109000, 0.3, -2.5],
    ["068270", "셀트리온",       185000,  400000, 40.0, 2.4,  4600, 77000, 0.4, 3.8],
    ["105560", "KB금융",          78000,  310000,  6.0, 0.5, 13000, 156000, 4.5, 6.1],
    ["012330", "현대모비스",     250000,  230000,  6.2, 0.5, 40300, 500000, 2.0, 1.4],
    ["066570", "LG전자",         100000,  163000,  9.5, 0.9, 10500, 111000, 1.5, 0.3],
    ["003670", "포스코퓨처엠",   280000,  217000, 90.0, 4.0,  3100, 70000, 0.2, -5.5],
    ["096770", "SK이노베이션",   115000,  115000, 20.0, 0.6,  5700, 191000, 1.0, -0.8],
    ["017670", "SK텔레콤",        53000,  115000, 10.5, 0.9,  5000, 58000, 6.8, 2.6],
    ["316140", "우리금융지주",    16000,  120000,  5.5, 0.4,  2900, 40000, 6.0, 4.3],
    ["030200", "KT",              42000,  110000,  8.0, 0.7,  5250, 60000, 4.9, 1.1],
], columns=["티커", "종목명", "현재가", "시가총액", "PER", "PBR",
            "EPS", "BPS", "DIV", "등락률"])
DEMO_UNIVERSE["ROE"] = (DEMO_UNIVERSE["EPS"] / DEMO_UNIVERSE["BPS"] * 100).round(2)
# 데모용 수급강도(순매수/상장주식수 근사): 모멘텀과 대략 연동되도록 합성
DEMO_UNIVERSE["수급강도"] = (DEMO_UNIVERSE["등락률"] / 1000).round(4)


# ====================================================================
# 영업일 계산
# ====================================================================
def recent_business_dates(n=12):
    """오늘(KST)부터 거슬러 올라가며 평일 날짜 문자열(YYYY-MM-DD) 목록 반환."""
    d = now_kst().date()
    out = []
    for i in range(n + 6):
        dd = d - timedelta(days=i)
        if dd.weekday() < 5:
            out.append(dd.strftime("%Y-%m-%d"))
        if len(out) >= n:
            break
    return out


# 코스피/코스닥 전종목 스냅샷 캐시 (FinanceData 팀이 GitHub에 매 영업일 게시, 출처: KRX/네이버)
_CACHE_URL = ("https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/"
              "refs/heads/master/data/listing/krx/{date}.csv")
_universe_cache = {}   # {frozenset(markets): (asof, DataFrame)}


def _load_market_snapshot():
    """가장 최근 영업일의 전종목 스냅샷 DataFrame과 기준일(asof)을 반환. (KRX 로그인 불필요)"""
    last_err = None
    for ds in recent_business_dates(12):
        try:
            raw = pd.read_csv(_CACHE_URL.format(date=ds), dtype={"Code": str})
            if len(raw) > 100:
                return raw, ds
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"전종목 스냅샷을 불러오지 못했습니다: {last_err}")


def load_universe_live(markets=("KOSPI", "KOSDAQ"), top_n_by_cap=200):
    """
    네이버/KRX 스냅샷(GitHub 캐시)에서 코스피·코스닥 전종목을 받아
    시가총액 상위 유니버스를 반환. (펀더멘털은 이후 야후로 개별 수집)
    반환 컬럼: 티커, 종목명, 현재가, 시가총액(억), 등락률, 시장
    """
    raw, asof = _load_market_snapshot()
    df = raw[raw["Market"].isin(list(markets))].copy()
    df = df.rename(columns={"Code": "티커", "Name": "종목명", "Close": "현재가",
                            "ChagesRatio": "등락률", "Marcap": "시가총액", "Market": "시장"})
    df = df[["티커", "종목명", "현재가", "등락률", "시가총액", "시장"]]
    df["현재가"] = pd.to_numeric(df["현재가"], errors="coerce")
    df["등락률"] = pd.to_numeric(df["등락률"], errors="coerce").fillna(0.0)
    df["시가총액"] = pd.to_numeric(df["시가총액"], errors="coerce") / 1e8   # 억 단위

    # 우선주·스팩 등 제외 (종목명 끝 '우'/'스팩' 간단 필터), 유효 시세만
    mask_pref = df["종목명"].str.contains("스팩") | df["종목명"].str.endswith(("우", "우B", "우C"))
    df = df[(df["현재가"] > 0) & (df["시가총액"] > 0) & (~mask_pref)]
    df = df.sort_values("시가총액", ascending=False).head(top_n_by_cap).reset_index(drop=True)
    df.attrs["asof"] = asof
    return df


# ====================================================================
# 스코어링 (백분위 랭킹 기반)
# ====================================================================
def _pct_high_good(s):
    return s.rank(pct=True)          # 값이 클수록 1에 가까움


def _pct_low_good(s):
    return 1 - s.rank(pct=True)      # 값이 작을수록 1에 가까움


def add_valuation_score(df):
    """ROE(↑)·PER(↓)·PBR(↓)·DIV(↑) 백분위 평균 → valuation_score(0~1).
    결측값은 표시용 원본은 그대로 두고, 점수 계산 시에만 중앙값(없으면 중립값)으로 보정."""
    df = df.copy()

    def _col(name, neutral):
        s = pd.to_numeric(df[name], errors="coerce")
        med = s.median()
        return s.fillna(med if pd.notna(med) else neutral)

    roe_p = _pct_high_good(_col("ROE", 8.0).clip(lower=0))
    per_p = _pct_low_good(_col("PER", 15.0))
    pbr_p = _pct_low_good(_col("PBR", 1.2))
    div_p = _pct_high_good(_col("DIV", 0.0))
    df["valuation_score"] = (roe_p * 0.35 + per_p * 0.30 +
                             pbr_p * 0.20 + div_p * 0.15)
    return df


def add_momentum_sentiment(df, news_scores=None):
    """
    등락률(1개월) → 시장 심리(모멘텀) sentiment(-1~1) 및 sentiment_score(0~1).
    news_scores: {티커: -1~1} 형태가 주어지면 뉴스 감성으로 대체.
    """
    df = df.copy()
    # 등락률(1개월)을 부드러운 곡선(tanh)으로 매핑 → 0/100에 고착되지 않고 항상 수치가 나옴
    chg = pd.to_numeric(df["등락률"], errors="coerce").fillna(0.0)
    mom = pd.Series(np.tanh(chg / 100.0 / 0.20), index=df.index).clip(-1, 1)  # 완만: ±20%≈±0.76
    if news_scores:
        news = df["티커"].map(news_scores)
        df["sentiment"] = news.fillna(mom).clip(-1, 1)
        df["sentiment_src"] = np.where(news.notna(), "뉴스", "모멘텀")
    else:
        df["sentiment"] = mom
        df["sentiment_src"] = "모멘텀"
    df["sentiment_score"] = (df["sentiment"] + 1) / 2
    return df


# ====================================================================
# 기술적 지표 (최종 후보에만 적용)
# ====================================================================
def _yf_symbol(ticker, market):
    return f"{ticker}.{'KQ' if market == 'KOSDAQ' else 'KS'}"


def _num_after(html, anchor, window=180):
    """html에서 anchor 문자열 뒤 구간의 첫 숫자를 float으로 반환 (태그 제거)."""
    import re
    i = html.find(anchor)
    if i < 0:
        return None
    seg = re.sub(r"<[^>]+>", " ", html[i:i + window])
    m = re.search(r"-?\d[\d,]*\.?\d*", seg)
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def fetch_fundamentals_naver(code):
    """
    네이버 금융 종목 페이지에서 PER·PBR을 직접 수집(요소 id `_per`,`_pbr`는 오래 안정적).
    ROE = PBR / PER × 100 로 산출(수학적으로 EPS/BPS와 동일). 클라우드에서도 안정적.
    """
    import urllib.request
    out = {"PER": np.nan, "PBR": np.nan, "ROE": np.nan, "DIV": np.nan}
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=6).read().decode("euc-kr", "ignore")
    except Exception:
        return out

    per = _num_after(html, 'id="_per"')
    pbr = _num_after(html, 'id="_pbr"')
    if per and per > 0:
        out["PER"] = per
    if pbr and pbr > 0:
        out["PBR"] = pbr
    if out["PER"] and out["PBR"] and not (np.isnan(out["PER"]) or np.isnan(out["PBR"])):
        out["ROE"] = round(out["PBR"] / out["PER"] * 100, 2)   # ROE ≈ PBR/PER

    dvr = _num_after(html, 'id="_dvr"')   # 배당수익률(있으면)
    if dvr is not None and 0 <= dvr < 30:
        out["DIV"] = dvr
    return out


def fetch_metrics(ticker, market="KOSPI", fallback_price=None, fallback_chg=None):
    """
    재무(PER·PBR·ROE·배당)는 네이버에서, 기술지표(현재가·52주·이평·모멘텀)는 야후에서 수집.
    반환: PER, PBR, ROE(%), DIV(%), 현재가, 등락률(약 1개월 모멘텀 %), high52, ma20, low60
    """
    import yfinance as yf
    sym = _yf_symbol(ticker, market)
    m = {"PER": np.nan, "PBR": np.nan, "ROE": np.nan, "DIV": np.nan,
         "현재가": fallback_price, "등락률": fallback_chg,
         "high52": None, "ma20": None, "low60": None,
         "vol_ratio": None, "spark": None}

    # --- 펀더멘털: 네이버 (신뢰도 높음) ---
    try:
        f = fetch_fundamentals_naver(ticker)
        m.update({k: f[k] for k in ("PER", "PBR", "ROE", "DIV")})
    except Exception:
        pass

    # --- 기술지표: 야후 1년 주가 ---
    tk = yf.Ticker(sym)
    try:
        hist = tk.history(period="1y")
        close = hist["Close"].dropna()
        if len(close):
            cur = float(close.iloc[-1])
            m["현재가"] = cur
            m["high52"] = float(close.max())
            m["low60"] = float(close.tail(60).min())
            m["ma20"] = float(close.tail(20).mean())
            if len(close) > 21:
                m["등락률"] = (cur / float(close.iloc[-21]) - 1) * 100
            m["spark"] = [round(float(x), 2) for x in close.tail(60).tolist()]
        vol = hist["Volume"].dropna() if "Volume" in hist else None
        if vol is not None and len(vol) > 20:
            avg20 = float(vol.tail(20).mean())
            if avg20 > 0:
                m["vol_ratio"] = float(vol.iloc[-1]) / avg20  # 당일 거래량 / 20일 평균
    except Exception:
        pass
    try:
        fi = tk.fast_info
        m["현재가"] = m["현재가"] or float(fi["last_price"])
        m["high52"] = m["high52"] or float(fi["year_high"])
        if m["ma20"] is None:
            m["ma20"] = float(fi["fifty_day_average"])
    except Exception:
        pass

    # --- 폴백/정합성 정리 ---
    cur = m["현재가"] or fallback_price or 0
    # 비정상 52주 고가(현재가보다 낮거나 3배 초과)는 신뢰 불가 → 보수적 대체
    if not (m["high52"] and cur and cur <= m["high52"] <= cur * 3):
        m["high52"] = cur * 1.2
    if m["ma20"] is None: m["ma20"] = cur * 0.98
    if m["low60"] is None: m["low60"] = cur * 0.9
    if m["등락률"] is None: m["등락률"] = fallback_chg if fallback_chg is not None else 0.0
    # ROE 이상치 방어
    if m["ROE"] is not None and not np.isnan(m["ROE"]) and abs(m["ROE"]) > 150:
        m["ROE"] = np.nan
    return m


def fetch_supply(code, n_days=20):
    """
    네이버 금융 '외국인·기관 매매동향'(frgn.naver)에서 최근 N영업일
    기관+외국인 순매매(주식수) 합계를 반환. 순매수(+)/순매도(-).
    반환: {"net": 순매매합계(주), "days": 실제집계일수}
    """
    import urllib.request
    import io
    out = {"net": None, "days": 0}
    url = f"https://finance.naver.com/item/frgn.naver?code={code}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=6).read().decode("euc-kr", "ignore")
    except Exception:
        return out
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:
        return out
    # 기관/외국인 순매매 컬럼을 가진 표 탐색
    target = None
    for t in tables:
        cols = [str(c) for c in t.columns.get_level_values(-1)]
        if any("기관" in c for c in cols) and any("외국인" in c for c in cols):
            target = t
            break
    if target is None:
        return out
    try:
        flat = [str(c) for c in target.columns.get_level_values(-1)]
        inst_i = next(i for i, c in enumerate(flat) if "기관" in c)
        forn_i = next(i for i, c in enumerate(flat) if "외국인" in c and "보유" not in c)
        sub = target.iloc[:, [inst_i, forn_i]].apply(
            lambda s: pd.to_numeric(
                s.astype(str).str.replace(",", "").str.replace("+", ""), errors="coerce"))
        sub = sub.dropna().head(n_days)
        if len(sub):
            out["net"] = float(sub.sum().sum())
            out["days"] = int(len(sub))
    except Exception:
        pass
    return out


def add_supply_score(df):
    """수급강도(순매수 주식수 ÷ 상장주식수) 백분위 → supply_score(0~1)."""
    df = df.copy()
    if "수급강도" not in df.columns:
        df["supply_score"] = 0.5
        return df
    s = pd.to_numeric(df["수급강도"], errors="coerce")
    if s.notna().sum() == 0:
        df["supply_score"] = 0.5
    else:
        df["supply_score"] = s.fillna(s.median()).rank(pct=True)
    return df


def _round_to(v, base=100):
    return int(base * round(float(v) / base))


def compute_price_targets(current, tech, score_unit):
    """
    매수가(진입 참고)·목표가(기술적 저항+밸류 리레이팅)·손절가(지지 이탈) 산출.
    score_unit: 0~1 종합점수 정규화값 → 목표 상승률 차등에 사용.
    """
    ma20 = tech.get("ma20", current)
    high52 = tech.get("high52", current)
    low60 = tech.get("low60", current * 0.9)

    # 매수가: 현재가와 20일선 사이의 눌림목 진입 기준
    buy = min(current * 0.99, max(ma20, current * 0.96))
    # 목표가: 52주 고점(저항) 또는 점수 차등 상승률(10~28%) 중 높은 값,
    #        단 과도한 목표를 막기 위해 현재가 대비 +50% 이내로 상한
    expected = 0.10 + 0.18 * score_unit
    target = max(high52, current * (1 + expected))
    target = min(target, current * 1.5)
    # 손절가: 최근 60일 저점과 매수가 -8% 중 낮은 쪽
    stop = min(low60, buy * 0.92)

    buy, target, stop = _round_to(buy), _round_to(target), _round_to(stop)
    upside = (target - current) / current if current else 0.0
    return buy, target, stop, upside


# ====================================================================
# 종합 점수 & 추천 사유
# ====================================================================
def finalize(df, w_fund, w_sent, w_upside, w_supply=0.0):
    """상승여력·수급 점수 반영 후 종합 점수(0~100) 계산 및 정렬."""
    df = df.copy()
    if "supply_score" not in df.columns:
        df["supply_score"] = 0.5   # 수급 데이터 없으면 중립
    total = w_fund + w_sent + w_upside + w_supply
    if total == 0:
        w_fund = w_sent = w_upside = w_supply = 0.25
    else:
        w_fund, w_sent, w_upside, w_supply = (w_fund/total, w_sent/total,
                                              w_upside/total, w_supply/total)

    up = df["upside"].clip(lower=0)
    df["upside_score"] = (up / 0.5).clip(0, 1)   # 상승여력 50% → 만점

    df["total_score"] = (
        df["valuation_score"] * w_fund +
        df["sentiment_score"] * w_sent +
        df["upside_score"] * w_upside +
        df["supply_score"] * w_supply
    ) * 100
    return df.sort_values("total_score", ascending=False).reset_index(drop=True)


def build_reason(row):
    roe, per, pbr = row.get("ROE"), row.get("PER"), row.get("PBR")
    sent, src = row["sentiment"], row.get("sentiment_src", "모멘텀")
    upside = row["upside"]

    roe_ok = roe is not None and pd.notna(roe)
    per_ok = per is not None and pd.notna(per) and per > 0
    pbr_ok = pbr is not None and pd.notna(pbr) and pbr > 0

    if not roe_ok:
        roe_txt = "수익성 지표(ROE)는 공개 데이터에서 확인되지 않았습니다."
    elif roe >= 15:
        roe_txt = f"높은 ROE({roe:.1f}%)로 수익성이 매우 우수합니다."
    elif roe >= 8:
        roe_txt = f"양호한 ROE({roe:.1f}%)로 안정적인 수익성을 확보하고 있습니다."
    else:
        roe_txt = f"ROE({roe:.1f}%)는 다소 낮아 수익성 개선이 관건입니다."

    pbr_str = f"·PBR {pbr:.2f}배" if pbr_ok else ""
    if not per_ok:
        per_txt = "PER/PBR 등 밸류에이션 지표를 확보하지 못해 이번 평가에서는 모멘텀·상승여력 비중이 큽니다."
    elif per <= 10:
        per_txt = f"PER {per:.1f}배{pbr_str}로 저평가 매력이 큽니다."
    elif per <= 20:
        per_txt = f"PER {per:.1f}배{pbr_str}로 밸류에이션이 적정 수준입니다."
    else:
        per_txt = f"PER {per:.1f}배{pbr_str}로 밸류에이션 부담은 존재합니다."

    label = "뉴스 심리" if src == "뉴스" else "가격 모멘텀(시장 심리)"
    if sent >= 0.5:
        sent_txt = f"최근 {label}가 매우 긍정적입니다."
    elif sent >= 0.15:
        sent_txt = f"최근 {label}가 긍정적입니다."
    elif sent >= -0.15:
        sent_txt = f"최근 {label}는 중립적입니다."
    else:
        sent_txt = f"최근 {label}는 다소 부정적입니다."

    # 수급(기관·외국인) 코멘트
    sup = row.get("수급강도")
    sup_txt = ""
    if sup is not None and pd.notna(sup):
        if sup >= 0.01:
            sup_txt = " 최근 기관·외국인 순매수가 뚜렷하게 유입되고 있습니다."
        elif sup > 0:
            sup_txt = " 최근 기관·외국인 수급이 소폭 순매수 우위입니다."
        elif sup <= -0.01:
            sup_txt = " 다만 최근 기관·외국인 순매도가 관찰됩니다."
        else:
            sup_txt = " 기관·외국인 수급은 중립적입니다."

    # 거래량 급증 코멘트
    vr = row.get("vol_ratio")
    vol_txt = ""
    if vr is not None and pd.notna(vr) and vr >= 2.0:
        vol_txt = f" 당일 거래량이 20일 평균의 {vr:.1f}배로 관심이 집중되고 있습니다."

    return (f"{roe_txt} {per_txt} {sent_txt}{sup_txt}{vol_txt} "
            f"기술적·밸류에이션 기준 상승여력은 약 **{upside*100:.1f}%**입니다.")


def backtest_picks(pick_list, months=3):
    """
    선정 종목들을 'months개월 전에 매수했다면'의 과거 수익률(사후 참고).
    pick_list: [(티커, 시장, 종목명), ...]  → DataFrame 반환.
    ※ 워크포워드 백테스트가 아니라 현재 선정 종목의 과거 성과 확인용입니다.
    """
    import yfinance as yf
    rows = []
    for code, market, name in pick_list:
        sym = _yf_symbol(code, market)
        ret = np.nan
        try:
            close = yf.Ticker(sym).history(period="1y")["Close"].dropna()
            if len(close) > 5:
                days = min(len(close) - 1, int(months * 21))
                past, now_ = float(close.iloc[-1 - days]), float(close.iloc[-1])
                if past > 0:
                    ret = (now_ - past) / past * 100
        except Exception:
            pass
        rows.append({"종목명": name, "티커": code, f"{months}개월 수익률(%)": round(ret, 1) if pd.notna(ret) else np.nan})
    return pd.DataFrame(rows)


# ====================================================================
# 뉴스 감성 (선택) — 네이버 뉴스 검색 API + 간이 사전
# ====================================================================
_POS = ["상승", "급등", "호조", "개선", "수주", "흑자", "최대", "신고가", "성장", "기대",
        "호실적", "수혜", "확대", "반등", "강세", "돌파", "상향", "역대", "훈풍"]
_NEG = ["하락", "급락", "부진", "악화", "적자", "우려", "감소", "약세", "손실", "하향",
        "리콜", "규제", "충격", "폭락", "불확실", "둔화", "위기", "경고", "리스크"]


def naver_news_sentiment(query, client_id, client_secret, display=20):
    """네이버 뉴스 검색 API로 헤드라인 수집 후 사전 기반 감성(-1~1) 반환. 실패 시 None."""
    import urllib.request
    import urllib.parse
    import json
    import re
    try:
        url = ("https://openapi.naver.com/v1/search/news.json?query="
               + urllib.parse.quote(query) + f"&display={display}&sort=date")
        req = urllib.request.Request(url)
        req.add_header("X-Naver-Client-Id", client_id)
        req.add_header("X-Naver-Client-Secret", client_secret)
        with urllib.request.urlopen(req, timeout=5) as resp:
            items = json.loads(resp.read().decode("utf-8")).get("items", [])
        if not items:
            return None
        scores = []
        for it in items:
            text = re.sub(r"<[^>]+>", "", it.get("title", "") + " " + it.get("description", ""))
            p = sum(w in text for w in _POS)
            n = sum(w in text for w in _NEG)
            if p + n > 0:
                scores.append((p - n) / (p + n))
        return float(np.clip(np.mean(scores), -1, 1)) if scores else 0.0
    except Exception:
        return None


# ====================================================================
# 시장 상태
# ====================================================================
def market_status(now):
    if now.weekday() >= 5:
        return "🔴 휴장", "주말에는 정규장이 열리지 않습니다."
    t = now.time()
    if t < time(9, 0):
        return "🟡 장 시작 전", "정규장은 오전 9시에 시작됩니다."
    if t > time(15, 30):
        return "🔴 장 마감", "정규장이 종료되었습니다. (마감 15:30)"
    if time(14, 30) <= t <= time(15, 30):
        return "🟢 장중 (마감 임박)", "마감 전 최종 점검에 적합한 시간대입니다."
    return "🟢 장중", "정규장이 진행 중입니다."


# ====================================================================
# 현재가 조회 (추천 내역 수익률 계산용)
# ====================================================================
def get_current_prices(tickers):
    """티커 리스트의 최신 종가를 {티커: 가격}으로 반환 (전종목 스냅샷 1회)."""
    try:
        raw, _ = _load_market_snapshot()
        raw["Code"] = raw["Code"].astype(str)
        price_map = dict(zip(raw["Code"], pd.to_numeric(raw["Close"], errors="coerce")))
    except Exception:
        price_map = {}
    return {str(t): price_map.get(str(t)) for t in tickers}


# ====================================================================
# 추천 내역 저장/조회 (CSV 파일 영속화)
# ====================================================================
HISTORY_COLUMNS = ["추천일시", "티커", "종목명", "추천시_현재가",
                   "매수가", "목표가", "손절가", "종합점수"]
DEFAULT_HISTORY_PATH = "recommendation_history.csv"


def load_history(path=DEFAULT_HISTORY_PATH):
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, dtype={"티커": str})
            for c in HISTORY_COLUMNS:
                if c not in df.columns:
                    df[c] = pd.NA
            return df[HISTORY_COLUMNS]
        except Exception:
            pass
    return pd.DataFrame(columns=HISTORY_COLUMNS)


def append_history(new_df, path=DEFAULT_HISTORY_PATH):
    """새 추천 내역을 이어붙이고 (추천일시,티커) 중복 제거 후 저장."""
    hist = load_history(path)
    new_df = new_df.copy()
    new_df["티커"] = new_df["티커"].astype(str)
    new_df = new_df[HISTORY_COLUMNS]
    combined = new_df if hist.empty else pd.concat([hist, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["추천일시", "티커"], keep="last")
    combined = combined.sort_values("추천일시", ascending=False).reset_index(drop=True)
    combined.to_csv(path, index=False, encoding="utf-8-sig")
    return combined


def clear_history(path=DEFAULT_HISTORY_PATH):
    if os.path.exists(path):
        os.remove(path)


def enrich_history(hist_df, current_prices=None):
    """
    추천 내역에 현재가·수익률·상태·목표까지 남은 여력을 계산해 반환.
    수익률(%) = (현재가 - 추천 매수가) / 추천 매수가 × 100
    """
    df = hist_df.copy()
    if df.empty:
        for c in ["현재가", "수익률", "목표까지", "상태"]:
            df[c] = []
        return df

    for c in ["추천시_현재가", "매수가", "목표가", "손절가", "종합점수"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    cp = current_prices or {}
    df["현재가"] = df["티커"].astype(str).map(cp)
    df["현재가"] = df["현재가"].fillna(df["추천시_현재가"])

    df["수익률"] = (df["현재가"] - df["매수가"]) / df["매수가"] * 100
    df["목표까지"] = (df["목표가"] - df["현재가"]) / df["현재가"] * 100

    def _status(r):
        if pd.notna(r["현재가"]):
            if r["현재가"] >= r["목표가"]:
                return "🎯 목표달성"
            if r["현재가"] <= r["손절가"]:
                return "🛑 손절이탈"
        return "⏳ 보유중"

    df["상태"] = df.apply(_status, axis=1)
    return df
