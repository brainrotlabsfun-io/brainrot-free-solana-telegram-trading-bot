"""
services/burn_title_service.py
================================
Cosmetic burn title ladder — purely additive, no access logic touched.

Reads total_burned from user_burn_stats and returns the current title,
next title, and progress. Does NOT modify holder_access, burn_activations,
or any existing access control.
"""

from utils.badge_config import BURN_TITLE_LADDER


def get_burn_title(total_burned: float) -> dict:
    """
    Returns the user's current burn title and next milestone.

    Returns:
        {
            "emoji":        str,
            "title":        str,
            "perk_line":    str,   # empty for cosmetic-only tiers
            "next_emoji":   str | None,
            "next_title":   str | None,
            "next_threshold": float | None,
            "remaining":    float,
            "progress_pct": int,   # 0-100
        }
    """
    current = BURN_TITLE_LADDER[0]
    next_entry = None

    for entry in BURN_TITLE_LADDER:
        if total_burned >= entry[0]:
            current = entry
        elif next_entry is None:
            next_entry = entry

    threshold     = current[0]
    next_threshold = next_entry[0] if next_entry else None
    remaining     = max(0.0, next_threshold - total_burned) if next_threshold else 0.0

    if next_threshold and next_threshold > threshold:
        progress_pct = min(100, int(
            ((total_burned - threshold) / (next_threshold - threshold)) * 100
        ))
    else:
        progress_pct = 100

    return {
        "emoji":          current[1],
        "title":          current[2],
        "perk_line":      current[3],
        "next_emoji":     next_entry[1] if next_entry else None,
        "next_title":     next_entry[2] if next_entry else None,
        "next_threshold": next_threshold,
        "remaining":      remaining,
        "progress_pct":   progress_pct,
    }


def format_title_display(title_data: dict) -> str:
    """
    Returns a formatted string for display in profile / status pages.

    Example:
        ⚡ VOLTAGE
        Next: 🧠 ALPHA — 150,000 more $BRAINROT
    """
    emoji = title_data["emoji"]
    title = title_data["title"]
    perk  = title_data["perk_line"]

    line = f"{emoji} {title}"
    if perk:
        line += f"\n<code>  {perk}</code>"

    if title_data["next_title"]:
        line += (
            f"\n<i>Next: {title_data['next_emoji']} {title_data['next_title']} "
            f"— {title_data['remaining']:,.0f} more $BRAINROT</i>"
        )
    else:
        line += "\n<i>Max title achieved ⬛</i>"

    return line
