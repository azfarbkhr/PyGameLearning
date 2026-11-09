"""Run editable policies outside Pygame; retain the last good policy on errors."""
from __future__ import annotations

import importlib.util
import math
import multiprocessing
from pathlib import Path
import time

ALLOWED = {"attack", "heavy", "feint", "dodge", "guard", "shoot", "retreat", "recover", "advance", "hold"}
DEFAULT_POLICY = Path(__file__).with_name("army_policy.py")


def _load(path):
    spec = importlib.util.spec_from_file_location("live_army_policy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "decide_actor", None)):
        raise ValueError("Missing decide_actor(unit, world, profile)")
    return module.decide_actor


def _worker(connection):
    good_path = str(DEFAULT_POLICY)
    good = _load(good_path)
    while True:
        try:
            message = connection.recv()
        except (EOFError, OSError):
            break
        if message is None:
            break
        job, candidate, units, world = message
        started = time.perf_counter()
        try:
            decide = _load(candidate) if candidate and candidate != good_path else good
            decisions = {}
            for unit in units:
                result = decide(unit, world, unit.get("profile", ""))
                if not isinstance(result, dict) or result.get("action") not in ALLOWED:
                    raise ValueError("Policy returned an unknown action")
                point = result.get("point")
                if point is not None and not (isinstance(point, (list, tuple)) and len(point) == 2
                        and all(isinstance(v, (int, float)) and math.isfinite(v) for v in point)):
                    raise ValueError("Policy returned an invalid destination")
                decisions[unit["id"]] = {"action": result["action"], "point": point,
                                          "reason": str(result.get("reason", ""))[:160]}
            elapsed = time.perf_counter() - started
            if elapsed > .08:
                raise ValueError(f"Policy batch exceeded the 80ms thinking budget ({elapsed:.3f}s)")
            if candidate:
                good, good_path = decide, candidate
            connection.send((job, decisions, good_path, None, elapsed))
        except Exception as exc:
            connection.send((job, {}, good_path, str(exc), time.perf_counter() - started))


class PolicyRunner:
    def __init__(self):
        self.process = None
        self.connection = None
        self.pending = None
        self.sequence = 0
        self.candidate = None
        self.good_path = str(DEFAULT_POLICY)
        self.backup_path = str(DEFAULT_POLICY)
        self.decisions = {}
        self.status = "baseline survival policy"
        self.last_submit = 0.0

    def publish(self, path):
        self.candidate = str(path)
        self.status = "validating candidate " + Path(path).stem

    def discard_worker(self, message):
        failed_path = self.pending[2] if self.pending else None
        self.close()
        if failed_path == self.good_path:
            # A formerly good policy can fail on a new state. A new candidate
            # failing must leave the current good version untouched.
            self.good_path = self.backup_path
        self.candidate = None
        self.decisions.clear()
        self.status = message + "; last working behavior retained"

    def tick(self, units, world):
        now = time.monotonic()
        if self.process and not self.process.is_alive():
            self.discard_worker("policy worker exited")
        if self.pending and now - self.pending[1] > (4 if self.pending[0] == 1 else .6):
            self.discard_worker("slow policy rejected")
        if self.connection and self.connection.poll():
            submitted_path = self.pending[2] if self.pending else None
            try:
                _, decisions, good, error, elapsed = self.connection.recv()
            except (EOFError, OSError):
                self.discard_worker("policy worker disconnected")
                return
            self.pending = None
            if error:
                if self.candidate == submitted_path:
                    self.candidate = None
                self.status = "policy rejected: " + error[:100]
            else:
                self.decisions = decisions
                if good != self.good_path:
                    self.backup_path = self.good_path
                    self.good_path = good
                if self.candidate == good:
                    self.candidate = None
                self.status = f"{Path(good).stem} · {elapsed * 1000:.1f}ms / {len(units)} units"
        if self.pending or now - self.last_submit < .2:
            return
        if not self.process:
            context = multiprocessing.get_context("spawn")
            parent, child = context.Pipe()
            self.connection = parent
            self.process = context.Process(target=_worker, args=(child,), daemon=True)
            self.process.start()
            child.close()
            self.sequence = 0
        self.sequence += 1
        submitted_path = self.candidate or self.good_path
        try:
            self.connection.send((self.sequence, submitted_path, units, world))
        except (OSError, BrokenPipeError):
            self.discard_worker("policy worker disconnected")
            return
        self.pending = (self.sequence, now, submitted_path)
        self.last_submit = now

    def close(self):
        if self.process:
            self.process.terminate()
            self.process.join(timeout=.15)
            self.process = None
        if self.connection:
            self.connection.close()
            self.connection = None
        self.pending = None
