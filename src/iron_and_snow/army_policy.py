"""Shared editable combat decisions. One O(1) decision per unit per thinking tick.

decide_actor(unit, world, profile) returns {action, reason}; optionally point=[x,y].
unit contains id, health_fraction, stamina, ranged, target_distance, target_position,
threatening, target_guarding, can_attack, allies_near, enemies_near, ordinal.
world contains time, player_tendencies, and units_by_id (read only).
Allowed actions: attack, heavy, feint, dodge, guard, shoot, retreat, recover,
advance, hold. The engine executes legal attacks and never bypasses resources.
"""


def decide_actor(unit, world, profile):
    distance = unit.get("target_distance", 9999)
    stamina = unit.get("stamina", 100)
    cautious = "Disposition: cautious" in profile
    if unit.get("health_fraction", 1) < (.40 if cautious else .30):
        return {"action": "retreat", "reason": "Wounded; regroup behind friendly troops"}
    if stamina < 22:
        return {"action": "recover", "reason": "Recover stamina before committing"}
    if unit.get("enemies_near", 0) > unit.get("allies_near", 0) + 2 and distance < 160:
        return {"action": "retreat", "reason": "Outnumbered; seek support"}
    if unit.get("threatening") and distance < 115:
        if stamina >= 32 and unit.get("can_dodge", True):
            return {"action": "dodge", "reason": "Evade the committed sword swing"}
        return {"action": "guard", "reason": "Brace for the incoming attack"}
    if unit.get("ranged"):
        if distance < 185:
            return {"action": "retreat", "reason": "Bowmen need distance from blades"}
        if distance < 445 and unit.get("line_of_sight"):
            return {"action": "shoot", "reason": "Clear firing lane"}
        return {"action": "advance", "reason": "Find a firing position"}
    if distance < 92 and unit.get("can_attack"):
        if unit.get("target_guarding") and stamina > 45:
            return {"action": "heavy", "reason": "Break the opponent's guard"}
        habits = world.get("player_tendencies", {})
        if habits.get("parry", 0) > 2 and unit.get("ordinal", 0) % 3 == 0:
            return {"action": "feint", "reason": "Bait the repeated parry"}
        return {"action": "attack", "reason": "Exploit an opening with support nearby"}
    if distance < 130 and not unit.get("can_attack"):
        return {"action": "guard", "reason": "Support the engaged fighter; avoid piling in"}
    return {"action": "advance", "reason": "Approach under coordinated squad orders"}
