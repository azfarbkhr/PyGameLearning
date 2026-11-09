"""The game's two persistent Codex sessions: one per faction."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import threading
import time


class BattleDirector:
    def __init__(self, root):
        self.root = Path(root)
        self.clients = {}
        self.sessions = {}
        self.busy = {"allies": False, "enemies": False}
        self.last_request = {"allies": -1000, "enemies": -1000}
        self.status = {"allies": "waiting for battlefield", "enemies": "waiting for battlefield"}
        self.lock = threading.Lock()
        self.pending = {}
        self.closed = False
        self.offline = os.getenv("IRON_SNOW_OFFLINE") == "1"
        self.ready = {"allies": threading.Event(), "enemies": threading.Event()}
        self.session_locks = {"allies": threading.RLock(), "enemies": threading.RLock()}
        self.active_turns = {"allies": None, "enemies": None}
        self.cancelled_requests = set()
        self.started = False

    def start(self):
        """Create and warm exactly two faction sessions in background threads."""
        with self.lock:
            if self.started or self.closed or self.offline:
                return
            self.started = True
            self.status = {"allies": "warming Codex session", "enemies": "warming Codex session"}
        for side in ("allies", "enemies"):
            threading.Thread(target=self._start_side, args=(side,), daemon=True).start()

    def _start_side(self, side):
        try:
            from openai_codex import Codex, CodexConfig, Sandbox, ApprovalMode
            self.status[side] = "starting Codex client"
            client = Codex(CodexConfig(cwd=str(self.root)))
            skill = self.root / ".agents" / "skills" / "battlefield-control" / "SKILL.md"
            role = ("Two task types are sent. Always follow the CURRENT TASK label; never continue an earlier task. "
                    "For TASK: dialogue, do not call tools or issue game commands. Reply only in character as the ACTIVE CHARACTER. "
                    "If CURRENT GAME STATE phase is pre_battle_council, reply with JSON only in this exact shape: "
                    "{\"reply\":\"short spoken tactical suggestion\",\"orders\":[{\"target\":\"sansa stark\",\"action\":\"cover\"}]}. "
                    "Council allowed targets: sansa stark, tormund, wun wun, archers, northmen, team. Allowed actions: follow, cover, focus, "
                    "target_archers, flank_left, flank_right, hold, retreat. At most three proposals; Jon must accept them. "
                    "Keep dialogue concise, natural, and consistent with the active Markdown character card. "
                    "For TASK: battlefield command, use the skill and CLI to direct living units to win while preserving allies. "
                    "Jon's spoken instructions and accepted council plans are authoritative; do not speak or edit files during command tasks." if side == "allies" else
                    "Two task types are sent. Always follow the CURRENT TASK label; never continue an earlier task. "
                    "For TASK: dialogue, do not call tools or issue game commands. Speak only as Ramsay Bolton, in character, with a concise natural line. "
                    "For TASK: battlefield command, use the skill and CLI to direct living Bolton units to win while preserving their lives when useful. "
                    "Only battlefield command tasks may update the shared generic NPC policy. Never create per-character Python files.")
            self.status[side] = "creating faction session"
            session = client.thread_start(
                model="gpt-6-luna", cwd=str(self.root), sandbox=Sandbox.workspace_write,
                config={"windows": {"sandbox": "unelevated"},
                        "sandbox_workspace_write": {"writable_roots": [str(self.root / "save" / "game-control")]}}
                       if os.name == "nt" else None,
                approval_mode=ApprovalMode.auto_review,
                developer_instructions=(skill.read_text(encoding="utf-8") + "\n" + role +
                    f" Invoke CLI with the absolute Python executable {sys.executable!r}. Use model gpt-6-luna with low effort. "
                    "Keep event prompts concise, use only the supplied game state for dialogue, and never invent events."),
            )
            self.clients[side] = client
            self.sessions[side] = session
            # A tiny no-tools turn warms model/session startup before play.
            self.status[side] = "warming faction model"
            with self.session_locks[side]:
                session.run("Startup warm-up. Reply with READY only; do not use tools or edit files.",
                            model="gpt-6-luna", effort="low")
            self.status[side] = "Codex session ready"
        except Exception as exc:
            self.status[side] = "Codex commander unavailable: " + str(exc)[:150]
        finally:
            self.ready[side].set()

    def run_turn(self, side, payload, *, request_id=None, effort="low"):
        """Run dialogue on the same persistent faction thread as its commander."""
        if side not in self.sessions and not self.ready[side].wait(timeout=90):
            raise RuntimeError(f"Codex {side} session did not finish warming up")
        if side not in self.sessions:
            raise RuntimeError(self.status[side])
        with self.session_locks[side]:
            if request_id in self.cancelled_requests:
                self.cancelled_requests.discard(request_id)
                raise InterruptedError("Dialogue was superseded")
            turn = self.sessions[side].turn(payload, model="gpt-6-luna", effort=effort)
            with self.lock:
                self.active_turns[side] = (request_id, turn)
            try:
                return turn.run()
            finally:
                with self.lock:
                    if self.active_turns[side] and self.active_turns[side][1] is turn:
                        self.active_turns[side] = None
                    self.cancelled_requests.discard(request_id)

    def cancel_dialogue(self, side, request_id):
        if side not in self.active_turns or request_id is None:
            return
        with self.lock:
            self.cancelled_requests.add(request_id)
            active = self.active_turns[side]
        if active and active[0] == request_id:
            def interrupt():
                try:
                    active[1].interrupt()
                except Exception:
                    pass
            threading.Thread(target=interrupt, daemon=True).start()

    def request(self, side, reason, force=False):
        now = time.monotonic()
        with self.lock:
            if force and self.busy[side]:
                self.pending[side] = reason
            if self.closed or self.offline or self.busy[side] or (not force and now - self.last_request[side] < 14):
                return False
            self.busy[side] = True
            self.last_request[side] = now
            self.status[side] = "Codex observing and commanding"
        def work():
            try:
                if not self.ready[side].is_set() and not self.ready[side].wait(timeout=30):
                    raise RuntimeError(f"Codex {side} session did not finish warming up")
                if side not in self.sessions:
                    raise RuntimeError(self.status[side])
                with self.session_locks[side]:
                    result = self.sessions[side].run(
                        f"TASK: battlefield command\nEvent: {reason}. Observe the current {side} situation using the CLI. "
                        "Command living units to win while preserving their lives. If recurring behavior needs improvement, "
                        "publish one efficient shared policy candidate. If the battle changed, use the latest snapshot. "
                        "Do useful game actions now and verify their receipts.", model="gpt-6-luna", effort="low")
                self.status[side] = (result.final_response or "No commander report").strip()[:240]
                trace = self.root / "save" / "game-control" / f"director-{side}.json"
                import json
                trace.write_text(json.dumps({"status": self.status[side], "items": [item.model_dump(mode="json") for item in result.items]}, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                self.status[side] = "Codex commander unavailable: " + str(exc)[:150]
            finally:
                with self.lock:
                    self.busy[side] = False
                    pending = self.pending.pop(side, None)
                if pending and not self.closed:
                    self.request(side, pending, force=True)
        threading.Thread(target=work, daemon=True).start()
        return True

    def close(self):
        self.closed = True
        for active in self.active_turns.values():
            if active:
                try:
                    active[1].interrupt()
                except Exception:
                    pass
        for client in list(self.clients.values()):
            try:
                client.close()
            except Exception:
                pass
