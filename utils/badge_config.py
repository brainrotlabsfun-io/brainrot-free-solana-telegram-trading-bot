"""
utils/badge_config.py
======================
Badge key constants, display metadata, and threshold configuration
for the $BRAINROT burn-reward badge system.

All thresholds are in raw $BRAINROT token units (not lamports).
"""

# ── Badge Keys ─────────────────────────────────────────────────────────────────

BADGE_INITIATE          = "initiate"
BADGE_VERIFIED_BURNER   = "verified_burner"
BADGE_SUPREME_ACTIVATED = "supreme_activated"
BADGE_SUPREME_BRONZE    = "supreme_bronze"
BADGE_SUPREME_SILVER    = "supreme_silver"
BADGE_SUPREME_GOLD      = "supreme_gold"
BADGE_SUPREME_BLACK     = "supreme_black"
BADGE_FOUNDING_BURNER   = "founding_burner"

# ── Display Metadata ───────────────────────────────────────────────────────────

BADGE_META: dict[str, dict] = {
    BADGE_INITIATE: {
        "name":        "Initiate",
        "icon":        "🔥",
        "description": "First $BRAINROT tossed in the fire.",
        "tier_rank":   1,
    },
    BADGE_VERIFIED_BURNER: {
        "name":        "Verified Burner",
        "icon":        "✅",
        "description": "Burn confirmed on-chain. You're real.",
        "tier_rank":   2,
    },
    BADGE_SUPREME_ACTIVATED: {
        "name":        "SUPREME Activated",
        "icon":        "🔑",
        "description": "Unlocked SUPREME access via $BRAINROT burn.",
        "tier_rank":   3,
    },
    BADGE_SUPREME_BRONZE: {
        "name":        "SUPREME Bronze",
        "icon":        "🥉",
        "description": "500K+ burned. You're not playing around.",
        "tier_rank":   4,
    },
    BADGE_SUPREME_SILVER: {
        "name":        "SUPREME Silver",
        "icon":        "🥈",
        "description": "2M+ burned. Deep in the chain.",
        "tier_rank":   5,
    },
    BADGE_SUPREME_GOLD: {
        "name":        "SUPREME Gold",
        "icon":        "🥇",
        "description": "10M+ burned. Elite status.",
        "tier_rank":   6,
    },
    BADGE_SUPREME_BLACK: {
        "name":        "⬛ SUPREME BLACK",
        "icon":        "⬛",
        "description": "50M+ burned. Top of the ladder.",
        "tier_rank":   7,
    },
    BADGE_FOUNDING_BURNER: {
        "name":        "Founding Burner",
        "icon":        "🌟",
        "description": "OG burner. Was here before it was a thing.",
        "tier_rank":   8,
    },
}

# ── Cumulative Burn Thresholds (tokens) ────────────────────────────────────────
# 0 = any non-zero burn qualifies (used for milestone badges)

BADGE_BURN_THRESHOLDS: dict[str, float] = {
    BADGE_INITIATE:          0,
    BADGE_VERIFIED_BURNER:   0,
    BADGE_SUPREME_ACTIVATED: 0,       # activation threshold comes from config
    BADGE_SUPREME_BRONZE:    500_000,
    BADGE_SUPREME_SILVER:    2_000_000,
    BADGE_SUPREME_GOLD:      10_000_000,
    BADGE_SUPREME_BLACK:     50_000_000,
    BADGE_FOUNDING_BURNER:   0,
}

# ── Minimum Burn Count per Badge ───────────────────────────────────────────────

BADGE_BURN_COUNT_REQUIREMENTS: dict[str, int] = {
    BADGE_INITIATE:          1,
    BADGE_VERIFIED_BURNER:   1,
    BADGE_SUPREME_ACTIVATED: 1,
    BADGE_SUPREME_BRONZE:    1,
    BADGE_SUPREME_SILVER:    1,
    BADGE_SUPREME_GOLD:      1,
    BADGE_SUPREME_BLACK:     1,
    BADGE_FOUNDING_BURNER:   1,
}

# ── Badges That Require Active SUPREME Activation ─────────────────────────────

BADGE_REQUIRES_ACTIVATION: dict[str, bool] = {
    BADGE_INITIATE:          False,
    BADGE_VERIFIED_BURNER:   False,
    BADGE_SUPREME_ACTIVATED: True,
    BADGE_SUPREME_BRONZE:    True,
    BADGE_SUPREME_SILVER:    True,
    BADGE_SUPREME_GOLD:      True,
    BADGE_SUPREME_BLACK:     True,
    BADGE_FOUNDING_BURNER:   False,
}

# ── Ordered ladder for "next badge" progress display ──────────────────────────
# Only cumulative-threshold badges are in this list (milestone badges excluded)

CUMULATIVE_BADGE_LADDER: list[str] = [
    BADGE_SUPREME_BRONZE,
    BADGE_SUPREME_SILVER,
    BADGE_SUPREME_GOLD,
    BADGE_SUPREME_BLACK,
]

# ── Burn Title Ladder ──────────────────────────────────────────────────────────
# Cosmetic titles earned by cumulative $BRAINROT burned.
# Top 3 (SUPREME, SUPREME BLACK) align with holder_access tiers.
# The rest are cosmetic only — no access changes, no interference with burn logic.
#
# Each entry: (min_total_burned, emoji, title, perk_line)
# perk_line is shown on profile — empty string for cosmetic-only tiers.

BURN_TITLE_LADDER: list[tuple[float, str, str, str]] = [
    (0,           "🆓", "FREEBIE",       "3 copy wallets · 30 trades/hr · 1 position"),
    (10_000,      "🔩", "LURKER",        ""),
    (25_000,      "📡", "SIGNAL",        ""),
    (75_000,      "🔫", "SHOOTER",       ""),
    (150_000,     "💊", "PLUGGED",       ""),
    (300_000,     "🧪", "CHEMIST",       ""),
    (500_000,     "💀", "GHOST",         ""),
    (750_000,     "⚡", "VOLTAGE",       ""),
    (900_000,     "🧠", "ALPHA",         ""),
    (1_000_000,   "🔱", "SUPREME",       "20 copy wallets · 80 trades/hr · 3 positions"),
    (10_000_000,  "⬛", "SUPREME BLACK", "Unlimited everything · Auto-sell · TP/SL"),
]
