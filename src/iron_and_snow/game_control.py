"""Nonblocking host side of the battlefield command spool."""
from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import time
import uuid

from .control import CONTROL_DIR, atomic_json, validate_command


class GameControl:
    def __init__(self, directory=CONTROL_DIR):
        self.directory = Path(directory)
        self.run_id = uuid.uuid4().hex
        self.battle_id = uuid.uuid4().hex
        self.events = deque(maxlen=12)
        self.last_publish = 0.0
        self.last_speech = 0.0
        self.revision = 0
        self.pending_policies = {}
        self.latest_ally_instruction = None
        for folder in ("commands", "receipts", "policies"):
            (self.directory / folder).mkdir(parents=True, exist_ok=True)

    def new_battle(self):
        self.battle_id = uuid.uuid4().hex
        self.events.clear()
        self.latest_ally_instruction = None

    def record(self, event, **data):
        self.events.append({"event": event, **data})
        self.revision += 1

    @staticmethod
    def group(actor):
        if getattr(actor, "ranged", False):
            return "archers"
        return "named" if actor.name in {"Tormund", "Sansa Stark", "Wun Wun", "Ramsay Bolton"} else "melee"

    def snapshot(self, game):
        actors = [(game.player, "allies")] if game.player else []
        actors += [(a, "allies") for a in getattr(game, "allies", [])]
        actors += [(a, "enemies") for a in game.enemies]
        units = []
        for actor, side in actors:
            visible = []
            for other, other_side in actors:
                if side == other_side or actor.pos.distance_squared_to(other.pos) > 700 ** 2:
                    continue
                if not any(o.clipline(actor.pos, other.pos) for o in game.obstacles):
                    visible.append(other.uid)
            order = game.order_for_ally(actor) if actor in getattr(game, "allies", []) else None
            units.append({"id": actor.uid, "name": actor.name, "side": side,
                          "group": self.group(actor), "position": [round(actor.pos.x), round(actor.pos.y)],
                          "health": round(actor.health), "max_health": actor.max_health,
                          "stamina": round(getattr(actor, "stamina", 100)),
                          "action": getattr(actor, "intent", "idle"), "visible": visible,
                          "player_order": order, "is_player": actor is game.player})
        return {"run_id": self.run_id, "battle_id": self.battle_id,
                "published_at": time.time(), "revision": self.revision, "phase": game.state,
                "chapter": game.chapter, "wave": game.chapter_wave,
                "combat_time": round(game.combat_time, 2), "units": units,
                "obstacles": [[o.x, o.y, o.width, o.height] for o in game.obstacles],
                "bounds": [32, 640, 3268, 1062], "events": list(self.events),
                "team_strategy": game.team_strategy,
                "ally_instruction": self.latest_ally_instruction,
                "policy": getattr(getattr(game, "armies", None), "policy_status", "baseline")}

    def tick(self, game, force=False):
        now = time.monotonic()
        if not force and now - self.last_publish < .2:
            return
        self.last_publish = now
        # Bound work per frame, including malformed commands from external tools.
        for path in list((self.directory / "commands").glob("*.json"))[:12]:
            command = {}
            try:
                command = json.loads(path.read_text(encoding="utf-8"))
                validate_command(command)
                if command.get("run_id") != self.run_id or command.get("battle_id") != self.battle_id:
                    raise ValueError("Command belongs to an old battle")
                if time.time() - command.get("created_at", 0) > 30:
                    raise ValueError("Command expired before it was applied")
                if game.state not in {"battle", "planning"}:
                    raise ValueError("No active council or battle")
                detail = self.apply(game, command)
                result = {"id": command["id"], "status": "accepted" if command["kind"] == "policy" else "applied", "detail": detail}
                if command["kind"] == "policy":
                    self.pending_policies[command["version"]] = command
                self.record("command_accepted" if command["kind"] == "policy" else "command_applied", source=command.get("source", "human"),
                            side=command.get("side"), kind=command["kind"], detail=detail)
            except Exception as exc:
                result = {"id": command.get("id", path.stem), "status": "rejected", "error": str(exc)}
            atomic_json(self.directory / "receipts" / path.name, result)
            path.unlink(missing_ok=True)
        runner = game.armies.runner
        for version, command in list(self.pending_policies.items()):
            active = Path(runner.good_path).stem == version
            superseded = runner.candidate and Path(runner.candidate).stem != version
            rejected = not runner.candidate and "rejected" in runner.status
            if active or superseded or rejected:
                result = {"id": command["id"], "status": "applied" if active else "rejected",
                          "detail": {"policy": version, "state": runner.status}}
                atomic_json(self.directory / "receipts" / f"{command['id']}.json", result)
                del self.pending_policies[version]
                self.record("policy_active" if active else "policy_rejected", version=version, source=command.get("source", "human"))
        atomic_json(self.directory / "state.json", self.snapshot(game))

    def apply(self, game, command):
        if command["kind"] == "order":
            actors = game.allies if command["side"] == "allies" else game.enemies
            chosen = [a for a in actors if ("all" in command["units"] or a.uid in command["units"]
                       or self.group(a) in command["units"])]
            if not chosen:
                raise ValueError("No selected units exist in this battle")
            if command["side"] == "allies":
                authorized = (self.latest_ally_instruction and command.get("source") == "codex"
                              and command.get("instruction") == self.latest_ally_instruction["id"]
                              and time.time() - self.latest_ally_instruction["at"] < 60)
                chosen = [a for a in chosen if authorized or not game.has_explicit_order(a)]
                if not chosen:
                    raise ValueError("Jon has explicit orders for those units; preserve his strategy")
            for actor in chosen:
                actor.control_order = {**command, "until": game.combat_time + command.get("duration", 20)}
                actor.hold_point = actor.pos.copy()
            return {"units": [a.uid for a in chosen], "action": command["action"],
                    "reason": command.get("reason", "")}
        if command["kind"] == "say":
            if time.monotonic() - self.last_speech < 8 or game.conversation_active():
                raise ValueError("A conversation is active; wait for the next speaking opportunity")
            self.last_speech = time.monotonic()
            speaker = command["speaker"].replace("_", " ").upper()
            game.add_dialogue(speaker, command["text"], voice=True, source=command.get("source", "human"))
            game.conversation_focus_until = time.monotonic() + 30
            if game.state == "battle":
                game.conversation.start(game.player, game.dialogue_actor(command["speaker"]))
                game.conversation.reply(command["text"])
            return {"speaker": speaker, "text": command["text"]}
        path = self.directory / "policies" / f"{command['version']}.py"
        if not path.is_file():
            raise ValueError("Policy file is missing")
        game.armies.publish_policy(path)
        return {"policy_candidate": command["version"], "status": "validating off the game thread"}
