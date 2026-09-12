#!/usr/bin/env python3
"""Upside-readiness ranking (0-100) across the three lists -> rank_overlay.json,
plus the catalyst layer -> catalysts.json.

Composite: trend 25 + pivot proximity 20 + tightness 15 + youth 15 + volume
dry-up 10 + cross-family consensus 15, then a bounded qualitative adjustment
(±8) for NEWS items only. One-day price moves are shown as highlights but carry
NO points: every row is already priced on the same official close, so scoring
the move again would double count it (critical-review finding, 2026-09-02).
"""
import json

FILES = [('scan_R23_2026-09-12.json', 'category'),
         ('scan_stage_R16_2026-09-12.json', 'stage'),
         ('scan_PB-R16_2026-09-12.json', 'category')]
ONLINE = {'A_VCP待突破', 'E_突破延伸中', 'B_上升結構', '2A_初升段', '2B_主升段', '1轉2_轉強觀察'}
BASIS = '2026-09-11'

# Qualitative NEWS catalysts only: (pts, date, text). Text must not contain '、'.
NEWS = {
    # 9/11 session (the classification basis). CPI landed close to expectations
    # (headline 3.4% y/y, core 2.4% with core 0.1pp hot) and oil eased, ending a
    # four-day slide; Oracle's capex guidance sent AI server names flying while
    # the SMR/nuclear complex broke down on a UBS downgrade and an Oklo ATM.
    'HPE':  (7, '2026-09-11', 'Oracle 資本開支指引帶動 AI 伺服器需求＋9/2 上調全年指引，+12.4%'),
    'DELL': (7, '2026-09-11', 'Oracle 資本開支指引；Q2 營收 +58%、AI 訂單 $60.9B／backlog $95B，+12.0%'),
    'SMCI': (5, '2026-09-11', 'AI 伺服器同步走強'),
    'ANET': (4, '2026-09-11', 'AI 資料中心網絡受惠 Oracle 資本開支'),
    'CLS':  (4, '2026-09-11', 'AI 硬件代工同步走強'),
    'BE':   (4, '2026-09-11', '資料中心供電需求'),
    'SMR':  (-8, '2026-09-11', 'UBS 降至賣出、目標價削至 $6（工期逾五年、無確定客戶、三年燒錢 $7 億），−15.7%'),
    'OKLO': (-6, '2026-09-11', '新設 $10 億 ATM 增發計劃＋核電板塊同步下挫，−9.2%'),
    # 9/10
    'AEO':  (-6, '2026-09-10', '財報 EPS 大勝（含關稅退款），惟同店遜預期、AE 品牌 −1%、毛利率 −3.3pp，跌 14%'),
    'RDDT': (4, '2026-09-10', 'Piper Sandler：8 月月活按月 +8%、按年 +18%'),
    # 9/9
    'NET':  (4, '2026-09-09', '與 OpenAI 合推 AI 資安平台（GPT-5.6 Cyber）'),
    'META': (4, '2026-09-09', '發布 Muse AI agent（訂閱制）'),
    # 9/8
    'LITE': (3, '2026-09-08', 'AI 光通訊全線大漲（+11%）'),
    'INTC': (2, '2026-09-08', '$200 億股票增發（每股 $95）強化 AI 與代工資本開支'),
    'LMT':  (2, '2026-09-08', '中東衝突升級，防務股獲上調評級'),
    # oil complex — crude eased back on 9/11 after topping $100
    'CVX':  (1, '2026-09-11', '油價自 $102 高位回落，能源板塊持平'),
    'XOM':  (1, '2026-09-11', '油價自高位回落'),
    # earlier, still explanatory
    'LULU': (-4, '2026-09-04', '財報：營收 −4%、同店 −9%，大砍全年指引，跌 17%'),
    'TSLA': (-2, '2026-09-04', 'Cybercab 發表令人失望＋NHTSA 審查'),
    'SNOW': (2, '2026-09-03', '財報超預期：產品營收 +37%、上調全年指引'),
    'HOOD': (2, '2026-09-03', '納入標普 500；MS 上調至 Overweight'),
    'MRNA': (3, '2026-09-11', '生技反彈，+5.4%（8/19 癌症疫苗三期成功後高位震盪）'),
    'GSAT': (-8, '2026-08-27', '被收購，價格封頂'),
    'RUSHB': (0, '2026-08-31', '3:2 拆股（已調整）'),
}
MOVE_MIN = 3.0   # a |basis-day move| >= 3% is shown as a highlight (pts 0)

rows_by = {}
for f, key in FILES:
    for r in json.load(open(f))['rows']:
        e = rows_by.setdefault(r['ticker'], {'rows': [], 'fam': set()})
        e['rows'].append(r)
        if r[key] in ONLINE:
            e['fam'].add('stage' if key == 'stage' else 'vcp')   # VCP and Pre-breakout share inputs -> one family

def pick(rows, k):
    vals = [r.get(k) for r in rows if r.get(k) is not None]
    return vals[0] if vals else None

# sanity: a news chip's sign must not contradict a large official move the other way
for t, (pts, d, txt) in NEWS.items():
    r = rows_by.get(t)
    mv = pick(r['rows'], 'chg_1d') if r else None
    if mv is not None and ((pts > 0 and mv < -2) or (pts < 0 and mv > 2)):
        print(f"WARNING catalyst sign vs official move: {t} pts {pts:+d} but {mv:+.1f}% on {BASIS}")

out, cats = {}, {}
for t, e in rows_by.items():
    rows = e['rows']
    off = min((r.get('off_high_pct') for r in rows if r.get('off_high_pct') is not None), default=50)
    above_low = max((r.get('above_low_pct') or 0) for r in rows)
    a200 = any(r.get('above_ma200') for r in rows)
    a50 = any(r.get('above_ma50') for r in rows)
    c1 = pick(rows, 'chg_1m'); c6 = pick(rows, 'chg_6m'); c1y = pick(rows, 'chg_1y')
    vr = pick(rows, 'vol_ratio'); rng = pick(rows, 'range_1m_pct'); mv = pick(rows, 'chg_1d')
    terms = []   # (points, label)

    trend = (15 if a200 else 0) + (10 if a50 else 0)
    if trend == 0 and above_low >= 30 and off <= 20:
        trend = 18
    terms.append((trend, '趨勢完整' if trend >= 20 else ''))

    prox = max(0, 20 * (1 - min(off, 25) / 25))
    terms.append((prox, f'距高僅{off:.0f}%' if off <= 6 else f'距高{off:.0f}%'))

    if c1 is not None:
        tight = max(0, 15 * (1 - min(abs(c1), 15) / 15))
        if rng is not None and rng > 15:
            tight *= 0.5
        terms.append((tight, '月線緊縮' if (abs(c1) <= 5 and off <= 15 and (rng is None or rng <= 12)) else ''))
    else:
        terms.append((7, ''))

    if c6 is not None and c1y is not None and 12 <= c6 <= 60 and c1y <= 100:
        terms.append((15, '升勢年輕'))
    elif c1y is not None and 10 <= c1y <= 100:
        terms.append((10, ''))
    elif c1y is not None and c1y > 150:
        terms.append((0, '漲幅已大'))
    elif c1 is not None and c1 > 20:
        terms.append((3, '單月急漲'))
    else:
        terms.append((5, ''))

    vol = 0
    if isinstance(vr, (int, float)):
        vol = 10 if vr < 0.7 else (6 if vr < 0.95 else 0)
    terms.append((vol, '明顯量縮' if vol == 10 else ''))

    cons = 7.5 * len(e['fam'])          # VCP/PB family + Weinstein family -> max 15
    terms.append((cons, '兩派共識' if len(e['fam']) == 2 else ''))

    pts, tag = 0, ''
    if t in NEWS:
        pts, d, txt = NEWS[t]
        tag = txt
    score = max(0, min(100, sum(p for p, _ in terms) + pts))
    labels = [l for p, l in sorted(terms, key=lambda x: -x[0]) if l]
    why = ('；'.join(([tag] if tag else []) + labels[:3]))[:60]
    out[t] = {'score': round(score, 1), 'why': why}

    mlabel = f"{int(BASIS[5:7])}/{int(BASIS[8:10])}"
    move_txt = f'{mlabel} {mv:+.1f}%' if (mv is not None and abs(mv) >= MOVE_MIN) else ''
    if t in NEWS or move_txt:
        pts_, d_, txt_ = NEWS.get(t, (0, BASIS, ''))
        reason = '，'.join(x for x in (move_txt, txt_) if x)
        cats[t] = {'pts': pts_, 'reason': reason, 'move': mv, 'date': d_, 'kind': 'news' if t in NEWS else 'move'}

json.dump(out, open('rank_overlay.json', 'w'), ensure_ascii=False, indent=1)
json.dump(cats, open('catalysts.json', 'w'), ensure_ascii=False, indent=1)
top = sorted(out.items(), key=lambda kv: -kv[1]['score'])[:12]
for t, v in top:
    print(f"{t:<6}{v['score']:>6.1f}  {v['why']}")
print(f"catalyst chips: {len(cats)} ({sum(1 for c in cats.values() if c['kind']=='news')} news, "
      f"{sum(1 for c in cats.values() if c['kind']=='move')} pure moves)")
