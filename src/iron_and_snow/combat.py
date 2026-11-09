"""Shared, timed sword combat for the player and both armies."""
from __future__ import annotations

import math
import time
import pygame

MOVES = {
    "quick": {"cost": 14, "windup": .22, "recovery": .46, "damage": 18, "reach": 88},
    "heavy": {"cost": 30, "windup": .57, "recovery": .68, "damage": 33, "reach": 102},
    "feint": {"cost": 8, "windup": .24, "recovery": .32, "damage": 0, "reach": 90},
}


class CombatSystem:
    def __init__(self, game):
        self.game = game
        self.tendencies = {"quick": 0, "heavy": 0, "parry": 0, "dodge": 0, "feint": 0}
        self.events = []

    def opponents(self, actor):
        g = self.game
        return [g.player, *g.allies] if actor in g.enemies else g.enemies

    def begin(self, actor, target=None, kind="quick"):
        g = self.game
        spec = MOVES[kind]
        if (not actor.alive or actor.attack_cooldown > 0 or actor.stamina < spec["cost"]
                or actor.stagger_until > g.combat_time or actor.dodge_until > g.combat_time):
            return False
        if target is None:
            candidates = [a for a in self.opponents(actor) if a and a.alive
                          and a.pos.distance_squared_to(actor.pos) < (spec["reach"] + 30) ** 2
                          and (a.pos - actor.pos).dot(actor.facing) >= 0]
            target = min(candidates, key=lambda a: a.pos.distance_squared_to(actor.pos), default=None)
        if target is not None and (target.pos - actor.pos).length_squared():
            actor.facing = (target.pos - actor.pos).normalize()
        if actor is not g.player and target is not None:
            committed = [a for a in [*g.allies, *g.enemies] if a is not actor and a.pending_strike
                         and a.pending_strike.get("target") is target]
            if len(committed) >= 2:
                return False
        actor.stamina -= spec["cost"]
        actor.block_time = 0
        actor.attack_cooldown = spec["windup"] + spec["recovery"]
        actor.pending_strike = {"kind": kind, "at": g.combat_time + spec["windup"],
                                "target": target, "direction": actor.facing.copy()}
        actor.attack_kind = kind
        actor.set_animation("attack", g.combat_time, actor.attack_cooldown)
        if actor is g.player:
            self.tendencies[kind] += 1
        return True

    def guard(self, actor):
        if actor.block_cooldown > 0 or actor.stamina < 8 or actor.stagger_until > self.game.combat_time:
            return False
        actor.stamina -= 8
        actor.block_time = .58
        actor.block_perfect_time = .17
        actor.block_cooldown = .85
        actor.pending_strike = None
        return True

    def dodge(self, actor, direction=None):
        g = self.game
        if actor.stamina < 24 or actor.dodge_cooldown > 0 or actor.stagger_until > g.combat_time:
            return False
        actor.stamina -= 24
        actor.dodge_cooldown = .95
        actor.dodge_until = g.combat_time + .28
        actor.invulnerable = max(actor.invulnerable, .23)
        direction = pygame.Vector2(direction) if direction is not None else pygame.Vector2(-actor.facing.y, actor.facing.x)
        if not direction.length_squared():
            direction.update(0, 1)
        actor.dodge_direction = direction.normalize()
        actor.pending_strike = None
        actor.block_time = 0
        actor.set_animation("walk", g.combat_time, .3)
        if actor is g.player:
            self.tendencies["dodge"] += 1
        return True

    def update(self, dt):
        g = self.game
        for actor in [g.player, *g.allies, *g.enemies]:
            if not actor or not actor.alive:
                continue
            actor.stamina = min(100, actor.stamina + dt * (17 if not actor.pending_strike else 3))
            actor.posture = max(0, actor.posture - dt * 14)
            actor.dodge_cooldown = max(0, actor.dodge_cooldown - dt)
            if actor.dodge_until > g.combat_time:
                actor.pos += actor.dodge_direction * 375 * dt
                actor.pos.x = max(32, min(3268, actor.pos.x))
                actor.pos.y = max(640, min(1062, actor.pos.y))
                actor._resolve_obstacles(g.obstacles)
            strike = actor.pending_strike
            if strike and g.combat_time >= strike["at"]:
                actor.pending_strike = None
                if actor.stagger_until <= g.combat_time:
                    self.resolve(actor, strike)

    def resolve(self, actor, strike):
        g = self.game
        spec = MOVES[strike["kind"]]
        if strike["kind"] == "feint":
            return
        g.effects.append([time.monotonic(), actor.pos + strike["direction"] * 42, "slash"])
        if g.attack_sound:
            g.attack_sound.play()
        target = strike["target"]
        if target is None or not target.alive or target.invulnerable > 0:
            return
        delta = target.pos - actor.pos
        if delta.length() > spec["reach"] or (delta.length_squared() and delta.normalize().dot(strike["direction"]) < .35):
            self.note("miss", actor, target)
            return
        if any(o.clipline(actor.pos, target.pos) for o in g.obstacles):
            return
        toward = -delta.normalize() if delta.length_squared() else -actor.facing
        guarded = target.block_time > 0 and target.facing.dot(toward) > .1
        if guarded and target.block_perfect_time > 0:
            actor.stagger_until = g.combat_time + .85
            actor.attack_cooldown = max(actor.attack_cooldown, .85)
            actor.pending_strike = None
            actor.set_animation("hit", g.combat_time, .35)
            g.effects.append([time.monotonic(), target.pos.copy(), "block"])
            g.play_hit_sound(.6)
            if target is g.player:
                self.tendencies["parry"] += 1
            self.note("parry", target, actor)
            return
        damage = spec["damage"]
        if guarded:
            target.posture += 47 if strike["kind"] == "heavy" else 25
            target.stamina = max(0, target.stamina - 12)
            if target.posture >= 100 or target.stamina <= 0:
                target.stagger_until = g.combat_time + 1.1
                target.block_time = 0
                self.note("guard_broken", actor, target)
            else:
                damage = round(damage * .2)
                g.effects.append([time.monotonic(), target.pos.copy(), "block"])
        if target.stagger_until > g.combat_time:
            damage = round(damage * 1.3)
        self.damage(target, damage, actor.pos - target.pos, actor)
        self.note(strike["kind"] + "_hit", actor, target)

    def damage(self, target, amount, incoming, attacker=None):
        g = self.game
        if target.invulnerable > 0 or not target.alive:
            return
        if target is g.player:
            # Sword guarding has already been resolved using shared rules.
            block = target.block_time
            target.block_time = 0
            g.damage_player(amount, incoming, attacker=attacker)
            target.block_time = block
        elif target in g.enemies:
            g.damage_enemy(target, amount, knockback_direction=-pygame.Vector2(incoming))
            target.invulnerable = .18
        else:
            target.health -= amount
            target.invulnerable = .2
            target.set_animation("hit", g.combat_time, .22)
            g.effects.append([time.monotonic(), target.pos.copy(), "hit"])
            g.play_hit_sound(.45)
            if target.health <= 0:
                target.alive = False
                if target in g.allies:
                    g.allies.remove(target)
        target.pending_strike = None

    def note(self, event, actor, target):
        self.game.control.record(event, actor=actor.uid, target=target.uid)
