"""Role-driven armies with persistent destinations and executable Codex policies."""
from __future__ import annotations

import math
from pathlib import Path
import time
import pygame

from .army_policy import decide_actor
from .navigation import Navigator, SpatialIndex
from .policy_runner import PolicyRunner


class ArmyController:
    def __init__(self, game):
        self.game = game
        self.runner = PolicyRunner()
        self.navigator = None
        self.think_at = 0
        self.states = {}
        self.profiles = {}
        self.last_policy_service = 0
        self.profile_root = Path(__file__).with_name("characters")

    @property
    def policy_status(self):
        return self.runner.status

    def publish_policy(self, path):
        self.runner.publish(path)

    def reset(self):
        self.runner.decisions.clear()
        self.states.clear()
        self.think_at = 0
        self.navigator = Navigator(self.game.obstacles)
        for actor in [self.game.player, *self.game.allies, *self.game.enemies]:
            actor.navigator = self.navigator
            actor.hold_point = actor.pos.copy()

    def profile(self, actor):
        slug = ("sansa_stark" if "Sansa" in actor.name else "tormund_giantsbane" if "Tormund" in actor.name
                else "wun_wun" if "Wun" in actor.name else "ramsay_bolton" if "Ramsay" in actor.name
                else "stark_archer" if actor not in self.game.enemies and actor.ranged
                else "stark_soldier" if actor not in self.game.enemies
                else "bolton_archer" if actor.ranged else "bolton_soldier")
        if slug not in self.profiles:
            self.profiles[slug] = (self.profile_root / f"{slug}.md").read_text(encoding="utf-8").split("## Battle dialogue")[0]
        return self.profiles[slug]

    def order(self, actor):
        g = self.game
        order = getattr(actor, "control_order", {})
        instruction = g.control.latest_ally_instruction
        if (actor in g.allies and order.get("until", -1) > g.combat_time and instruction
                and order.get("instruction") == instruction["id"]):
            return order
        if actor in g.allies:
            key = g.ally_strategy_key(actor)
            explicit = g.has_explicit_order(actor)
            if explicit:
                positions = g.team_strategy.get("positions", {})
                group = "archers" if actor.ranged else "northmen"
                point = positions.get(key, positions.get(group)) if not g.has_explicit_order(actor, temporary_only=True) else None
                return {"action": g.order_for_ally(actor), "point": point}
        order = getattr(actor, "control_order", {})
        if order.get("until", -1) > g.combat_time:
            return order
        return {"action": g.order_for_ally(actor) if actor in g.allies else "advance"}

    def think(self, index):
        g = self.game
        actors = [*g.allies, *g.enemies]
        for ordinal, actor in enumerate(actors):
            hostile = actor in g.enemies
            opponents = [g.player, *g.allies] if hostile else g.enemies
            opponents = [a for a in opponents if a and a.alive]
            order = self.order(actor)
            choices = [a for a in index.near(actor.pos, 650) if a in opponents] or opponents
            if order.get("target"):
                choices = [a for a in opponents if a.uid == order["target"]] or choices
            elif order["action"] == "target_archers":
                choices = [a for a in choices if getattr(a, "ranged", False)] or choices
            elif order["action"] == "focus":
                choices = [a for a in choices if "Ramsay" in a.name] or choices
            elif order["action"] == "cover" and not hostile:
                choices = sorted(choices, key=lambda a: a.pos.distance_squared_to(g.player.pos))[:3]
            previous = getattr(actor, "target_actor", None)
            nearest = min(choices, key=lambda a: a.pos.distance_squared_to(actor.pos), default=None)
            # Target hysteresis prevents rapid switching when two soldiers cross.
            target = previous if previous in choices and nearest and previous.pos.distance_to(actor.pos) < nearest.pos.distance_to(actor.pos) + 75 else nearest
            actor.target_actor = target
            actor.intent_order = order
            if (not hostile and order["action"] == "follow" and target
                    and actor.pos.distance_to(target.pos) > 450):
                actor.target_actor = None
                continue
            if not target:
                continue
            nearby = index.near(actor.pos, 170)
            target_delta = target.pos - actor.pos
            state = {"id": actor.uid, "ordinal": ordinal, "health_fraction": actor.health / actor.max_health,
                     "stamina": actor.stamina, "ranged": getattr(actor, "ranged", False),
                     "target_distance": target_delta.length(), "target_position": list(target.pos),
                     "target_guarding": target.block_time > 0,
                     "threatening": bool(target.pending_strike and target_delta.length() < 120),
                     "can_dodge": actor.dodge_cooldown <= 0,
                     "allies_near": sum(a is not actor and (a in g.enemies) == hostile for a in nearby),
                     "enemies_near": sum((a in g.enemies) != hostile for a in nearby),
                     "line_of_sight": not any(o.clipline(actor.pos, target.pos) for o in g.obstacles),
                     "can_attack": False, "profile": self.profile(actor)}
            self.states[actor.uid] = state
        # Two committed melee attackers per target; others screen, flank or guard.
        by_target = {}
        for actor in actors:
            target = getattr(actor, "target_actor", None)
            if target and not getattr(actor, "ranged", False):
                by_target.setdefault(target.uid, []).append(actor)
        for group in by_target.values():
            group.sort(key=lambda a: a.pos.distance_squared_to(a.target_actor.pos))
            for actor in group[:2]:
                if actor.uid in self.states:
                    self.states[actor.uid]["can_attack"] = True
        active_ids = {a.uid for a in actors}
        self.states = {key: state for key, state in self.states.items() if key in active_ids}
        world = {"time": g.combat_time, "player_tendencies": dict(g.combat.tendencies),
                 "units_by_id": {a.uid: {"position": list(a.pos), "health": a.health} for a in actors}}
        self.runner.tick(list(self.states.values()), world)
        self.world = world

    def update(self, dt):
        g = self.game
        actors = [g.player, *g.allies, *g.enemies]
        index = SpatialIndex(actors)
        if g.combat_time >= self.think_at:
            self.think(index)
            self.think_at = g.combat_time + .25
        for actor in [*g.allies, *g.enemies]:
            for field in ("attack_cooldown", "invulnerable", "flash", "block_time", "block_perfect_time", "block_cooldown"):
                setattr(actor, field, max(0, getattr(actor, field) - dt))
            actor.moving = False
            actor.navigator = self.navigator
            target = getattr(actor, "target_actor", None)
            if target is None or not target.alive:
                # Idle soldiers hold useful ground instead of mirroring Jon.
                order = self.order(actor)
                if order["action"] == "move" and order.get("point"):
                    actor.intent = "move"
                    actor.move_toward(order["point"], dt, g.obstacles, g.combat_time,
                                      crowd=[a for a in index.near(actor.pos, 95) if a is not actor])
                    continue
                if actor in g.allies and actor.pos.distance_to(g.player.pos) > 480:
                    destination = getattr(actor, "regroup_point", None)
                    if destination is None or actor.pos.distance_to(destination) < 35:
                        actor.regroup_point = g.player.pos.copy()
                    actor.move_toward(actor.regroup_point, dt, g.obstacles, g.combat_time,
                                      crowd=[a for a in index.near(actor.pos, 95) if a is not actor])
                    continue
                actor.velocity *= .75
                actor._update_animation(g.combat_time)
                continue
            if actor.stagger_until > g.combat_time or actor.dodge_until > g.combat_time or actor.pending_strike:
                continue
            state = dict(self.states.get(actor.uid, {}))
            delta = target.pos - actor.pos
            distance = delta.length()
            state.update(stamina=actor.stamina, target_distance=distance,
                         health_fraction=actor.health / actor.max_health,
                         threatening=bool(target.pending_strike and distance < 120),
                         can_dodge=actor.dodge_cooldown <= 0, target_guarding=target.block_time > 0)
            decision = self.runner.decisions.get(actor.uid) or decide_actor(state, self.world, self.profile(actor))
            # Survival reactions use current state even between policy evaluations.
            if actor.health < actor.max_health * .30 or actor.stamina < 22 or state["threatening"]:
                decision = decide_actor(state, self.world, self.profile(actor))
            action = decision["action"]
            order = getattr(actor, "intent_order", {"action": "advance"})
            macro = order["action"]
            actor.intent = macro if macro in {"hold", "move", "defend", "retreat", "rescue"} else action
            actor.intent_reason = decision.get("reason", "")
            friends = g.enemies if actor in g.enemies else [g.player, *g.allies]
            crowd = [other for other in index.near(actor.pos, 95) if other is not actor]
            away = -delta.normalize() if distance else pygame.Vector2(1, 0)
            if action == "dodge":
                sign = 1 if int(actor.uid[:2], 16) % 2 else -1
                g.combat.dodge(actor, pygame.Vector2(away.y, -away.x) * sign)
            elif action in {"retreat", "recover"} or macro == "retreat":
                if distance < (290 if actor.ranged else 215):
                    support = min((a for a in friends if a is not actor),
                                  key=lambda a: a.pos.distance_squared_to(actor.pos), default=actor)
                    destination = actor.pos + away * 155 + (support.pos - actor.pos) * .3
                    actor.move_toward(destination, dt, g.obstacles, g.combat_time, crowd)
                else:
                    actor.facing = -away
                    actor._update_animation(g.combat_time)
            elif macro == "rescue":
                wounded = min(friends, key=lambda a: a.health / a.max_health)
                destination = wounded.pos + away * 55
                if actor.pos.distance_to(destination) > 50:
                    actor.move_toward(destination, dt, g.obstacles, g.combat_time, crowd)
                else:
                    actor.facing = -away
                    g.combat.guard(actor)
                    if distance < 90 and state.get("can_attack"):
                        g.combat.begin(actor, target)
            elif macro in {"hold", "move", "defend"}:
                destination = pygame.Vector2(order.get("point") or actor.hold_point)
                if actor.pos.distance_to(destination) > 24:
                    actor.move_toward(destination, dt, g.obstacles, g.combat_time, crowd)
                elif actor.ranged and distance < 445 and state.get("line_of_sight"):
                    self.shoot(actor, target)
                elif distance < 90:
                    g.combat.guard(actor)
                    if state.get("can_attack"):
                        g.combat.begin(actor, target)
            elif action == "guard":
                actor.facing = -away
                g.combat.guard(actor)
            elif action in {"attack", "heavy", "feint"}:
                g.combat.begin(actor, target, "quick" if action == "attack" else action)
            elif action == "shoot":
                self.shoot(actor, target)
            elif actor.ranged and not state.get("line_of_sight"):
                # A bowman blocked by terrain moves to a firing lane instead
                # of stopping at an unusable ideal range behind a boulder.
                if g.combat_time >= getattr(actor, "vantage_until", 0):
                    candidates = [target.pos + pygame.Vector2(math.cos(angle), math.sin(angle)) * 285
                                  for angle in (i * math.pi / 4 for i in range(8))]
                    candidates = [point for point in candidates if 32 < point.x < 3268 and 650 < point.y < 1050
                                  and not any(o.inflate(50,50).collidepoint(point) or o.clipline(point,target.pos)
                                              for o in g.obstacles)]
                    actor.vantage_point = min(candidates, key=lambda point: point.distance_squared_to(actor.pos), default=actor.pos + away * 80)
                    actor.vantage_until = g.combat_time + 1.3
                actor.move_toward(actor.vantage_point, dt, g.obstacles, g.combat_time, crowd)
            else:
                stand_off = 290 if actor.ranged else (65 if state.get("can_attack") else 145)
                if distance > stand_off + 18 or (macro in {"flank_left", "flank_right"} and distance > 150):
                    destination = target.pos + away * stand_off
                    if macro in {"flank_left", "flank_right"}:
                        destination += pygame.Vector2(-away.y, away.x) * (100 if macro == "flank_left" else -100)
                    if decision.get("point"):
                        destination = pygame.Vector2(decision["point"])
                    actor.move_toward(destination, dt, g.obstacles, g.combat_time, crowd)
                else:
                    actor.velocity *= .7
                    actor.facing = -away
                    actor._update_animation(g.combat_time)

    def service_policy(self):
        now = time.monotonic()
        if now - self.last_policy_service >= .2:
            self.last_policy_service = now
            self.think(SpatialIndex([self.game.player, *self.game.allies, *self.game.enemies]))

    def shoot(self, actor, target):
        g = self.game
        if actor.attack_cooldown > 0 or actor.stamina < 10:
            return
        if any(o.clipline(actor.pos, target.pos) for o in g.obstacles):
            return
        direction = target.pos - actor.pos
        if not direction.length_squared():
            return
        actor.facing = direction.normalize()
        actor.stamina -= 10
        actor.attack_cooldown = 2.1
        actor.set_animation("attack", g.combat_time, .6)
        g.pending_support_shots.append({"shooter": actor, "target": target, "damage": 16,
                                       "release_at": g.combat_time + .42})

    def close(self):
        self.runner.close()
