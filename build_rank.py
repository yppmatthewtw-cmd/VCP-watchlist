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

FILES = [('scan_R16_2026-09-02.json', 'category'),
         ('scan_stage_R9_2026-09-02.json', 'stage'),
         ('scan_PB-R9_2026-09-02.json', 'category')]
ONLINE = {'A_VCP待突破', 'E_突破延伸中', 'B_上升結構', '2A_初升段', '2B_主升段', '1轉2_轉強觀察'}
BASIS = '2026-09-01'

# Qualitative NEWS catalysts only: (pts, date, text). Text must not contain '、'.
NEWS = {
    'AMZN': (-3, '2026-09-01', 'FTC 訴訟'),
    'MRNA': (3, '2026-08-19', '癌症疫苗三期成功（8/19 +177%）；9/1 再 +9.9%'),
    'CRM':  (2, '2026-08-27', '財報＋Anthropic 合作'),
    'CRWD': (-2, '2026-09-01', '財報後漲幅回吐，科技板塊承壓'),
    'MRVL': (-4, '2026-08-28', '財報指引不如預期'),
    'AMAT': (-4, '2026-08-28', 'sell-the-news＋中國風險'),
    'GSAT': (-8, '2026-08-27', '被收購，價格封頂'),
    'LLY':  (-2, '2026-08-28', 'GLP-1 報銷疑慮'),
    'RUSHB': (0, '2026-08-31', '3:2 拆股（已調整）'),
    'CVX':  (2, '2026-09-01', '美伊衝突推升油價，能源避險'),
    'EOG':  (2, '2026-09-01', '油價破 $90'),
    'NVDA': (2, '2026-09-02', '9/2 領漲道指，AI 基建需求續強'),
    'JNJ':  (2, '2026-09-02', '9/2 與 NVDA 同為道指主要推手'),
}
MOVE_MIN = 3.0   # a |9/1 move| >= 3% is shown as a highlight (pts 0)

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
        print(f"WARNING catalyst sign vs official move: {t} pts {pts:+d} but 9/1 {mv:+.1f}%")

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

    move_txt = f'9/1 {mv:+.1f}%' if (mv is not None and abs(mv) >= MOVE_MIN) else ''
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
