---
name: battlefield-control
description: Direct the running Iron and Snow armies through the game CLI, observe outcomes, and write efficient shared NPC policies. Use for live battlefield tactics and survival behavior in this project.
---

Use the project venv Python and `-m iron_and_snow.control` from the repository root.
The host supplies its absolute Python and project paths when starting a game session.

Observe before commanding: `python -m iron_and_snow.control observe --side enemies --summary`
(or `--side allies` for the allied commander). Snapshots expire after five seconds.
Use the same faction for observation and orders. Units expose only currently visible
opponents; use those observations rather than reading unfiltered state files.
The summary groups troops and lists wounded units to keep context small. Omit
`--summary` only when individual unit IDs or exact geometry are needed. During
the council the real army is prepared but frozen; orders begin when combat starts.

Examples (global flags go before the subcommand):

```powershell
python -m iron_and_snow.control --source codex --wait 2 order --side enemies --units melee --action flank_left --duration 20 --reason "Draw Jon away from the archers"
python -m iron_and_snow.control --source codex --wait 2 order --side enemies --units archers --action hold --duration 25
python -m iron_and_snow.control --source codex --wait 2 say --speaker ramsay_bolton --text "Shields forward. Keep your wounded behind the line."
python -m iron_and_snow.control --source codex --wait 2 policy --file save/game-control/candidate.py
```

Orders select IDs or groups `all`, `melee`, `archers`, `named`. Actions are listed by
`order --help`; `move` requires `--point X Y`. Read the applied receipt. Queued means
the game has not yet consumed the command. Re-observe when a battle changes; stale
battle commands are rejected. Preserve Jon's explicit council and spoken orders.

Prefer coordinated actions over one command per soldier. Troops want to survive:
rotate exhausted attackers, support wounded allies, keep archers out of melee,
retreat with purpose, and contest objectives. Reconsider after losses, new waves,
orders, or exposed flanks; do not issue a new command every frame.

For durable behavior, write one generic Python candidate defining
`decide_actor(unit, world, profile) -> dict`, then publish it with `policy`.
Read `src/iron_and_snow/army_policy.py` for the input/output contract. Character
personality lives in `characters/*.md`. Never create character-specific Python.
Use supplied neighbors and indexed units rather than repeated full-army searches.
The policy runs in a separate process; a bad or slow candidate is rejected and
the last working policy remains active. Do not import game state, do IO, launch
processes, or mutate `world` from policy functions. Return intents; the game owns
physics, attack timings, stamina, collision and legal actions.

The allied snapshot includes `ally_instruction` when Jon has just spoken. If that
instruction requests a change to an existing assignment, include
`--instruction <that id>` on the corresponding allied `order`. This permits the
requested tactical change for the order's duration; the council plan resumes
afterward. Do not use it to override a plan when Jon only asks a question. Old
instruction IDs cannot supersede a newer player instruction.

Tell the host briefly what changed and why. A result counts as applied only when
the receipt or a newer snapshot shows it. Leave dialogue to the conversation
session unless a short commander order is useful and no one is speaking.
