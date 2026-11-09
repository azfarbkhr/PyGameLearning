# AI game showcase tickets

Goal: demonstrate a playable, conversational battlefield whose armies are directed
by Codex through a CLI and skill, retaining the full existing enemy count.

| Ticket | Status | Completion evidence required |
| --- | --- | --- |
| AI-01 Game CLI and skill | Verified | Observe a running game; submit an order; receive an applied receipt; reject stale/invalid commands; validate the skill. |
| AI-02 Survival and Codex director | Verified | Live Codex issues army orders and publishes efficient shared policies; wounded NPCs withdraw; attackers coordinate; policy errors cannot stall the render loop. |
| AI-03 Two prewarmed faction sessions | Verified | Exactly two persistent Codex sessions are initialized and warmed at game startup; council/team dialogue, enemy dialogue, and faction movement orders share the matching session. |
| COMBAT-01 Expressive, fair combat | Verified | Quick/heavy attacks, dodge, parry, feint, stamina/posture, telegraphed hits and recovery; enemies use the same rules; balance checks. |
| MOVE-01 Natural allied movement | Verified | Independent role objectives, persistent destinations, pathfinding around obstacles, separation, acceleration and turning; no fixed position tether to Jon. |
| TALK-01 Cinematic conversation | Verified | Pause simulation; smoothly focus Jon while recording, then the addressed speaker; captions precede voice; interruption, timeout, and camera return work. |
| PLAN-01 Council polish | Verified | Sharp source-resolution portraits, contained aligned buttons, editable/reviewable orders, useful AI proposals and clear loading/response states. |
| DEMO-01 Showcase verification | Verified | Full-army integration/performance checks, live Codex CLI evidence, UI captures and a reproducible showcase sequence. |

## Verification record — 8 November 2026

- `python -m iron_and_snow.check_showcase`: passed behavioral checks for prepared
  council armies and persistent assignments; retained chapter enemy counts
  (11, 9, 6) and every reserve wave (7; 7; 6 plus Ramsay); real CLI receipts and stale-command rejection; player-order
  priority; delayed sword damage, stamina, parry, feint, overhead guard break,
  dodge, wounded-unit retreat, pathfinding and independent allied positioning;
  camera pause/focus/return; actual Start-button click mapping; obsolete-reply rejection; executable policy
  activation; runaway-policy termination retaining the exact last good version.
- `python -m iron_and_snow.check_live_director`: real signed-in Codex sessions
  observed and commanded both enemy and allied units through the CLI. Codex
  wrote and published shared policy `877283205cd380db`; a newer game snapshot
  confirmed that version active for 15 NPCs with all 11 enemy troops retained.
  Evidence: `save/showcase-check/live-codex-report.json`, plus the actual command
  traces under `save/game-control/director-*.json`.
- `python -m iron_and_snow.check_live_conversation --with-voice`: genuine council,
  team and Ramsay replies passed schema checks and produced decodable Kokoro
  speech. Measured model replies: 3.29s, 1.41s, 1.36s. First audio after text:
  1.39s, 1.03s, 0.52s. These are observed samples rather than promised latency.
  Evidence: `save/showcase-check/live-conversation-report.json`.
- `python -m iron_and_snow.check_live_conversation --interrupt-only`: interrupted
  a real in-flight Codex turn, then received a genuine fresh reply. Evidence:
  `save/showcase-check/live-interruption-report.json`.
- After the two-session refactor, `python -m iron_and_snow.check_live_conversation`
  passed council planning with structured proposals, ally dialogue, and Ramsay
  dialogue. Each response took about 2–3 seconds.
- After the two-session refactor, `python -m iron_and_snow.check_live_director`
  asserted exactly two warmed sessions, then applied enemy and allied orders
  and published a shared survival policy through those same sessions.
- 80-enemy headless render/update stress check using the actual Codex-written
  policy: 11.4ms median / 15.1ms p95 per frame over 120 frames; the shared
  policy worker reported 0.1ms for 84 NPCs. Evidence:
  `save/showcase-check/performance.json`. This is a scoped synthetic load check.
- Skill validation passed. Council and conversation captures were inspected:
  sharp source-resolution portraits, contained/aligned controls, readable
  dialogue/proposals, and smoothly softened focus staging.

These checks use headless gameplay and real model/synthesis calls. They do not
record the user's microphone or claim a manual full-campaign playthrough.
The screenshot `council-recorded-live-reply.png` replays a previously recorded
real model response; it is not a screenshot of a new live microphone exchange.

## Agreed constraints

- Preserve current hardware and local voice models.
- Preserve the full army and existing chapter/wave compositions.
- One generic NPC implementation; character traits and story remain in Markdown.
- Codex owns tactical decisions and can publish shared executable policies;
  continuous movement, animation, collision and timing execute locally.
- Dialogue, council strategy and both enemy/team speech remain core features.
- Test the requested outcome rather than claiming success from syntax checks.

## Research applied

- [Epic: event-driven behavior trees](https://dev.epicgames.com/documentation/en-us/unreal-engine/behavior-tree-in-unreal-engine---overview): blackboard state and event-triggered reconsideration avoid full reasoning every frame.
- [Official Codex SDK](https://learn.chatgpt.com/docs/codex-sdk): persistent sessions retain each faction's context across planning, dialogue, and commander turns.
- [OpenAI latency optimization](https://developers.openai.com/api/docs/guides/latency-optimization): minimize generated output, parallelize independent work, chunk user-visible results, and use clear progress states. Applied here through two independently warmed faction sessions, compact army summaries, short replies, sentence-level audio generation and cancellation.
- Conversation presentation will use anticipation/turn-taking animation, explicit
  listener focus, immediate captions, cancellation of stale speech, and staged
  camera motion while asynchronous work completes. These are implementation
  choices, not claims that model inference has become instantaneous.
