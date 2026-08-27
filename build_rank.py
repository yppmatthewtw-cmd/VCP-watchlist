#!/usr/bin/env python3
"""Compute the Page-D upside-readiness ranking (0-100) across all three lists.

Composite, applied uniformly to every ticker:
  trend 25 + pivot proximity 20 + tightness 15 + youth 15 + volume dry-up 10
  + cross-list consensus 15, then a bounded qualitative catalyst adjustment
  (±10) for events known this week. Emits rank_overlay.json {ticker: {score, why}}.
"""
import json

FILES = [('scan_R10_2026-08-27.json', 'category'),
         ('scan_stage_R3_2026-08-27.json', 'stage'),
         ('scan_PB-R3_2026-08-27.json', 'category')]
ONLINE = {'A_VCP待突破', 'E_突破延伸中', 'B_上升結構', '2A_初升段', '2B_主升段', '1轉2_轉強觀察'}

# Qualitative catalyst adjustments (my read of this week's events), bounded ±10.
CATALYST = {
    'CRWD': (8, '財報大勝盤後+11%'), 'NVDA': (6, '財報+106%超預期'),
    'DELL': (4, 'AI伺服器動能強'), 'BLFS': (4, '突破52週高'), 'SNOW': (3, '貼頂強勢'),
    'BE': (3, '動能強'), 'BNS': (3, '創紀錄財報'), 'ROST': (2, '財報後走強'),
    'MRVL': (1, '8/27財報双面刃'), 'MU': (-2, 'NVDA漲價傳聞壓記憶體'),
    'GSAT': (-8, '被收購價格封頂'), 'PWR': (-5, '六連跌'), 'CCJ': (-4, '鈾族群賣壓'),
    'OXY': (-3, '油價逆風'), 'LLY': (-3, 'GLP-1報銷疑慮'), 'ENVA': (-3, '高檔回落'),
    'AXTI': (-4, '連續重挫'), 'CBRS': (-3, '持續回檔'),
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
top = sorted(out.items(), key=lambda kv: -kv[1]['score'])[:25]
for t, v in top:
    print(f"{t:<6}{v['score']:>6.1f}  {v['why']}")
