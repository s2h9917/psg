# 💰 머니캐치 — MTN AI PICK (국내 · 실시간)

코스피·코스닥을 **네이버·야후 실시간 데이터**로 분석해 오늘의 추천 종목·매수가·목표가·추천 사유를 도출하고, 추천 내역/수익률·백테스트·자동 알림까지 제공하는 Streamlit 웹앱입니다. **KRX 직접 로그인 불필요.**

## 구성
- `app.py` — Streamlit UI (추천 · 내역/수익률 · 성과/백테스트)
- `engine.py` — 데이터 수집 + 스코어링 엔진
- `notify.py` — 매일 추천을 텔레그램으로 발송(스케줄용)
- `.github/workflows/daily.yml` — 매 평일 15:00 KST 자동 실행
- `requirements.txt` — 의존성

## 4팩터 스코어링
종합점수 = **펀더멘털**(ROE·PER·PBR·배당) + **수급**(기관·외국인 순매수) + **시장심리**(모멘텀/뉴스) + **상승여력**. 후보 내 백분위(percentile) 랭킹으로 정규화하며, 가중치는 사이드바에서 조절(자동 정규화). 매수가=20일선·눌림목, 목표가=52주 고점·점수 차등(현재가 +50% 이내 상한), 손절가=60일 저점 기준.

## 데이터 소스 (KRX 로그인 불필요)
| 항목 | 소스 |
|---|---|
| 코스피·코스닥 전종목 시세·시총·등락률 | 네이버/KRX 스냅샷(GitHub 캐시) |
| PER·PBR·ROE(=PBR/PER)·배당 | 네이버 금융 종목 페이지 |
| 기관·외국인 순매수(수급) | 네이버 금융 매매동향(frgn) |
| 52주 고저·이평·거래량·모멘텀 | 야후 파이낸스 |

## 기능
- **오늘의 추천**: TOP N 카드(4팩터 막대, 거래량 급증 🔥배지, 미니 주가차트, 추천 사유). **원샷 모드**로 1위만 크게 볼 수 있습니다.
- **추천 내역**: 추천 매수가 대비 수익률·목표달성 상태, 종목별 수익률 차트, 평균 수익률·승률, CSV 저장.
- **성과·백테스트**: 현재 선정 종목을 'N개월 전에 샀다면'의 과거 수익률(사후 참고).

## 로컬 실행
```bash
pip install -r requirements.txt
streamlit run app.py
```

## 무료 웹 배포 (브라우저만으로)
1. github.com에 `app.py`, `engine.py`, `requirements.txt` 업로드(Public 저장소).
2. share.streamlit.io → GitHub 로그인 → Create app → 저장소·`app.py` 지정 → Deploy.
3. `https://내앱이름.streamlit.app` 주소 생성.

## 매일 15시 자동 추천 알림 (텔레그램)
1. 텔레그램에서 **@BotFather** → `/newbot` → 봇 생성 후 **토큰** 발급.
2. 만든 봇에게 아무 메시지나 보낸 뒤, **@userinfobot**에게 말 걸어 내 **chat id** 확인.
3. GitHub 저장소 → **Settings → Secrets and variables → Actions → New repository secret** 로
   `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` 등록.
4. `notify.py`와 `.github/workflows/daily.yml`을 저장소에 올리면 매 평일 15:00 KST에 자동 발송됩니다.
   (Actions 탭 → daily-pick → **Run workflow**로 수동 테스트 가능)
5. 워크플로가 매일 `recommendation_history.csv`를 커밋해 **추천 내역이 영구 보존**됩니다.

로컬/수동 테스트: `DEMO=1 python notify.py` (네트워크 없이 출력), 실서버: `python notify.py`.

## 참고 / 한계
- 신규상장·적자 등 일부 종목은 재무·수급이 '미확보'로 표시될 수 있습니다(정상).
- 개별 조회(네이버·야후)는 종목당 시간이 걸리므로 '정밀분석 후보 수'를 늘리면 느려집니다.
- 1분 체결강도·틱 단위 실시간 수급 등은 유료·증권사 API가 필요해 미구현입니다.

## ⚠️ 유의사항
투자 참고용 도구이며 투자 자문·매매 권유가 아닙니다. 매수가·목표가·손절가와 과거 수익률은 미래 수익을 보장하지 않으며, 모든 투자 판단과 책임은 투자자 본인에게 있습니다. 불특정 다수 대상 유료 제공 시 유사투자자문업 등 규제 대상이 될 수 있으니 사전에 확인하세요.
