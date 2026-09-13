"""
utils/trade_presets.py
========================
Quick-apply trading presets for Auto-Buy.
All 6 presets enforce minimum bonding curve depth (min_initial_buy_sol)
so the bot never touches zero-traction tokens.

sniper_settings fields  → filter what the feed shows / scores
auto_buy_settings fields → how the auto-buyer fires trades
strategy_mode           → tells the score engine which signals to prioritise

Profit-only philosophy:
  - Never buy a token with < min_initial_buy_sol SOL in the bonding curve
  - Never buy below the score threshold — noisy signals cost money
  - Higher threshold + DexScreener lookup (threshold > 35) = real momentum data
  - Graduate hunter + volume spike = tokens making noise, not just new tokens
"""

TRADE_PRESETS: dict[str, dict] = {

    # ── 1. QUALITY SNIPE ─────────────────────────────────────────────────────
    # High-conviction only. Requires 0.5+ SOL in the curve — real money in.
    # Score 60+. Only 2 trades/hr. Slow but the highest win rate of any preset.
    # Best for: users who want fewer, safer trades.
    "quality_snipe": {
        "label":       "💎 QUALITY SNIPE",
        "description": "High conviction only. 0.5+ SOL curve depth. Score 60+. 2 trades/hr.",
        # sniper_settings
        "min_liquidity":         10_000,  # $10k+ liq for DexScreener tokens
        "min_volume":            5_000,
        "min_buys":              20,
        "max_token_age_minutes": 60,
        "default_buy_size":      0.05,
        "default_slippage":      15.0,
        "preferred_platform":    "auto",
        "strict_mode":           1,
        "strategy_mode":         "volume_spike",
        # auto_buy_settings
        "score_threshold":       60,
        "max_buy_size_sol":      0.05,
        "slippage":              15.0,
        "max_buys_per_hour":     2,
        "cooldown_seconds":      120,
        "priority_fee":          0.005,
        "min_initial_buy_sol":   0.5,   # 0.5 SOL in bonding curve — real conviction
    },

    # ── 2. MOMENTUM HUNTER ───────────────────────────────────────────────────
    # Volume spike strategy on tokens with real bonding curve depth.
    # Score 40+ → DexScreener is consulted → real volume/buys data used.
    # Catches tokens already gaining traction, not just brand-new launches.
    "momentum_hunter": {
        "label":       "🚀 MOMENTUM HUNTER",
        "description": "Volume spike detection. 0.15+ SOL curve. Score 40+. DexScreener data used.",
        "min_liquidity":         3_000,
        "min_volume":            2_000,
        "min_buys":              10,
        "max_token_age_minutes": 90,
        "default_buy_size":      0.05,
        "default_slippage":      18.0,
        "preferred_platform":    "auto",
        "strict_mode":           0,
        "strategy_mode":         "volume_spike",
        "score_threshold":       40,
        "max_buy_size_sol":      0.05,
        "slippage":              18.0,
        "max_buys_per_hour":     5,
        "cooldown_seconds":      60,
        "priority_fee":          0.005,
        "min_initial_buy_sol":   0.15,  # 0.15 SOL minimum — filters most rugs
    },

    # ── 3. GRADUATE RUNNER ───────────────────────────────────────────────────
    # Targets tokens that just graduated from pump.fun to Raydium/Jupiter.
    # Graduation = ~$69k mcap, real DEX liquidity added. These often run hard.
    # Jupiter only — graduated tokens cannot be bought via PumpPortal bonding curve.
    "graduate_runner": {
        "label":       "🎓 GRADUATE RUNNER",
        "description": "Pump.fun graduates on Raydium/Jupiter. Fresh DEX liquidity. Often big runners.",
        "min_liquidity":         5_000,   # real liq added at graduation
        "min_volume":            1_000,
        "min_buys":              5,
        "max_token_age_minutes": 120,     # allow up to 2h post-graduation
        "default_buy_size":      0.05,
        "default_slippage":      18.0,
        "preferred_platform":    "jupiter",
        "strict_mode":           0,
        "strategy_mode":         "graduate_hunter",
        "score_threshold":       20,      # behavior bonuses push score up on graduates
        "max_buy_size_sol":      0.05,
        "slippage":              18.0,
        "max_buys_per_hour":     8,
        "cooldown_seconds":      30,
        "priority_fee":          0.005,
        "min_initial_buy_sol":   0.1,    # ensures real initial demand before graduation
    },

    # ── 4. SURGE DETECT ──────────────────────────────────────────────────────
    # Fast entries on volume surges with verified curve depth.
    # Score 30+ → DexScreener consulted. Rewards vol/liq spike ratio.
    # Good balance of speed and quality — the go-to active preset.
    "surge_detect": {
        "label":       "⚡ SURGE DETECT",
        "description": "Fast vol surge entries. 0.1+ SOL curve. Score 30+. Active default.",
        "min_liquidity":         1_500,
        "min_volume":            1_000,
        "min_buys":              8,
        "max_token_age_minutes": 60,
        "default_buy_size":      0.05,
        "default_slippage":      20.0,
        "preferred_platform":    "auto",
        "strict_mode":           0,
        "strategy_mode":         "volume_spike",
        "score_threshold":       30,
        "max_buy_size_sol":      0.05,
        "slippage":              20.0,
        "max_buys_per_hour":     8,
        "cooldown_seconds":      45,
        "priority_fee":          0.005,
        "min_initial_buy_sol":   0.1,
    },

    # ── 5. ACTIVE HUNT ───────────────────────────────────────────────────────
    # Higher frequency mode. Still filtered (0.05 SOL min = no zero-traction rugs).
    # Score 20+. Catches more tokens, more risk, more opportunity.
    # Use with small buy sizes and tight stop-loss.
    "active_hunt": {
        "label":       "🔥 ACTIVE HUNT",
        "description": "Higher frequency. 0.05+ SOL curve. Score 20+. Use small size + tight SL.",
        "min_liquidity":         500,
        "min_volume":            200,
        "min_buys":              3,
        "max_token_age_minutes": 30,
        "default_buy_size":      0.02,
        "default_slippage":      22.0,
        "preferred_platform":    "auto",
        "strict_mode":           0,
        "strategy_mode":         "volume_spike",
        "score_threshold":       20,
        "max_buy_size_sol":      0.02,
        "slippage":              22.0,
        "max_buys_per_hour":     12,
        "cooldown_seconds":      20,
        "priority_fee":          0.005,
        "min_initial_buy_sol":   0.05,  # still filters zero-depth launches
    },

    # ── 6. WAVE RIDER ────────────────────────────────────────────────────────
    # FOMO/panic waves on tokens with real bonding curve depth.
    # 90%+ buy ratio, ultra-fresh, fast in/out before panic reverses.
    # 0.08 SOL min = no empty launches. Use very small size.
    "wave_rider": {
        "label":       "🌊 WAVE RIDER",
        "description": "FOMO waves on real-depth tokens. 0.08+ SOL curve. Fast in/out.",
        "min_liquidity":         0,
        "min_volume":            0,
        "min_buys":              5,       # need buys to confirm panic
        "max_token_age_minutes": 15,      # panic always on fresh tokens
        "default_buy_size":      0.01,
        "default_slippage":      25.0,
        "preferred_platform":    "pumpfun",
        "strict_mode":           0,
        "strategy_mode":         "panic_ride",
        "score_threshold":       15,
        "max_buy_size_sol":      0.01,   # tiny — panic reverses fast
        "slippage":              25.0,
        "max_buys_per_hour":     15,
        "cooldown_seconds":      10,
        "priority_fee":          0.006,  # slightly higher to beat bots on panic entries
        "min_initial_buy_sol":   0.08,   # filters empty launches
    },

    # ── 7. PORTFOLIO BUILDER ─────────────────────────────────────────────────
    # Buys tokens like Jellybean, $MAD, AIFRUITS — established projects with real
    # market caps ($100k+) that are gaining consistently over days/weeks.
    # Small position size so you can hold 10-20 tokens simultaneously.
    # Jupiter only (these are already on real DEXes). No age cap.
    # Score 35+ with smart_project mode pushes 41-day tokens to 70+.
    "portfolio_builder": {
        "label":       "📊 PORTFOLIO BUILDER",
        "description": "Buys established performers (10d+, $100k+ mcap, gaining). Builds diversified positions.",
        "min_liquidity":         20_000,  # real projects have DEX liquidity
        "min_volume":            5_000,
        "min_buys":              15,
        "max_token_age_minutes": 999_999, # no age cap — older proven = better
        "default_buy_size":      0.02,    # small size — hold 10-20 tokens at once
        "default_slippage":      14.0,
        "preferred_platform":    "jupiter",
        "strict_mode":           0,
        "strategy_mode":         "smart_project",
        "score_threshold":       35,      # smart_project bonus pushes good tokens to 55+
        "max_buy_size_sol":      0.02,    # small — build portfolio, not single bets
        "slippage":              14.0,
        "max_buys_per_hour":     10,      # higher frequency to build diversified positions
        "cooldown_seconds":      45,
        "priority_fee":          0.005,
        "min_initial_buy_sol":   0.0,     # not bonding curve — no filter needed
    },

    # ── 8. SMART PROJECT ─────────────────────────────────────────────────────
    # Single large-conviction entry on 30+ day tokens with $120k+ mcap and +5% 24h.
    # Targets proven tokens: 30+ days old, $120k+ market cap, +5%+ 24h growth.
    # These are not new launches — they are established projects gaining momentum.
    # Score gets a +10 bonus in the active scanner for meeting these criteria.
    # Jupiter only. Conservative size — these are deliberate entries, not gambles.
    "smart_project": {
        "label":       "🧠 SMART PROJECT",
        "description": "30+ day tokens, $120k+ mcap, +5% 24h growth. Proven projects only.",
        "min_liquidity":         50_000,  # real projects have real liquidity
        "min_volume":            10_000,
        "min_buys":              20,
        "max_token_age_minutes": 999_999, # no age cap — older is better
        "default_buy_size":      0.05,
        "default_slippage":      12.0,
        "preferred_platform":    "jupiter",
        "strict_mode":           1,
        "strategy_mode":         "smart_project",
        "score_threshold":       35,      # smart_project bonus scores proven tokens to 55+
        "max_buy_size_sol":      0.05,
        "slippage":              12.0,
        "max_buys_per_hour":     4,
        "cooldown_seconds":      90,
        "priority_fee":          0.005,
        "min_initial_buy_sol":   0.0,     # not bonding curve — no initial buy filter
    },
}
