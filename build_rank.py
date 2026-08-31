#!/usr/bin/env python3
"""Compute the Page-D upside-readiness ranking (0-100) across all three lists.

Composite, applied uniformly to every ticker:
  trend 25 + pivot proximity 20 + tightness 15 + youth 15 + volume dry-up 10
  + cross-list consensus 15, then a bounded qualitative catalyst adjustment
  (±10) for events known this week. Emits rank_overlay.json {ticker: {score, why}}.
"""
import json

FILES = [('scan_R14_2026-08-31.json', 'category'),
         ('scan_stage_R7_2026-08-31.json', 'stage'),
         ('scan_PB-R7_2026-08-31.json', 'category')]
ONLINE = {'A_VCP待突破', 'E_突破延伸中', 'B_上升結構', '2A_初升段', '2B_主升段', '1轉2_轉強觀察'}

# Qualitative catalyst adjustments (my read of this week's events), bounded ±10.
CATALYST = {
    # 8/31 session: US-Iran strikes sent WTI above $90. Energy was the only
    # sector up; utilities and communication services led 10 of 11 sectors down;
    # oil-driven inflation revived Sept rate-hike odds.
    'EOG': (7, '8/31油價破$90，+6.8%'), 'TRGP': (5, '8/31 +3.9%，中游受惠'),
    'CVE': (4, '8/31 +2.6%'), 'FTI': (4, '8/31 +2.4%，油服走強'),
    'EQNR': (4, '8/31 +2.3%'), 'SU': (3, '8/31 +2.1%'), 'DINO': (3, '8/31煉油+2.1%'),
    'CVX': (3, '8/31 +1.6%，油價避險'), 'CNQ': (3, '8/31 +1.5%'), 'CHRD': (3, '8/31 +1.1%'),
    'TSLA': (5, '8/31 +5.5%領漲'), 'CRWD': (5, '8/31 +3.8%，財報後續強'),
    'CRM': (3, '財報+Anthropic合作'), 'ANET': (2, '前週單日+7.9%'),
    'MRNA': (3, '8/19癌症疫苗三期成功+177%，高位整理'),
    'AXON': (-5, '8/31 -5.3%'), 'TD': (-4, '8/31 -3.4%'),
    'GD': (-3, '8/31 -2.3%'), 'MRVL': (-4, '指引不如預期，8/31再-2.2%'),
    'UNP': (-3, '8/31 -2.2%，運輸受油價壓'), 'CSX': (-3, '8/31 -1.5%，運輸成本升'),
    'NSC': (-2, '運輸受油價壓'), 'GOOGL': (-3, '8/31 -2.5%，通訊服務最弱'),
    'AMZN': (-2, '8/31 -1.7%'), 'NEE': (-3, '公用事業最弱，利率敏感'),
    'ETR': (-3, '公用事業最弱'), 'VST': (-3, '公用事業回落'), 'CEG': (-3, '公用事業回落'),
    'AMAT': (-4, 'sell-the-news＋中國風險'), 'COIN': (-4, '加密走弱'),
    'GSAT': (-8, '被收購價格封頂'), 'CCJ': (-2, '鈾股8/28重挫-5.9%'),
    'LLY': (-2, 'GLP-1報銷疑慮'), 'CAT': (-3, '連日回落'),
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
