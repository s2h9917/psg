"""
notify.py — 매 영업일 추천 종목을 생성해 텔레그램으로 발송하는 스탠드얼론 스크립트.
GitHub Actions(.github/workflows/daily.yml)에서 매일 15:00 KST에 실행됩니다.

환경변수:
  TELEGRAM_TOKEN     텔레그램 봇 토큰 (BotFather 발급)
  TELEGRAM_CHAT_ID   받을 채팅 ID
  MARKETS            'KOSPI,KOSDAQ' (기본)
  TOP_N              추천 개수 (기본 3)
  CAP_N / SHORT_K    유니버스/후보 수
  W_FUND,W_SUPPLY,W_SENT,W_UPSIDE   가중치
  DEMO=1             네트워크 없이 데모 데이터로 테스트
  토큰이 없으면 발송 대신 화면에 출력(dry-run)합니다.
"""

import os
import urllib.request
import urllib.parse
import pandas as pd
import numpy as np
import engine as E

HISTORY_PATH = "recommendation_history.csv"


def _env(name, default):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def pick_shortlist(uni, k, markets):
    mkts = [m for m in markets if m in set(uni.get("시장", pd.Series()).unique())]
    if len(mkts) <= 1:
        return uni.head(k).copy()
    per = max(1, k // len(mkts))
    parts = [uni[uni["시장"] == m].head(per) for m in mkts]
    short = pd.concat(parts)
    if len(short) < k:
        short = pd.concat([short, uni[~uni["티커"].isin(short["티커"])].head(k - len(short))])
    return short.reset_index(drop=True)


def build_recommendations():
    markets = tuple(_env("MARKETS", "KOSPI,KOSDAQ").split(","))
    cap_n = int(_env("CAP_N", "200"))
    short_k = int(_env("SHORT_K", "14"))
    top_n = int(_env("TOP_N", "3"))
    supply_days = int(_env("SUPPLY_DAYS", "20"))
    w = (float(_env("W_FUND", "0.4")), float(_env("W_SENT", "0.15")),
         float(_env("W_UPSIDE", "0.25")), float(_env("W_SUPPLY", "0.2")))
    demo = _env("DEMO", "0") == "1"

    if demo:
        uni = E.DEMO_UNIVERSE.copy()
        df = uni.sort_values("시가총액", ascending=False).head(short_k).copy()
        df["_tech"] = df["현재가"].apply(lambda c: {"high52": c*1.22, "ma20": c*0.98, "low60": c*0.9})
        df["vol_ratio"] = 1.0
        asof = E.now_kst().strftime("%Y-%m-%d")
    else:
        uni = E.load_universe_live(markets=markets, top_n_by_cap=cap_n)
        asof = uni.attrs.get("asof", "")
        short = pick_shortlist(uni, short_k, list(markets))
        rows = []
        for _, r in short.iterrows():
            m = E.fetch_metrics(r["티커"], r["시장"], float(r["현재가"]), float(r["등락률"]))
            cur = m["현재가"] or r["현재가"]
            si = None
            if w[3] > 0:
                sup = E.fetch_supply(r["티커"], supply_days)
                if sup["net"] is not None and cur:
                    so = (float(r["시가총액"]) * 1e8) / cur
                    if so > 0:
                        si = sup["net"] / so
            rows.append({"티커": r["티커"], "종목명": r["종목명"], "시장": r["시장"],
                         "시가총액": r["시가총액"], "현재가": cur, "등락률": m["등락률"],
                         "PER": m["PER"], "PBR": m["PBR"], "ROE": m["ROE"], "DIV": m["DIV"],
                         "수급강도": si, "vol_ratio": m["vol_ratio"],
                         "_tech": {"high52": m["high52"], "ma20": m["ma20"], "low60": m["low60"]}})
        df = pd.DataFrame(rows)

    df = E.add_valuation_score(df)
    df = E.add_momentum_sentiment(df)
    df = E.add_supply_score(df)
    b, t, s, u = [], [], [], []
    for _, r in df.iterrows():
        su = (r["valuation_score"] + r["sentiment_score"]) / 2
        bb, tt, ss, uu = E.compute_price_targets(float(r["현재가"]), r["_tech"], su)
        b.append(bb); t.append(tt); s.append(ss); u.append(uu)
    df["buy"], df["target"], df["stop"], df["upside"] = b, t, s, u
    res = E.finalize(df, w[0], w[1], w[2], w[3])
    return res.head(top_n), asof


def format_message(top, asof):
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"📈 <b>오늘의 추천 종목</b> (기준일 {asof})", ""]
    for i, r in top.iterrows():
        m = medals[i] if i < 3 else "🔹"
        mkt = r.get("시장", "")
        lines.append(f"{m} <b>{r['종목명']}</b> {r['티커']} · {mkt} · 종합 {r['total_score']:.0f}점")
        lines.append(f"   매수 {int(r['buy']):,} → 목표 {int(r['target']):,} "
                     f"(+{r['upside']*100:.0f}%) · 손절 {int(r['stop']):,}")
        reason = E.build_reason(r).replace("**", "")
        lines.append(f"   💡 {reason}")
        lines.append("")
    lines.append("⚠️ 투자 참고용이며 매매 권유가 아닙니다. 투자 책임은 본인에게 있습니다.")
    return "\n".join(lines)


def send_telegram(text):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[dry-run] TELEGRAM_TOKEN/CHAT_ID 미설정 → 발송 대신 출력합니다.\n")
        print(text)
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat, "text": text,
                                   "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as resp:
        print("텔레그램 발송 완료:", resp.status)


def main():
    top, asof = build_recommendations()
    ran_at = E.now_kst().strftime("%Y-%m-%d %H:%M")
    # 추천 내역 저장(누적 트랙레코드) — 워크플로가 이 CSV를 커밋하면 영구 보존됩니다.
    try:
        E.append_history(pd.DataFrame({
            "추천일시": ran_at, "티커": top["티커"].astype(str), "종목명": top["종목명"],
            "추천시_현재가": top["현재가"].astype(int), "매수가": top["buy"].astype(int),
            "목표가": top["target"].astype(int), "손절가": top["stop"].astype(int),
            "종합점수": top["total_score"].round(1)}), HISTORY_PATH)
    except Exception as e:
        print("내역 저장 경고:", e)
    send_telegram(format_message(top, asof))


if __name__ == "__main__":
    main()
