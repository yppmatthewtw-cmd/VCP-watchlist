#!/usr/bin/env python3
"""Compute the Page-D upside-readiness ranking (0-100) across all three lists.

Composite, applied uniformly to every ticker:
  trend 25 + pivot proximity 20 + tightness 15 + youth 15 + volume dry-up 10
  + cross-list consensus 15, then a bounded qualitative catalyst adjustment
  (±10) for events known this week. Emits rank_overlay.json {ticker: {score, why}}.
"""
import json

FILES = [('scan_R15_2026-09-01.json', 'category'),
         ('scan_stage_R8_2026-09-01.json', 'stage'),
         ('scan_PB-R8_2026-09-01.json', 'category')]
ONLINE = {'A_VCP待突破', 'E_突破延伸中', 'B_上升結構', '2A_初升段', '2B_主升段', '1轉2_轉強觀察'}

# Qualitative catalyst adjustments (my read of this week's events), bounded ±10.
CATALYST = {
    # 9/1 session: renewed US strikes on Iranian targets near Hormuz lifted oil
    # and bond yields; TECH led the selling (Nasdaq -1.02%, XLK -1.6%) while
    # energy and defensive pharma held up. 8/31 moves kept where still relevant.
    'CVX': (5, '9/1 +1.5%，油價避險'), 'SU': (5, '9/1 +3.3%'),
    'RPRX': (4, '9/1 +2.6%'), 'MRK': (4, '9/1 +1.8%，防禦性領漲'),
    'JNJ': (3, '9/1 +1.6%，防禦性領漲'), 'FTI': (3, '9/1 +1.0%，油服續強'),
    'EOG': (5, '油價破$90後續強'), 'TRGP': (4, '中游受惠油價'),
    'CVE': (3, '油氣走強'), 'EQNR': (3, '油氣走強'), 'DINO': (3, '煉油受惠'),
    'CNQ': (3, '油氣走強'), 'CHRD': (3, '油氣走強'),
    'PANW': (-6, '9/1 -3.6%，科技領跌'), 'AMZN': (-6, '9/1 -2.7%，FTC 訴訟'),
    'GOOGL': (-5, '9/1 -2.2%'), 'NVDA': (-5, '9/1 -2.0%，科技領跌'),
    'CAT': (-4, '9/1 -1.7%'), 'MSFT': (-3, '9/1 -1.2%'),
    'CRWD': (2, '財報後仍強，惟科技板塊承壓'),
    'MRNA': (3, '8/19癌症疫苗三期成功+177%，高位整理'),
    'CRM': (2, '財報+Anthropic合作'),
    'AXON': (-5, '8/31 -5.3%'), 'TD': (-4, '8/31 -3.4%'),
    'MRVL': (-4, '指引不如預期'), 'UNP': (-3, '運輸受油價壓'),
    'CSX': (-3, '運輸成本升'), 'NSC': (-2, '運輸受油價壓'),
    'NEE': (-4, '公用事業連續走弱，利率敏感'), 'ETR': (-3, '公用事業走弱'),
    'VST': (-3, '公用事業回落'), 'CEG': (-3, '公用事業回落'),
    'AMAT': (-4, 'sell-the-news＋中國風險'), 'COIN': (-4, '加密走弱'),
    'GSAT': (-8, '被收購價格封頂'), 'CCJ': (-2, '鈾股8/28重挫-5.9%'),
    'LLY': (-2, 'GLP-1報銷疑慮'),
    'IREN': (-3, '8/28重挫-12.5%'), 'AXTI': (-3, '8/28重挫-12.4%'),
}

best = {}
for f, key in FILES:
    for r in json.load(open(f))['rows']:
        t = r['ticker']
        e = best.setdefault(t, {'rows': [], 'online': 0})
        e['rows'].append(r)
        if r[key] in ONLINE:
            e['online'] += 1

def pick(rows, k):
    vals = [r.get(k) for r in rows if r.get(k) is not None]
    return vals[0] if vals else None

out = {}
for t, e in best.items():
    rows = e['rows']
    off = min((r.get('off_high_pct') for r in rows if r.get('off_high_pct') is not None), default=50)
    above_low = max((r.get('above_low_pct') or 0) for r in rows)
    a200 = any(r.get('above_ma200') for r in rows)
    a50 = any(r.get('above_ma50') for r in rows)
    c1 = pick(rows, 'chg_1m'); c6 = pick(rows, 'chg_6m'); c1y = pick(rows, 'chg_1y')
    vr = pick(rows, 'vol_ratio')
    why = []

    trend = 0
    if a200: trend += 15; 
    if a50: trend += 10
    if trend == 0 and above_low >= 30 and off <= 20:
        trend = 18
    if trend >= 20: why.append('趨勢完整')

    prox = max(0, 20 * (1 - min(off, 25) / 25))
    if off <= 6: why.append(f'距高僅{off:.0f}%')

    tight = 0
    if c1 is not None:
        tight = max(0, 15 * (1 - min(abs(c1), 15) / 15))
        if abs(c1) <= 5: why.append('月線緊縮')
    else:
        tight = 7

    youth = 0
    if c6 is not None and c6 >= 12 and (c1y is None or c1y <= 100):
        youth = 15; why.append('升勢年輕')
    elif c1y is not None and 10 <= c1y <= 100:
        youth = 10
    elif c1y is not None and c1y > 150:
        youth = 0; why.append('漲幅已大')
    else:
        youth = 5

    vol = 0
    if isinstance(vr, (int, float)):
        vol = 10 if vr < 0.7 else (6 if vr < 0.95 else 0)
        if vr < 0.7: why.append('明顯量縮')

    cons = 5 * e['online']
    if e['online'] == 3: why.append('三榜共識')
    elif e['online'] == 2: why.append('兩榜共識')

    adj, tag = CATALYST.get(t, (0, ''))
    if tag: why.insert(0, tag)

    score = max(0, min(100, trend + prox + tight + youth + vol + cons + adj))
    out[t] = {'score': round(score, 1), 'why': '、'.join(why[:3])}

json.dump(out, open('rank_overlay.json', 'w'), ensure_ascii=False, indent=1)
json.dump({t: {'pts': p, 'reason': w} for t, (p, w) in CATALYST.items()},
          open('catalysts.json', 'w'), ensure_ascii=False, indent=1)
top = sorted(out.items(), key=lambda kv: -kv[1]['score'])[:25]
for t, v in top:
    print(f"{t:<6}{v['score']:>6.1f}  {v['why']}")
