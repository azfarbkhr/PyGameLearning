"""Generic profile-driven policy for shared NPC battle behavior."""


def decide(state: dict, profile_text: str) -> str:
    """Choose only a tactic supported by profile guidance and current state."""
    state = state if isinstance(state, dict) else {}
    profile = str(profile_text or "").lower()
    chapter = str(state.get("chapter", "")).strip().lower().replace("-", "_")
    try:
        health = float(state.get("health", 100))
    except (TypeError, ValueError):
        health = 100.0
    try:
        enemies = int(state.get("enemies", 0))
    except (TypeError, ValueError):
        enemies = 0

    has = lambda tactic: tactic in profile
    if has("withdraw") and (health < 100 / 3 or state.get("survival_is_priority", False)):
        return "withdraw"

    allies = state.get("reliable_allies_nearby", state.get("ally_present", False))
    permits_archers = chapter in {"battlefield", "shield_wall", "giant_charge",
                                  "giants_charge", "winterfell_courtyard"}
    if (permits_archers and enemies > 2 and state.get("archers_available", False)
            and has("archer") and not allies):
        return "call_archers"
    if allies and has("feint"):
        return "feint"
    if (state.get("opponent_isolated", False) or state.get("opponent_injured", False)) and has("press"):
        return "press"
    if chapter == "startup" and has("feint"):
        return "feint"
    if has("press"):
        return "press"
    if has("feint"):
        return "feint"
    return "withdraw" if has("withdraw") else "press"


def decide_team_order(command: str, state: dict, profile_text: str) -> str:
    """Map a short player command to a bounded, reusable squad behavior."""
    text = str(command or "").lower()
    if any(word in text for word in ("retreat", "fall back", "withdraw", "back to me", "pull back")):
        return "retreat"
    if any(word in text for word in ("flank left", "left flank", "from the left", "go left")):
        return "flank_left"
    if any(word in text for word in ("flank right", "right flank", "from the right", "go right")):
        return "flank_right"
    if any(word in text for word in ("hold", "stay here", "hold ground", "defend this", "hold position", "stay put")):
        return "hold"
    if any(word in text for word in (
        "cover", "protect", "guard me", "watch my back", "defend me", "help me", "come help", "save me",
    )):
        return "cover"
    if any(word in text for word in (
        "archer", "bowmen", "bows", "back line", "backline", "rear line", "ranged line", "shoot their",
    )):
        return "target_archers"
    if any(word in text for word in (
        "focus", "bolton", "ramsay", "ramsey", "leader", "attack", "target", "engage", "charge", "take out", "fight them",
    )):
        return "focus"
    if any(word in text for word in ("follow", "with me", "regroup", "stay close", "come to me")):
        return "follow"
    # Do not silently turn an unrecognized transcript into a no-op follow order.
    # The game can then ask the player to repeat a supported command.
    return "unrecognized"
