"""Offline tests for the VCP screener using synthetic price data."""

import numpy as np
import pandas as pd

from vcp_screener import analyze, find_contractions, is_contracting, trend_template


def make_df(closes: np.ndarray, vol: np.ndarray | None = None) -> pd.DataFrame:
    n = len(closes)
    idx = pd.bdate_range(end="2026-08-14", periods=n)
    if vol is None:
        vol = np.full(n, 1_000_000.0)
    return pd.DataFrame({
        "Open": closes,
        "High": closes * 1.005,
        "Low": closes * 0.995,
        "Close": closes,
        "Volume": vol,
    }, index=idx)


def synthetic_vcp(n: int = 400) -> pd.DataFrame:
    """Uptrend followed by successively shallower pullbacks with drying volume."""
    rng = np.random.default_rng(42)
    base = np.linspace(50, 100, n - 120)
    base *= 1 + rng.normal(0, 0.002, len(base))

    # Three contractions: -18%, -10%, -5%, each ~40/30/30 bars, recovering to prior high
    pattern = []
    level = base[-1]
    for depth, bars in [(0.18, 44), (0.10, 34), (0.05, 30)]:
        half = bars // 2
        down = level * (1 - depth * np.linspace(0, 1, half))
        up = level * (1 - depth * np.linspace(1, 0, bars - half))
        pattern.extend(down)
        pattern.extend(up)
    closes = np.concatenate([base, np.array(pattern)[:120]])

    vol = np.full(len(closes), 1_000_000.0)
    vol[-15:] = 500_000.0  # dry-up
    return make_df(closes, vol)


def test_trend_template_pass():
    df = synthetic_vcp()
    ok, info = trend_template(df)
    assert ok, info


def test_trend_template_fail_downtrend():
    closes = np.linspace(100, 50, 400)
    ok, _ = trend_template(make_df(closes))
    assert not ok


def test_contractions_detected_and_shrinking():
    df = synthetic_vcp()
    seq = is_contracting(find_contractions(df))
    assert len(seq) >= 2, [c.depth_pct for c in seq]
    depths = [c.depth_pct for c in seq]
    assert depths == sorted(depths, reverse=True) or all(
        b <= a * 1.15 for a, b in zip(depths, depths[1:])
    )


def test_analyze_scores_vcp_high():
    df = synthetic_vcp()
    res = analyze("TEST", df, max_off_high=25.0, min_contractions=2)
    assert res.passed_trend
    assert res.score >= 60, (res.score, res.notes, [c.depth_pct for c in res.contractions])
    assert res.volume_ratio < 0.8


def test_analyze_rejects_short_history():
    df = synthetic_vcp()[:100]
    res = analyze("SHORT", df, max_off_high=25.0, min_contractions=2)
    assert res.notes == "insufficient history"
    assert res.score == 0.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("All tests passed.")
