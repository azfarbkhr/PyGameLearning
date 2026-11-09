# Iron & Snow: The Bastard's Winter

A personal, fan-made 2D Pygame game inspired by *Game of Thrones* and the Battle of the Bastards. This is a learning and AI integration experiment, not an official product and not intended for sale or commercial distribution. *Game of Thrones* and its characters belong to their respective rights holders.

## The story

Play Jon Snow in a combat-focused retelling of the battle for Winterfell. Three fronts now contain seven combat phases, with reinforcements between phases and less story text between fights:

1. **Before Dawn** — learn why the North must take Winterfell back.
2. **The Battlefield** — survive the Bolton infantry and archers, then break the reserve line.
3. **The Giants' Charge** — break the shield wall and its reinforcements to reach Winterfell's gates.
4. **The Courtyard** — clear two guard pushes before Ramsay enters for the final duel.

If Jon falls, the North rallies. Choose **R** to rebuild and retry with a tactical advantage, or **Q** to return to the title screen. Defeat is an alternate story outcome; victory returns the Stark banners to Winterfell.

## Run it

Requirements: Windows, Python 3.13+, and uv. Codex sign-in enables live AI dialogue and tactics. A microphone enables voice input. Local Kokoro and Whisper are the default voice engines; internet access is used only when their Edge TTS or Google recognition fallbacks are needed. The campaign still runs with local scripted behavior if Codex is unavailable.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\run_game.ps1
```

The standard launcher prepares the game's local voice models, then starts the same game. GPT-6 Luna handles Codex dialogue. Kokoro ONNX provides local speech synthesis, and multilingual Whisper tiny handles local speech recognition; Whisper can use CUDA or fall back to CPU. If a local voice model cannot load, its online fallback is Edge TTS or Google speech recognition. The fallback services need internet access. A microphone is only needed for voice conversations and team orders; combat and mouse controls work without one.

## Controls

The council clock pauses while voice models warm up, while you speak, and while
an adviser thinks or speaks. Genuine Codex replies are marked **AI ADVISER**;
timeout responses are marked **SCRIPTED FALLBACK**. An adviser can propose up to
three unit orders. Review **AI PROPOSES**, then click **APPLY AI PLAN** or say
“apply that” to save those assignments for the battle. Manual orders remain
available. During battlefield conversations, combat pauses and the camera focuses
on Jon, then smoothly shifts to the responding character. Captions appear before
voice playback. The camera returns to Jon before combat resumes. Council recordings
allow up to 12 seconds; Codex reply windows are 25 seconds in council and 18 seconds
in battle. Voice synthesis sends complete sentences to playback as they become ready.

| Input | Action |
| --- | --- |
| Enter / Space / click | Begin, advance story, or dismiss the victory ending |
| Arrow keys | Move Jon freely in four directions; diagonal movement is normalized. Arrow-key movement cancels an active mouse destination or enemy approach. |
| Click battlefield | Move Jon to that point; click an enemy to approach and auto-strike. The battle now spans a wide, scrolling Winterfell approach; the camera eases after Jon leaves its inner focus area. |
| Pre-battle war council | After each front's story card, you have 60 seconds to discuss the plan. Click Sansa or Tormund, use B/T to speak, set one named-unit order per phrase, and say “I'm done” or click Start Battle. The timer starts the fight automatically. Orders in Current Orders are applied for the full battle. |
| Left / Right Shift | Burst toward the current mouse destination for 0.46 seconds; recharges after a brief cooldown |
| Space | Quick sword slash with windup and recovery |
| C / X | Heavy overhead strike / feint to draw a guard or dodge |
| Alt / right mouse button | Stamina-limited sidestep; arrow keys choose dodge direction |
| Enter during a conversation | End the exchange and return to battle |
| Q (battle) | Raise your guard; time the first 0.18 seconds for a perfect block |
| F | Call two Stark archers once per chapter |
| R (battle) | Fire an arrow; eight arrows are shared across the campaign and restored on retry |
| B | Talk to the selected character during battle. Speak a short line; it sends automatically after a pause. During the war council, B talks to the selected adviser. |
| E | Start a voice conversation with Ramsay; speech sends automatically after a pause. |
| T | Give the Stark team or a named ally a spoken order. The HUD shows examples while the mic listens, then confirms the applied order. Supported commands include “cover me”, “focus Ramsay”, “attack their archers”, “flank left/right”, “hold”, “follow”, and “retreat”. Unrecognized speech is shown and does not silently apply a default order. |
| Tab | Cycle the conversation target between Ramsay, Sansa, and Tormund for B; during planning, switch between Sansa and Tormund. |
| Y | Ask the live Codex enemy commander to inspect the battle and issue CLI orders or revise the shared army policy |
| R (defeat) or click “Rebuild and Retry” | Rebuild with extra allies, archers, and full arrow supply |
| Q (defeat) or click “Return to Title” | Return to the title screen |

## Codex inside the game

The game uses persistent GPT-6 Luna sessions at low effort. `npc.py` handles
character conversations and council proposals. `director.py` runs independent
allied and enemy commanders, which use shell tools to invoke a real game CLI.
They begin planning against the prepared full army during the war council. The
current enemy chapter/wave counts are retained. Sansa participates in every
battle so her accepted council assignments affect a real archer.

The repository skill is `.agents/skills/battlefield-control/SKILL.md`.
From the prepared project environment, the CLI supports:

```powershell
.\.venv\Scripts\python.exe -m iron_and_snow.control observe --side enemies --summary
.\.venv\Scripts\python.exe -m iron_and_snow.control --wait 2 order --side enemies --units melee --action flank_left --reason "Protect the archers"
.\.venv\Scripts\python.exe -m iron_and_snow.control --wait 2 policy --file save/game-control/candidate.py
```

`observe --summary` keeps recurring context small. Full observations provide unit
IDs, health, stamina, visible opponents, terrain and current orders. Commands
have battle IDs and expire if stale. Receipts show queued, applied or rejected
results; the HUD displays actual Codex orders. Command files and snapshots live
under the ignored `save/game-control/` directory. No network control server is
needed. On Windows the commander uses a per-session unelevated workspace sandbox
with the command directory explicitly writable, without changing global Codex
settings.

Codex can publish one generic Python `decide_actor(unit, world, profile)` policy.
A separate process evaluates it at a limited thinking rate. Candidates must
return supported intents, and an exception, invalid result or runaway script
retains the last working behavior. Continuous physics, legal attacks and resource
costs execute in Pygame. `army_policy.py` supplies survival behavior until Codex
publishes a policy; all character-specific traits remain in Markdown.

Armies have independent targets, stable objectives, cached grid paths, local
separation and gradual acceleration/turning. Wounded or outnumbered fighters
withdraw toward support, archers maintain distance and clear firing lanes, and
only two NPCs can commit sword attacks to one target at once. Explicit player
orders take priority over commander suggestions. A commander implementing Jon's
new spoken instruction can reference that instruction's ID to temporarily update
only the requested units; an old instruction cannot supersede a newer one. Simple spoken orders apply
immediately; both simple and free-form team instructions also reach the Codex
conversation and allied commander.

Jon and NPCs share timed attacks, stamina, posture, guarding, dodging and recovery.
A quick slash deals 18 damage; a heavy overhead strike deals 33 before guard or
counter modifiers. Ordinary enemy soldiers have roughly 84 health versus Jon's
100. Their attacks use the same damage values and can hit Jon or his allies.
Feints draw defensive reactions; repeated parries can prompt the shared policy
to change its attack selection.

Conversation latency is presented through paused action, listener camera focus,
subtle idle animation, immediate captions and sentence-by-sentence voice output.
Starting another utterance cancels old speech, and late responses cannot interrupt
the next exchange. These techniques give inference time a place in the scene;
they do not claim to eliminate network or model latency.

For a reproducible showcase, discuss and accept a council plan, start the full
battle, observe independent ally behavior, bait and dodge an overhead strike,
then press E to address Ramsay or T to coordinate the team. The camera stages
both turns. Observe the Codex order feed and CLI receipts for evidence of actual
AI action. [TICKETS.md](TICKETS.md) records implementation and verification status.

Checks (no microphone recording):

```powershell
.\.venv\Scripts\python.exe -m iron_and_snow.check_showcase
.\.venv\Scripts\python.exe -m iron_and_snow.check_live_conversation
.\.venv\Scripts\python.exe -m iron_and_snow.check_live_director
```

Add `--with-voice` to the conversation check to synthesize and decode actual
responses, or `--interrupt-only` to verify cancellation of a real in-flight turn.
The first command is an offline behavioral/rendering check. The other two use
the signed-in Codex account and verify actual model replies and CLI actions.
Captures and reports are saved under `save/showcase-check/`.

## Project layout

- `src/iron_and_snow/game.py` — story, Pygame loop, combat, HUD, chapter flow.
- `src/iron_and_snow/npc.py` — persistent dialogue, council proposals, local speech recognition and TTS.
- `src/iron_and_snow/director.py`, `control.py`, `game_control.py` — Codex commanders and the game CLI.
- `src/iron_and_snow/armies.py`, `army_policy.py`, `policy_runner.py`, `navigation.py` — shared army logic and isolated executable policies.
- `src/iron_and_snow/combat.py`, `conversation.py` — shared combat rules and conversation camera staging.
- `src/iron_and_snow/assets/` — ten generated character sheets, a rotated arrow projectile, collidable snowy boulder and fallen-pine terrain, battlefield art, music, and sound effects.
- `src/iron_and_snow/characters/` — Markdown character backgrounds and behavior profiles.
- `src/iron_and_snow/story.md` — campaign narrative and branching outcomes.
- `save/` — local generated voice audio and save data.
- `__old/` — original standalone learning scripts and their original assets, retained for reference.

## Development

```powershell
uv sync
uv run python -m iron_and_snow.game
```

Generated art is stored under `src/iron_and_snow/assets/`. The old knight/slime assets and their original prototypes are preserved under `__old/`.
# Voice model GPU check

The game project keeps speech inference dependencies in an optional `voice-gpu`
group so the core game environment does not need to download the CUDA runtime.
On Windows, run the setup and sample check from PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_and_check_voice_gpu.ps1
```

The process-scoped policy change applies only to the current PowerShell window
and does not require administrator privileges. It resets when that window closes.

The first run installs the optional dependencies and downloads the Kokoro FP32
model (about 326 MB), voice file, and multilingual Whisper `tiny` under the ignored
`save/voice-gpu-check/` directory. FP32 is the default because it was much
faster on CUDA on the test laptop; use `--tts-precision int8` to benchmark the
smaller int8 model.
Models load before timing begins. The script warms them up, then reports
repeated TTS and STT timings with median latency and real-time factors. Model
load time is shown separately. To run a five-second microphone test:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_and_check_voice_gpu.ps1 --mic
```

The script shows a three-second countdown before recording locally. To change
the recording length, pass `--record-seconds 8`. To compare inference on the
CPU, run the same command with `--device cpu`; use `--tts-precision fp32` for
the same model in both runs.

To test a WAV recording instead:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_and_check_voice_gpu.ps1 --audio "C:\path\to\recording.wav"
```

To compare Whisper on CPU, pass `--device cpu`. The setup script installs the
CUDA-enabled ONNX Runtime after `uv sync`; this is needed because Kokoro lists
CPU and GPU ONNX Runtime distributions that share the same Python package files.

The standard `scripts/run_game.ps1` launcher also preloads Kokoro and
multilingual Whisper during startup, using the same GPU setup and prepared
model directory as the voice check. Character-specific Kokoro voices are
selected from the Markdown profiles. The game keeps the online voice services
as fallbacks if local model startup fails.

