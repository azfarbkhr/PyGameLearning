"""Verify a real Codex commander against a running headless full-army host."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .control import CONTROL_DIR, read_snapshot
from .director import BattleDirector


def main():
    root = Path(__file__).resolve().parents[2]
    output = root / "save" / "showcase-check"
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, IRON_SNOW_OFFLINE="1", PYTHONUNBUFFERED="1")
    log = (output / "live-host.log").open("w", encoding="utf-8")
    host = subprocess.Popen([sys.executable, "-m", "iron_and_snow.check_showcase", "--serve", "160"],
                            cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT)
    director = BattleDirector(root)
    director.start()
    started = time.monotonic()
    try:
        warm_deadline = time.monotonic() + 100
        while time.monotonic() < warm_deadline and not all(event.is_set() for event in director.ready.values()):
            time.sleep(.05)
        assert all(event.is_set() for event in director.ready.values()), director.status
        assert len(director.sessions) == 2, director.sessions.keys()
        print("Exactly two faction Codex sessions prewarmed.", flush=True)
        all_applied = []
        deadline = started + 15
        while time.monotonic() < deadline:
            try:
                snapshot = read_snapshot()
                if snapshot["phase"] == "battle" and (output / "live-host.log").read_text(encoding="utf-8").find("HEADLESS_GAME_READY") >= 0:
                    break
            except (OSError, ValueError):
                pass
            if host.poll() is not None:
                raise RuntimeError("Headless game exited; inspect live-host.log")
            time.sleep(.1)
        else:
            raise RuntimeError("Headless game did not become ready")
        assert len([u for u in snapshot['units'] if u['side']=='enemies']) == 11
        print("Requesting real Codex enemy commander; full army is live.", flush=True)
        director.request("enemies", "Integration check: observe the live army, give a useful group order through the CLI, "
                         "then verify its applied receipt. Do not speak or edit a policy for this first connection check.", force=True)
        deadline = time.monotonic() + 130
        last_notice = time.monotonic()
        while director.busy['enemies'] and time.monotonic() < deadline:
            if time.monotonic() - last_notice > 20:
                print("Codex commander still running; host heartbeat remains live.", flush=True)
                read_snapshot()
                last_notice = time.monotonic()
            time.sleep(.2)
        final = read_snapshot()
        applied = [e for e in final['events'] if e.get('event')=='command_applied' and e.get('source')=='codex']
        all_applied.extend(applied)
        if applied and not director.busy['enemies']:
            print("Codex order applied. Requesting a real shared-policy publication next.", flush=True)
            director.request("enemies", "Integration check stage two: inspect src/iron_and_snow/army_policy.py, "
                             "write an efficient generic candidate under save/game-control/candidate.py with a "
                             "survival improvement for wounded melee soldiers while preserving archery, feints, "
                             "dodges, and both factions. Publish it with the CLI policy command. Observe until "
                             "the policy hash is active rather than merely validating. No speech.", force=True)
            deadline = time.monotonic() + 95
            while director.busy['enemies'] and time.monotonic() < deadline:
                time.sleep(.2)
            final = read_snapshot()
            applied = [e for e in final['events'] if e.get('event')=='command_applied' and e.get('source')=='codex']
            all_applied.extend(applied)
            print('Shared policy inspected. Checking the allied commander session next.',flush=True)
            director.request('allies','Integration check: prepare the free allied troops for the full enemy army. '
                             'Use the CLI to give at least one useful group order and verify an applied receipt. '
                             'Sansa is an archer and Tormund leads the infantry. Preserve any explicit player orders. '
                             'Do not speak or publish a policy.',force=True)
            deadline=time.monotonic()+60
            while director.busy['allies'] and time.monotonic()<deadline:
                time.sleep(.2)
            final=read_snapshot()
            applied=[e for e in final['events'] if e.get('event')=='command_applied' and e.get('source')=='codex']
            all_applied.extend(applied)
        report = {'elapsed_seconds': round(time.monotonic()-started,2), 'session_count': len(director.sessions),
                  'session_status': dict(director.status), 'status': director.status['enemies'],
                  'codex_commands_applied': all_applied, 'active_policy': final.get('policy'),
                  'allied_status':director.status['allies'],
                  'remaining_enemies': len([u for u in final['units'] if u['side']=='enemies'])}
        (output / 'live-codex-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2),flush=True)
        sides={event.get('side') for event in all_applied if event.get('kind')=='order'}
        return 0 if sides=={'allies','enemies'} and not any(director.busy.values()) and 'army_policy' not in final.get('policy', '') else 1
    finally:
        director.close()
        host.terminate()
        try:
            host.wait(timeout=5)
        except subprocess.TimeoutExpired:
            host.kill()
        log.close()


if __name__ == '__main__':
    raise SystemExit(main())
