"""
services/sniper_score_service.py
=================================
BRAINROT Sniper Score engine.
Score range: 0 – 100.  Higher = stronger candidate.

Factors: liquidity + volume + buy pressure + age + activity,
plus settings-match weighting and fit notes.
"""

from typing import Optional
from utils.config import settings

def _strategy_bonus(token: dict, strategy_mode: str) -> tuple[int, list[str]]:
    """
    Behavior-detection scoring bonus for Degen Fire sub-strategies.
    Returns (bonus_points capped at 40, list of signal labels).

    Signals are derived from live token data — either real DexScreener
    values or synthetic values built from the PumpPortal feed event.
    """
    if not strategy_mode or strategy_mode == "none":
        return 0, []

    liq       = float(token.get("liquidity_usd", 0))
    vol       = float(token.get("volume_h1") or token.get("volume_h24") or 0)
    buys      = int(token.get("buys_h1", 0))
    sells     = int(token.get("sells_h1", 0))
    age       = float(token.get("age_minutes") or 0)
    mcap      = float(token.get("market_cap") or 0)
    dex       = str(token.get("dex") or "").lower()
    total     = buys + sells
    buy_ratio = buys / total if total > 0 else 0
    buy_rate  = buys / min(max(age, 0.5), 60.0)   # buys per minute (capped at 60min window for established tokens)

    bonus   = 0
    signals = []

    if strategy_mode == "volume_spike":
        # ── Vol/Liq spike ratio ────────────────────────────────────────────
        if liq > 0:
            ratio = vol / liq
            if ratio >= 10:
                bonus += 30; signals.append("🔥 Extreme volume spike (10x+ vol/liq)")
            elif ratio >= 5:
                bonus += 22; signals.append("📈 Strong volume spike (5x vol/liq)")
            elif ratio >= 3:
                bonus += 14; signals.append("📈 Volume surge (3x vol/liq)")
        # ── Panic buy velocity ─────────────────────────────────────────────
        if buy_rate >= 20:
            bonus += 20; signals.append("😱 Panic buy rate — 20+ buys/min")
        elif buy_rate >= 10:
            bonus += 12; signals.append("⚡ Fast buy velocity — 10+ buys/min")
        elif buy_rate >= 5:
            bonus += 6
        # ── Extreme buy ratio ──────────────────────────────────────────────
        if buy_ratio >= 0.85:
            bonus += 15; signals.append("💚 Extreme buy dominance (85%+)")
        elif buy_ratio >= 0.70:
            bonus += 8

    elif strategy_mode == "graduate_hunter":
        # ── Graduation confirmation: on a real DEX with real liq ──────────
        if dex and dex not in ("pumpfun", "") and liq >= 5_000:
            bonus += 30; signals.append("🎓 DEX graduation confirmed — real liquidity")
        elif liq >= 10_000:
            bonus += 20; signals.append("💧 Strong post-graduation liquidity")
        elif liq >= 5_000:
            bonus += 12
        # ── Post-graduation market cap ─────────────────────────────────────
        if mcap >= 80_000:
            bonus += 15; signals.append("📊 Market cap past graduation threshold")
        elif mcap >= 40_000:
            bonus += 8
        # ── Fresh graduate time window ─────────────────────────────────────
        if 0 < age <= 15:
            bonus += 10; signals.append("🚀 Fresh graduate — early entry window")
        elif age <= 30:
            bonus += 5

    elif strategy_mode == "micro_cap_sweep":
        # ── Micro-cap market size ──────────────────────────────────────────
        if 0 < mcap <= 5_000:
            bonus += 30; signals.append("🔬 Ultra micro-cap sweep target (<$5k)")
        elif mcap <= 15_000:
            bonus += 22; signals.append("🔬 Micro-cap sweep zone (<$15k)")
        elif mcap <= 30_000:
            bonus += 12; signals.append("🔬 Small cap sweep range (<$30k)")
        # ── Whale sweep pattern: high ratio + concentrated buys ────────────
        if buy_ratio >= 0.85 and buys >= 3:
            bonus += 18; signals.append("🐋 Whale sweep pattern (85%+ ratio)")
        elif buy_ratio >= 0.70 and buys >= 2:
            bonus += 10; signals.append("🐋 Sweep entry pattern")
        # ── High initial buy vs micro market cap ───────────────────────────
        if vol > 0 and mcap > 0 and vol / mcap >= 0.5:
            bonus += 10; signals.append("💥 Large buy relative to market cap")

    elif strategy_mode == "smart_project":
        # ── Proven project: rewards age, market cap, and 24h momentum ─────────
        # Calibrated for established tokens (30+ day, $120k+ mcap, +5% 24h)
        chg_h24 = float(token.get("price_change_h24") or 0)
        if age is not None and age >= 30 * 24 * 60:
            bonus += 20; signals.append("⏰ 30+ day proven project")
        elif age is not None and age >= 7 * 24 * 60:
            bonus += 10; signals.append("⏰ Established (7+ days)")
        if mcap >= 500_000:
            bonus += 20; signals.append("📊 $500k+ market cap")
        elif mcap >= 200_000:
            bonus += 15; signals.append("📊 $200k+ market cap")
        elif mcap >= 120_000:
            bonus += 10; signals.append("📊 $120k+ market cap")
        if chg_h24 >= 20:
            bonus += 15; signals.append(f"📈 Strong growth +{chg_h24:.0f}% 24h")
        elif chg_h24 >= 10:
            bonus += 10; signals.append(f"📈 Good growth +{chg_h24:.0f}% 24h")
        elif chg_h24 >= 5:
            bonus += 5;  signals.append(f"📈 Positive growth +{chg_h24:.0f}% 24h")
        # Absolute volume — not vol/liq ratio (established tokens have deep liq)
        if vol >= 50_000:
            bonus += 10; signals.append("💰 High 1h volume")
        elif vol >= 20_000:
            bonus += 6
        elif vol >= 5_000:
            bonus += 3

    elif strategy_mode == "panic_ride":
        # ── Extreme buy ratio (core panic signal) ──────────────────────────
        if buy_ratio >= 0.90 and total >= 15:
            bonus += 35; signals.append("😱 PANIC BUY — 90%+ buy ratio confirmed")
        elif buy_ratio >= 0.85 and total >= 10:
            bonus += 25; signals.append("🔥 Heavy panic momentum (85%+ ratio)")
        elif buy_ratio >= 0.80 and total >= 8:
            bonus += 15; signals.append("⚡ Panic buying building")
        # ── FOMO frenzy: ultra-fresh + many buys ──────────────────────────
        if age <= 3 and buys >= 20:
            bonus += 25; signals.append("⚡ FOMO frenzy — fresh + heavy buying")
        elif age <= 5 and buys >= 10:
            bonus += 14; signals.append("⚡ Fast FOMO entry signal")
        # ── Buy velocity ───────────────────────────────────────────────────
        if buy_rate >= 15:
            bonus += 15; signals.append("🚀 Extreme buy velocity — 15+ buys/min")
        elif buy_rate >= 8:
            bonus += 8

    return min(bonus, 40), signals


def _rating(score: int) -> str:
    if score >= 80: return "🟢 STRONG"
    if score >= 60: return "🟡 GOOD"
    if score >= 40: return "🟠 MODERATE"
    if score >= 20: return "🔴 WEAK"
    return "⚫ VERY WEAK"


def score_token(
    token: dict,
    user_settings: dict,
) -> dict:
    """
    Calculate the Sniper Score for a token.
    Returns dict: score, rating, risk_notes, summary, premium_notes.
    """
    liq   = float(token.get("liquidity_usd", 0))
    vol   = float(token.get("volume_h1") or token.get("volume_h24") or 0)
    buys  = int(token.get("buys_h1", 0))
    sells = int(token.get("sells_h1", 0))
    age   = token.get("age_minutes")

    score      = 0
    risk_notes = []

    # ── Liquidity (0-30 pts) ───────────────────────────────────────────────────
    if liq >= 50_000:   score += 30
    elif liq >= 10_000: score += 22
    elif liq >= 5_000:  score += 15
    elif liq >= 2_000:  score += 8
    elif liq >= 500:    score += 3
    else:               risk_notes.append("Very low liquidity — high slippage risk")

    # ── Volume (0-20 pts) ──────────────────────────────────────────────────────
    if vol >= 100_000:   score += 20
    elif vol >= 50_000:  score += 15
    elif vol >= 10_000:  score += 10
    elif vol >= 2_000:   score += 5
    elif vol >= 500:     score += 2

    # ── Buy pressure (0-20 pts) ────────────────────────────────────────────────
    total_txns = buys + sells
    if total_txns > 0:
        ratio = buys / total_txns
        if ratio >= 0.75:   score += 20
        elif ratio >= 0.60: score += 15
        elif ratio >= 0.50: score += 10
        elif ratio >= 0.40: score += 5
        else:               risk_notes.append("Sell pressure dominant")

    # ── Age freshness (0-15 pts) ───────────────────────────────────────────────
    # Both extremes are rewarded: ultra-fresh NEW tokens AND proven OLD tokens.
    # The dead zone (2h-7d) is where most rugs live.
    if age is not None:
        if age <= 5:                    score += 15   # ultra fresh launch
        elif age <= 15:                 score += 12   # very fresh
        elif age <= 30:                 score += 8    # fresh
        elif age <= 60:                 score += 4    # recent
        elif age <= 120:                score += 1    # 2h
        elif age >= 30 * 24 * 60:      score += 12   # 30+ days — proven project
        elif age >= 7  * 24 * 60:      score += 6    # 7+ days — established
        elif age >= 24 * 60:           score += 2    # 1+ day — survived first 24h
        # else: 2h-24h old — 0 pts (highest rug/dump risk window)
    if age is not None and age < 2:
        risk_notes.append("Extremely fresh — high risk/reward")

    # ── Transaction activity (0-15 pts) ───────────────────────────────────────
    if buys >= 200:     score += 15
    elif buys >= 100:   score += 12
    elif buys >= 50:    score += 8
    elif buys >= 20:    score += 5
    elif buys >= 10:    score += 2
    if buys < 5:        risk_notes.append("Very low buy count")

    # ── Bonding curve depth (pump.fun feed tokens only) ────────────────────────
    # vSolInBondingCurve is the actual SOL locked in the pump.fun bonding curve.
    # It's the strongest single signal for brand-new tokens — far better than
    # synthetic buys. We score it separately so it adds to (not replaces) base.
    curve_sol = float(token.get("v_sol_in_bonding_curve") or 0)
    if curve_sol > 0:
        if curve_sol >= 50:
            score += 20  # near graduation — very high interest
        elif curve_sol >= 20:
            score += 15
        elif curve_sol >= 5:
            score += 10
        elif curve_sol >= 1:
            score += 5
        else:
            risk_notes.append(f"Bonding curve near-empty ({curve_sol:.3f} SOL) — very early")

    # ── Risk checks ────────────────────────────────────────────────────────────
    strategy_mode = str(user_settings.get("strategy_mode") or "none") if user_settings else "none"
    # Micro-cap sweep: low liq is expected — suppress the noise warning
    if liq < 1_000 and strategy_mode != "micro_cap_sweep":
        risk_notes.append("Liquidity below safe threshold ($1k)")
    if buys > 0 and sells > buys * 2:
        risk_notes.append("High sell ratio vs buys")

    # ── Strategy behavior-detection bonus ──────────────────────────────────────
    strategy_bonus, strategy_signals = _strategy_bonus(token, strategy_mode)
    score += strategy_bonus

    score = min(100, max(0, score))
    rating = _rating(score)

    # ── Summary line ───────────────────────────────────────────────────────────
    if strategy_signals:
        summary = " · ".join(strategy_signals)
    elif score >= 70:
        summary = "Strong candidate — solid metrics across all factors."
    elif score >= 50:
        summary = "Moderate candidate — review metrics before entry."
    elif score >= 30:
        summary = "Weak signals — high caution recommended."
    else:
        summary = "Very weak — not recommended for automated entry."

    # ── Settings-fit notes ─────────────────────────────────────────────────────
    premium_notes: Optional[str] = None
    if user_settings:
        fit = []
        if liq >= user_settings.get("min_liquidity", 0) * 2:
            fit.append("✅ Strong liquidity fit")
        if buys >= user_settings.get("min_buys", 0) * 3:
            fit.append("✅ High buy activity match")
        if age is not None and age <= user_settings.get("max_token_age_minutes", 120) * 0.5:
            fit.append("✅ Fresh within age target")
        if user_settings.get("prioritize_fresh_launches") and age is not None and age <= 10:
            fit.append("🚀 Priority — fresh launch detected")
        if user_settings.get("prioritize_liquidity_strength") and liq >= 20_000:
            fit.append("💧 Priority — strong liquidity")
        if strategy_signals:
            fit = strategy_signals + fit   # lead with behavior signals
        premium_notes = " · ".join(fit) if fit else "Analysis complete — no exceptional matches"

    return {
        "score":         score,
        "rating":        rating,
        "risk_notes":    risk_notes,
        "summary":       summary,
        "premium_notes": premium_notes,
    }
