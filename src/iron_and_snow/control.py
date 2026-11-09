"""File-spooled game CLI. No network service, game imports, or model loading."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "save" / "game-control"
ACTIONS = {"follow", "cover", "focus", "target_archers", "flank_left", "flank_right",
           "hold", "retreat", "advance", "move", "defend", "rescue"}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    try:
        os.replace(temporary, path)
    except PermissionError:
        # Windows can briefly lock a destination while the CLI reads it. Keep
        # the last complete snapshot and retry on the next host tick.
        temporary.unlink(missing_ok=True)
        return False
    return True


def read_snapshot(directory=CONTROL_DIR):
    state = json.loads((Path(directory) / "state.json").read_text(encoding="utf-8"))
    if time.time() - state["published_at"] > 5:
        raise ValueError("Game snapshot is stale. Start or resume the game first.")
    return state


def observe(state, side):
    state = dict(state)
    if side != "all":
        units = state.get("units", [])
        friends = [u for u in units if u["side"] == side]
        seen = {v for u in friends for v in u.get("visible", [])}
        state["units"] = [u for u in units if u["side"] == side or u["id"] in seen]
    if side == "enemies":
        state["ally_instruction"] = None
        state["team_strategy"] = {"note": "Jon's private strategy is not visible to the enemy"}
    return state


def summarize(state):
    groups = {}
    for unit in state.get("units", []):
        key = unit["side"] + ":" + unit["group"]
        group = groups.setdefault(key, {"count": 0, "health_total": 0, "position": [0, 0]})
        group["count"] += 1
        group["health_total"] += unit["health"]
        group["position"][0] += unit["position"][0]
        group["position"][1] += unit["position"][1]
    for group in groups.values():
        group["position"] = [round(v / group["count"]) for v in group["position"]]
    return {"run_id": state["run_id"], "battle_id": state["battle_id"], "phase": state["phase"],
            "chapter": state["chapter"], "wave": state["wave"], "groups": groups,
            "wounded": [{k: u[k] for k in ("id", "name", "side", "health", "position")}
                        for u in state.get("units", []) if u["health"] < u["max_health"] * .5][:8],
            "team_strategy": state["team_strategy"], "policy": state["policy"],
            "ally_instruction": state.get("ally_instruction"),
            "events": state["events"][-5:]}


def validate_command(command):
    if command.get("source", "human") not in {"human", "codex"}:
        raise ValueError("Unknown command source")
    if command.get("kind") == "order":
        if command.get("action") not in ACTIONS:
            raise ValueError("Unknown unit action")
        if command.get("side") not in {"allies", "enemies"}:
            raise ValueError("Orders target allies or enemies")
        if not isinstance(command.get("units"), list) or not command["units"]:
            raise ValueError("Select a unit id or group")
        if not all(isinstance(value, str) for value in command["units"]):
            raise ValueError("Unit selectors must be strings")
        if not isinstance(command.get("reason", ""), str):
            raise ValueError("Order reason must be text")
        if not 1 <= float(command.get("duration", 20)) <= 120:
            raise ValueError("Order duration must be 1..120 seconds")
        if command.get("action") == "move":
            import math
            point = command.get("point")
            if not (isinstance(point, list) and len(point) == 2
                    and all(isinstance(v, (int, float)) and math.isfinite(v) for v in point)):
                raise ValueError("Move requires a finite x/y destination")
            if not (32 <= point[0] <= 3268 and 640 <= point[1] <= 1062):
                raise ValueError("Move destination is outside the walkable battlefield")
    elif command.get("kind") == "say":
        if command.get("speaker") not in {"ramsay_bolton", "sansa_stark", "tormund_giantsbane"}:
            raise ValueError("Unknown speaker")
        if not isinstance(command.get("text"), str) or not 1 <= len(command["text"]) <= 220:
            raise ValueError("Speech must contain 1..220 characters")
    elif command.get("kind") == "policy":
        if not isinstance(command.get("version"), str) or not command["version"].isalnum():
            raise ValueError("Invalid policy version")
    else:
        raise ValueError("Unknown command kind")
    return command


def publish_policy(source, directory=CONTROL_DIR):
    text = Path(source).read_text(encoding="utf-8")
    tree = ast.parse(text)
    if not any(isinstance(n, ast.FunctionDef) and n.name == "decide_actor" for n in tree.body):
        raise ValueError("Policy must define decide_actor(unit, world, profile)")
    compile(tree, str(source), "exec")
    version = hashlib.sha256(text.encode()).hexdigest()[:16]
    path = Path(directory) / "policies" / f"{version}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return version


def submit(command, directory=CONTROL_DIR, wait=0):
    directory = Path(directory)
    state = read_snapshot(directory)
    if state.get("phase") not in {"planning", "battle"}:
        raise ValueError("Start a council or battle before sending commands")
    validate_command(command)
    command = {**command, "id": uuid.uuid4().hex, "run_id": state["run_id"],
               "battle_id": state["battle_id"], "created_at": time.time()}
    atomic_json(directory / "commands" / f"{command['id']}.json", command)
    deadline = time.monotonic() + wait
    receipt = directory / "receipts" / f"{command['id']}.json"
    while wait and time.monotonic() < deadline:
        if receipt.exists():
            result = json.loads(receipt.read_text(encoding="utf-8"))
            if result.get("status") != "accepted":
                return result
        time.sleep(.04)
    return {"id": command["id"], "status": "queued"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=CONTROL_DIR)
    parser.add_argument("--source", choices=("human", "codex"), default="human")
    parser.add_argument("--wait", type=float, default=0, help="Wait up to N seconds for an applied receipt")
    sub = parser.add_subparsers(dest="command", required=True)
    look = sub.add_parser("observe")
    look.add_argument("--side", choices=("allies", "enemies", "all"), default="all")
    look.add_argument("--summary", action="store_true", help="Compact group state for commander reasoning")
    order = sub.add_parser("order")
    order.add_argument("--side", choices=("allies", "enemies"), required=True)
    order.add_argument("--units", nargs="+", required=True, help="IDs or groups: all, melee, archers, named")
    order.add_argument("--action", choices=sorted(ACTIONS), required=True)
    order.add_argument("--point", nargs=2, type=float)
    order.add_argument("--target", help="Optional target unit ID")
    order.add_argument("--duration", type=float, default=20)
    order.add_argument("--reason", default="")
    order.add_argument("--instruction", help="Current Jon instruction ID when implementing his changed strategy")
    say = sub.add_parser("say")
    say.add_argument("--speaker", required=True)
    say.add_argument("--text", required=True)
    policy = sub.add_parser("policy")
    policy.add_argument("--file", required=True, type=Path)
    receipt = sub.add_parser("receipt")
    receipt.add_argument("id")
    args = parser.parse_args(argv)
    try:
        if args.command == "observe":
            result = observe(read_snapshot(args.directory), args.side)
            if args.summary:
                result = summarize(result)
        elif args.command == "receipt":
            if not args.id.isalnum():
                raise ValueError("Invalid receipt ID")
            result = json.loads((args.directory / "receipts" / f"{args.id}.json").read_text())
        else:
            command = {"kind": args.command, "source": args.source}
            if args.command == "order":
                command.update(side=args.side, units=args.units, action=args.action, point=args.point,
                               target=args.target, duration=args.duration, reason=args.reason[:220], instruction=args.instruction)
            elif args.command == "say":
                command.update(speaker=args.speaker, text=args.text)
            else:
                command["version"] = publish_policy(args.file, args.directory)
            result = submit(command, args.directory, max(0, min(args.wait, 10)))
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result.get("status") == "rejected" else 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
