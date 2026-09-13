"""
services/candle_sniper_engine.py
==================================
9 Quant Equation Framework — tuned for ESTABLISHED, HIGH-CAP tokens.

Target tokens: FARTCOIN, WIF, BONK, POPCAT, PEPE, JUP, etc.
These are NOT new launches. They have:
  - $1M+ liquidity
  - $50M–$1B+ market cap
  - Months/years of price history
  - Active trading on major DEXes (Raydium, Orca, etc.)

The signal we are looking for: SHORT-TERM MOMENTUM OPPORTUNITIES —
volume surges, price breakouts, buy pressure imbalances, and trend
alignment that suggest a favorable entry for a short-to-medium hold.

Equations are tuned for liquid assets, NOT for new launch mechanics.
Age filtering is NOT used (these tokens are already established).

Each equation returns:
  {
    "name":   str,
    "passed": bool,
    "score":  float,   # 0–weight contribution to composite
    "weight": int,
    "reason": str,
  }
"""

import logging

logger = logging.getLogger(__name__)

# ── Equation Weights (sum = 100) ───────────────────────────────────────────────
EQUATION_WEIGHTS: dict[str, int] = {
    "volume_spike":          20,   # h1 vol vs 24h baseline — is volume surging?
    "dip_recovery":          15,   # pulled back then m5 reversing — entry point signal
    "buy_pressure_surge":    15,   # buy txn ratio — are buyers stepping in?
    "breakout_signal":       12,   # price breaking above recent range
    "liquidity_depth":       12,   # deep enough to absorb without slippage
    "volume_to_mcap_ratio":  10,   # % of market cap traded in 1h — opportunity size
    "market_cap_tier":        8,   # established token vs micro-cap reliability
    "price_momentum":         5,   # short-term price direction (used as tiebreaker)
    "trade_frequency_spike":  3,   # txn count spike — urgency/FOMO signal
}
assert sum(EQUATION_WEIGHTS.values()) == 100

# ── Strategy Profiles ─────────────────────────────────────────────────────────
# 6 tiers from blue-chip safe to full degen micro-cap.
# Floor ladder (mcap): $50M → $2M → $500k → $200k → $75k → $20k
STRATEGY_PROFILES: dict[str, dict] = {
    # Blue chip only. $50M+ mcap. Wait for textbook setups.
    "safe": {
        "min_confirmations":    5,
        "confidence_threshold": 65,
        "min_liquidity_usd":    800_000,     # $800k+ liq
        "min_market_cap":       50_000_000,  # $50M+ mcap
        "min_volume_h1":        80_000,      # $80k+ h1 vol
        "require_positive_h6":  True,
    },
    # Established tokens. $2M+ mcap. Strong signal required.
    "conservative": {
        "min_confirmations":    4,
        "confidence_threshold": 52,
        "min_liquidity_usd":    300_000,     # $300k+ liq
        "min_market_cap":       2_000_000,   # $2M+ mcap
        "min_volume_h1":        20_000,      # $20k+ h1 vol
        "require_positive_h6":  True,
    },
    # Default. $500k+ mcap. Good mix of opportunity vs risk.
    "balanced": {
        "min_confirmations":    3,
        "confidence_threshold": 38,
        "min_liquidity_usd":    100_000,     # $100k+ liq
        "min_market_cap":       500_000,     # $500k+ mcap
        "min_volume_h1":        5_000,       # $5k+ h1 vol
        "require_positive_h6":  False,
    },
    # Mid-range tokens. $200k+ mcap. More trades, more noise.
    "active": {
        "min_confirmations":    2,
        "confidence_threshold": 28,
        "min_liquidity_usd":    50_000,      # $50k+ liq
        "min_market_cap":       200_000,     # $200k+ mcap
        "min_volume_h1":        2_000,       # $2k+ h1 vol
        "require_positive_h6":  False,
    },
    # Emerging tokens. $75k+ mcap. Early signals, higher risk.
    "aggressive": {
        "min_confirmations":    2,
        "confidence_threshold": 16,
        "min_liquidity_usd":    20_000,      # $20k+ liq
        "min_market_cap":        75_000,     # $75k+ mcap
        "min_volume_h1":          800,       # $800 h1 vol
        "require_positive_h6":  False,
    },
    # Micro-cap degen. $20k+ mcap. Max trades, max risk.
    "degen": {
        "min_confirmations":    1,
        "confidence_threshold": 8,
        "min_liquidity_usd":    5_000,       # $5k+ liq
        "min_market_cap":       20_000,      # $20k+ mcap
        "min_volume_h1":          200,       # $200 h1 vol
        "require_positive_h6":  False,
    },
}

# Discovery is now driven dynamically from pump.fun's market cap leaderboard.
# See services/candle_sniper_service.discover_pumpfun_candidates().


# ─────────────────────────────────────────────────────────────────────────────
# Equation 1 — Volume Spike
# Current h1 volume vs the 24h hourly average.
# For established tokens, a 2x+ spike vs baseline is a strong signal.
# ─────────────────────────────────────────────────────────────────────────────
def eq_volume_spike(token: dict) -> dict:
    weight  = EQUATION_WEIGHTS["volume_spike"]
    vol_h1  = float(token.get("volume_h1")  or 0)
    vol_h24 = float(token.get("volume_h24") or 0)

    avg_hourly = vol_h24 / 24 if vol_h24 > 0 else 0
    if avg_hourly <= 0:
        return _eq_result("volume_spike", False, 0, weight, "No h24 volume baseline")

    ratio = vol_h1 / avg_hourly

    if ratio >= 5.0:
        return _eq_result("volume_spike", True, weight, weight,
                          f"Massive volume spike: {ratio:.1f}x baseline (${vol_h1:,.0f} h1)")
    if ratio >= 3.0:
        return _eq_result("volume_spike", True, round(weight * 0.80), weight,
                          f"Strong volume spike: {ratio:.1f}x baseline (${vol_h1:,.0f} h1)")
    if ratio >= 2.0:
        return _eq_result("volume_spike", True, round(weight * 0.55), weight,
                          f"Moderate volume spike: {ratio:.1f}x baseline (${vol_h1:,.0f} h1)")
    if ratio >= 1.3:
        return _eq_result("volume_spike", True, round(weight * 0.25), weight,
                          f"Mild volume increase: {ratio:.1f}x baseline")
    return _eq_result("volume_spike", False, 0, weight,
                      f"No volume spike: {ratio:.1f}x baseline — normal activity")


# ─────────────────────────────────────────────────────────────────────────────
# Equation 2 — Price Momentum
# Are all timeframes showing upward price movement?
# For trading established tokens we want aligned momentum, not just a blip.
# ─────────────────────────────────────────────────────────────────────────────
def eq_price_momentum(token: dict) -> dict:
    weight = EQUATION_WEIGHTS["price_momentum"]  # tiebreaker — 5 pts
    pc_m5  = float(token.get("price_change_m5")  or 0)
    pc_h1  = float(token.get("price_change_h1")  or 0)
    pc_h6  = float(token.get("price_change_h6")  or 0)

    positives = sum(1 for x in [pc_m5, pc_h1, pc_h6] if x > 0)
    strong    = sum(1 for x in [pc_m5, pc_h1, pc_h6] if x > 3)

    if positives == 3 and strong >= 2:
        return _eq_result("price_momentum", True, weight, weight,
                          f"Strong aligned momentum: m5 {pc_m5:+.1f}% h1 {pc_h1:+.1f}% h6 {pc_h6:+.1f}%")
    if positives == 3:
        return _eq_result("price_momentum", True, round(weight * 0.7), weight,
                          f"All timeframes positive: m5 {pc_m5:+.1f}% h1 {pc_h1:+.1f}% h6 {pc_h6:+.1f}%")
    if positives == 2 and pc_h1 > 0:
        return _eq_result("price_momentum", True, round(weight * 0.45), weight,
                          f"Partial momentum: h1 {pc_h1:+.1f}% positive")
    if pc_h1 > 2 and pc_m5 > 0:
        return _eq_result("price_momentum", True, round(weight * 0.25), weight,
                          f"Early move: m5 {pc_m5:+.1f}% h1 {pc_h1:+.1f}%")
    return _eq_result("price_momentum", False, 0, weight,
                      f"No consistent momentum: m5 {pc_m5:+.1f}% h1 {pc_h1:+.1f}% h6 {pc_h6:+.1f}%")


# ─────────────────────────────────────────────────────────────────────────────
# Equation 3 — Breakout Signal
# Has price broken meaningfully above the h6 baseline?
# A breakout on an established token often has strong follow-through.
# Proxy: h1 change is meaningfully positive relative to h6 change.
# ─────────────────────────────────────────────────────────────────────────────
def eq_breakout_signal(token: dict) -> dict:
    weight = EQUATION_WEIGHTS["breakout_signal"]
    pc_h1  = float(token.get("price_change_h1")  or 0)
    pc_h6  = float(token.get("price_change_h6")  or 0)
    pc_h24 = float(token.get("price_change_h24") or 0)
    pc_m5  = float(token.get("price_change_m5")  or 0)

    # Breakout: h1 is outperforming h6 significantly AND m5 is still positive
    # This means price broke upward recently and hasn't reversed yet
    h1_vs_h6   = pc_h1 - (pc_h6 / 6)    # h1 vs expected if h6 were linear
    fresh_break = pc_h1 > 5 and pc_m5 > 0 and pc_h24 < pc_h1 * 3

    if fresh_break and h1_vs_h6 > 5:
        return _eq_result("breakout_signal", True, weight, weight,
                          f"Strong breakout: h1 {pc_h1:+.1f}% outperforming h6 trend, m5 still positive")
    if pc_h1 > 3 and pc_m5 > 0 and h1_vs_h6 > 2:
        return _eq_result("breakout_signal", True, round(weight * 0.7), weight,
                          f"Moderate breakout: h1 {pc_h1:+.1f}% vs h6 {pc_h6:+.1f}%")
    if pc_h1 > 1.5 and pc_m5 > 0:
        return _eq_result("breakout_signal", True, round(weight * 0.35), weight,
                          f"Early breakout attempt: h1 {pc_h1:+.1f}% m5 {pc_m5:+.1f}%")
    return _eq_result("breakout_signal", False, 0, weight,
                      f"No breakout: h1 {pc_h1:+.1f}% m5 {pc_m5:+.1f}%")


# ─────────────────────────────────────────────────────────────────────────────
# Equation 4 — Buy Pressure Surge
# Is the buy/sell ratio significantly above 50% in the last hour?
# On established tokens, a buy ratio surge above 65–70% is meaningful.
# ─────────────────────────────────────────────────────────────────────────────
def eq_buy_pressure_surge(token: dict) -> dict:
    weight   = EQUATION_WEIGHTS["buy_pressure_surge"]
    buys_h1  = int(token.get("buys_h1")  or 0)
    sells_h1 = int(token.get("sells_h1") or 0)
    total    = buys_h1 + sells_h1

    if total < 5:
        return _eq_result("buy_pressure_surge", False, 0, weight,
                          f"Insufficient h1 activity ({total} txns) to gauge pressure")

    ratio = buys_h1 / total

    if ratio >= 0.75:
        return _eq_result("buy_pressure_surge", True, weight, weight,
                          f"Dominant buy pressure: {ratio*100:.0f}% buys ({buys_h1}/{total} txns)")
    if ratio >= 0.65:
        return _eq_result("buy_pressure_surge", True, round(weight * 0.75), weight,
                          f"Strong buy pressure: {ratio*100:.0f}% buys")
    if ratio >= 0.58:
        return _eq_result("buy_pressure_surge", True, round(weight * 0.45), weight,
                          f"Moderate buy lean: {ratio*100:.0f}% buys")
    if ratio >= 0.50:
        return _eq_result("buy_pressure_surge", True, round(weight * 0.15), weight,
                          f"Slight buy majority: {ratio*100:.0f}% buys")
    return _eq_result("buy_pressure_surge", False, 0, weight,
                      f"Sell pressure dominates: only {ratio*100:.0f}% buys ({buys_h1}/{total})")


# ─────────────────────────────────────────────────────────────────────────────
# Equation 5 — Liquidity Depth
# Is liquidity deep enough for a trade to execute with minimal slippage?
# Established tokens should have $500k+ to trade cleanly.
# ─────────────────────────────────────────────────────────────────────────────
def eq_liquidity_depth(token: dict) -> dict:
    weight  = EQUATION_WEIGHTS["liquidity_depth"]
    liq_usd = float(token.get("liquidity_usd") or 0)

    if liq_usd >= 5_000_000:
        return _eq_result("liquidity_depth", True, weight, weight,
                          f"Deep liquidity: ${liq_usd:,.0f} — minimal slippage")
    if liq_usd >= 1_000_000:
        return _eq_result("liquidity_depth", True, round(weight * 0.85), weight,
                          f"Strong liquidity: ${liq_usd:,.0f}")
    if liq_usd >= 500_000:
        return _eq_result("liquidity_depth", True, round(weight * 0.65), weight,
                          f"Good liquidity: ${liq_usd:,.0f}")
    if liq_usd >= 100_000:
        return _eq_result("liquidity_depth", True, round(weight * 0.35), weight,
                          f"Acceptable liquidity: ${liq_usd:,.0f}")
    return _eq_result("liquidity_depth", False, 0, weight,
                      f"Thin liquidity: ${liq_usd:,.0f} — slippage risk")


# ─────────────────────────────────────────────────────────────────────────────
# Equation 6 — Market Cap Tier
# Higher market cap = more established, less manipulable, more reliable signals.
# ─────────────────────────────────────────────────────────────────────────────
def eq_market_cap_tier(token: dict) -> dict:
    weight = EQUATION_WEIGHTS["market_cap_tier"]
    mcap   = float(token.get("market_cap") or 0)

    if mcap >= 1_000_000_000:
        return _eq_result("market_cap_tier", True, weight, weight,
                          f"Blue chip: ${mcap/1e9:.1f}B market cap")
    if mcap >= 500_000_000:
        return _eq_result("market_cap_tier", True, round(weight * 0.85), weight,
                          f"Large cap: ${mcap/1e6:.0f}M market cap")
    if mcap >= 100_000_000:
        return _eq_result("market_cap_tier", True, round(weight * 0.70), weight,
                          f"Mid cap: ${mcap/1e6:.0f}M market cap")
    if mcap >= 50_000_000:
        return _eq_result("market_cap_tier", True, round(weight * 0.55), weight,
                          f"Small-mid cap: ${mcap/1e6:.0f}M market cap")
    if mcap >= 10_000_000:
        return _eq_result("market_cap_tier", True, round(weight * 0.35), weight,
                          f"Small cap: ${mcap/1e6:.0f}M")
    if mcap >= 1_000_000:
        return _eq_result("market_cap_tier", True, round(weight * 0.20), weight,
                          f"Micro cap: ${mcap/1e6:.1f}M — speculative")
    if mcap >= 100_000:
        return _eq_result("market_cap_tier", True, round(weight * 0.08), weight,
                          f"Nano cap: ${mcap/1e3:.0f}k — high risk")
    return _eq_result("market_cap_tier", False, 0, weight,
                      f"No market cap data or below $100k")


# ─────────────────────────────────────────────────────────────────────────────
# Equation 7 — Volume to Market Cap Ratio
# Unusually high volume relative to market cap signals a live trading opportunity.
# For a $500M token, $50M+ in 1h volume is a major event worth trading.
# ─────────────────────────────────────────────────────────────────────────────
def eq_volume_to_mcap_ratio(token: dict) -> dict:
    weight = EQUATION_WEIGHTS["volume_to_mcap_ratio"]
    vol_h1 = float(token.get("volume_h1") or 0)
    mcap   = float(token.get("market_cap") or 0)

    if mcap <= 0:
        return _eq_result("volume_to_mcap_ratio", False, 0, weight, "No market cap data")

    # Express as % of market cap traded in 1 hour
    ratio_pct = (vol_h1 / mcap) * 100

    if ratio_pct >= 10:
        return _eq_result("volume_to_mcap_ratio", True, weight, weight,
                          f"Exceptional activity: {ratio_pct:.1f}% of market cap traded in 1h")
    if ratio_pct >= 5:
        return _eq_result("volume_to_mcap_ratio", True, round(weight * 0.80), weight,
                          f"High activity: {ratio_pct:.1f}% of mcap traded in 1h")
    if ratio_pct >= 2:
        return _eq_result("volume_to_mcap_ratio", True, round(weight * 0.55), weight,
                          f"Active: {ratio_pct:.1f}% of mcap traded in 1h")
    if ratio_pct >= 0.5:
        return _eq_result("volume_to_mcap_ratio", True, round(weight * 0.25), weight,
                          f"Normal: {ratio_pct:.1f}% of mcap traded in 1h")
    return _eq_result("volume_to_mcap_ratio", False, 0, weight,
                      f"Quiet: {ratio_pct:.2f}% of mcap traded in 1h — low opportunity")


# ─────────────────────────────────────────────────────────────────────────────
# Equation 2 (reordered) — Dip Recovery (Entry Point Detection)
# This is the core signal for WHEN to enter. We want tokens that have pulled
# back from a recent high (h6 or h24 negative = in a dip) but are showing
# early recovery signs on m5 with buy pressure returning. This is the exact
# pattern of a low-risk entry before the next leg up.
# ─────────────────────────────────────────────────────────────────────────────
def eq_dip_recovery(token: dict) -> dict:
    weight   = EQUATION_WEIGHTS["dip_recovery"]
    pc_m5    = float(token.get("price_change_m5")  or 0)
    pc_h1    = float(token.get("price_change_h1")  or 0)
    pc_h6    = float(token.get("price_change_h6")  or 0)
    pc_h24   = float(token.get("price_change_h24") or 0)
    buys_m5  = int(token.get("buys_m5")  or 0)
    sells_m5 = int(token.get("sells_m5") or 0)

    # Token is in a dip if h6 or h24 is negative
    in_dip   = pc_h6 < -2 or pc_h24 < -5
    # Recovery: m5 going positive
    m5_up    = pc_m5 > 0
    # Buy pressure returning in last 5 minutes
    buys_returning = buys_m5 >= sells_m5 and buys_m5 > 0

    # Best signal: token dipped AND m5 strongly reversing with buyers
    if in_dip and m5_up and buys_returning and pc_m5 > 2:
        return _eq_result("dip_recovery", True, weight, weight,
                          f"Strong dip entry: h6 {pc_h6:+.1f}% h24 {pc_h24:+.1f}% → m5 +{pc_m5:.1f}% buyers back")
    # Good signal: dipping but m5 starting to recover
    if in_dip and m5_up and buys_returning:
        return _eq_result("dip_recovery", True, round(weight * 0.75), weight,
                          f"Dip recovery starting: h24 {pc_h24:+.1f}% → m5 {pc_m5:+.1f}%")
    # Moderate: dipping and m5 positive, no confirmation from buys yet
    if in_dip and m5_up:
        return _eq_result("dip_recovery", True, round(weight * 0.40), weight,
                          f"Possible dip recovery: m5 {pc_m5:+.1f}% after {pc_h6:+.1f}% h6 dip")
    # Mild: sideways/consolidating (h1 near 0) — often precedes a breakout
    if abs(pc_h1) < 2 and m5_up and buys_returning:
        return _eq_result("dip_recovery", True, round(weight * 0.20), weight,
                          f"Consolidation entry: h1 {pc_h1:+.1f}% m5 {pc_m5:+.1f}% — tight range")
    return _eq_result("dip_recovery", False, 0, weight,
                      f"No entry signal: h6 {pc_h6:+.1f}% h24 {pc_h24:+.1f}% m5 {pc_m5:+.1f}%")


# ─────────────────────────────────────────────────────────────────────────────
# Equation 9 — Trade Frequency Spike
# Is the number of transactions per hour unusually high?
# For established tokens, a txn spike above 2x baseline signals urgency/FOMO.
# ─────────────────────────────────────────────────────────────────────────────
def eq_trade_frequency_spike(token: dict) -> dict:
    weight   = EQUATION_WEIGHTS["trade_frequency_spike"]
    txns_h1  = int(token.get("buys_h1") or 0) + int(token.get("sells_h1") or 0)
    txns_h24 = int(token.get("buys_h24") or 0) + int(token.get("sells_h24") or 0)

    avg_hourly = txns_h24 / 24 if txns_h24 > 0 else 0
    if avg_hourly <= 0:
        return _eq_result("trade_frequency_spike", False, 0, weight, "No h24 txn baseline")

    ratio = txns_h1 / avg_hourly

    if ratio >= 3.0:
        return _eq_result("trade_frequency_spike", True, weight, weight,
                          f"Trade frequency {ratio:.1f}x above baseline ({txns_h1} txns in h1) — high urgency")
    if ratio >= 2.0:
        return _eq_result("trade_frequency_spike", True, round(weight * 0.7), weight,
                          f"Trade frequency {ratio:.1f}x above baseline ({txns_h1} txns in h1)")
    if ratio >= 1.4:
        return _eq_result("trade_frequency_spike", True, round(weight * 0.35), weight,
                          f"Slightly elevated txn rate: {ratio:.1f}x baseline")
    return _eq_result("trade_frequency_spike", False, 0, weight,
                      f"Normal txn rate: {ratio:.1f}x baseline ({txns_h1} txns in h1)")


# ── Composite Scoring Engine ───────────────────────────────────────────────────

EQUATION_FUNCTIONS = [
    eq_volume_spike,
    eq_dip_recovery,
    eq_buy_pressure_surge,
    eq_breakout_signal,
    eq_liquidity_depth,
    eq_volume_to_mcap_ratio,
    eq_market_cap_tier,
    eq_price_momentum,
    eq_trade_frequency_spike,
]


def score_candidate(token: dict, min_confirmations: int = 5) -> dict:
    """
    Run all 9 quant equations against a token and return composite result.
    """
    results      = []
    total_score  = 0.0
    passed_count = 0
    debug_lines  = []

    for eq_fn in EQUATION_FUNCTIONS:
        try:
            result = eq_fn(token)
        except Exception as exc:
            logger.warning(f"Equation {eq_fn.__name__} error on {token.get('address','?')[:8]}: {exc}")
            result = _eq_result(eq_fn.__name__, False, 0,
                                EQUATION_WEIGHTS.get(eq_fn.__name__, 0), f"Error: {exc}")

        results.append(result)
        total_score  += result["score"]
        if result["passed"]:
            passed_count += 1

        status = "✅" if result["passed"] else "❌"
        debug_lines.append(
            f"{status} {result['name'].replace('_',' ').title()}: "
            f"{result['score']:.0f}/{result['weight']} — {result['reason']}"
        )

    composite     = round(min(total_score, 100), 1)
    passed_thresh = passed_count >= min_confirmations

    return {
        "composite_score":  composite,
        "equations_passed": passed_count,
        "equations_failed": len(results) - passed_count,
        "equations":        results,
        "passed_threshold": passed_thresh,
        "rating":           _rating(composite),
        "debug_lines":      debug_lines,
    }


def apply_profile_filters(token: dict, profile: str) -> tuple[bool, str]:
    """
    Hard filters for the given strategy profile.
    Returns (passes: bool, reason: str).
    Age is NOT filtered — these are established tokens.
    """
    cfg    = STRATEGY_PROFILES.get(profile, STRATEGY_PROFILES["balanced"])
    liq    = float(token.get("liquidity_usd") or 0)
    vol_h1 = float(token.get("volume_h1")     or 0)
    mcap   = float(token.get("market_cap")    or 0)
    pc_h6  = float(token.get("price_change_h6") or 0)

    if liq < cfg["min_liquidity_usd"]:
        return False, f"Liq ${liq:,.0f} < ${cfg['min_liquidity_usd']:,.0f} required"
    if mcap > 0 and mcap < cfg["min_market_cap"]:
        return False, f"MCap ${mcap/1e6:.0f}M < ${cfg['min_market_cap']/1e6:.0f}M required"
    if vol_h1 < cfg["min_volume_h1"]:
        return False, f"Vol h1 ${vol_h1:,.0f} < ${cfg['min_volume_h1']:,.0f} required"
    if cfg.get("require_positive_h6") and pc_h6 <= 0:
        return False, f"h6 price change {pc_h6:+.1f}% must be positive (conservative mode)"
    return True, "Profile filters passed"


# ── Internal Helpers ──────────────────────────────────────────────────────────

def _eq_result(name: str, passed: bool, score: float, weight: int, reason: str) -> dict:
    return {"name": name, "passed": passed, "score": float(score),
            "weight": weight, "reason": reason}


def _rating(score: float) -> str:
    if score >= 80: return "🟢 STRONG"
    if score >= 65: return "🟡 GOOD"
    if score >= 50: return "🟠 MODERATE"
    if score >= 35: return "🔴 WEAK"
    return "⚫ VERY WEAK"
