"""Verify real council and teammate replies without recording a microphone."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
import argparse
import re
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-voice', action='store_true', help='Also synthesize and decode responses with the existing game voice backend')
    parser.add_argument('--interrupt-only', action='store_true', help='Check interruption of a live Codex turn and a fresh follow-up')
    args = parser.parse_args()
    os.environ['IRON_SNOW_OFFLINE'] = '0'
    os.environ.setdefault('IRON_SNOW_TTS_BACKEND', 'kokoro' if args.with_voice else 'edge')
    os.environ.setdefault('IRON_SNOW_STT_BACKEND', 'google')
    from .npc import CodexNPC
    from .director import BattleDirector
    root = Path(__file__).resolve().parents[2]
    director = BattleDirector(root)
    director.start()
    npc = CodexNPC(root, director=director)
    report = []
    try:
        warm_deadline = time.monotonic() + 100
        next_warm_log = 0.0
        while time.monotonic() < warm_deadline and not all(event.is_set() for event in director.ready.values()):
            if time.monotonic() >= next_warm_log:
                print(json.dumps({"warming": director.status}), flush=True)
                next_warm_log = time.monotonic() + 5
            time.sleep(.05)
        if not all(event.is_set() for event in director.ready.values()):
            raise RuntimeError(f"Faction sessions did not warm: {director.status}")
        assert len(director.sessions) == 2, director.sessions.keys()
        npc.select_character('sansa_stark')
        if args.interrupt_only:
            state={'phase':'battle','channel':'team','chapter':'Battlefield','health':100}
            npc.send_player_line('Consider how we can protect every soldier while keeping the flank secure.',state,voice=True,request_id='obsolete')
            deadline=time.monotonic()+10
            while director.active_turns['allies'] is None and time.monotonic()<deadline:
                time.sleep(.005)
            assert director.active_turns['allies'] is not None
            started=time.monotonic()
            npc.cancel_dialogue()
            while npc.busy and time.monotonic()-started<10:
                time.sleep(.025)
            assert not npc.busy
            elapsed=time.monotonic()-started
            while npc.poll(): pass
            npc.send_player_line('Watch the archers and stay behind cover.',state,voice=True,request_id='fresh')
            deadline=time.monotonic()+20
            response=None
            while time.monotonic()<deadline:
                response=npc.poll()
                if response and response.get('request_id')=='fresh': break
                time.sleep(.025)
            assert response and response.get('source')=='codex',response
            result={'interrupt_seconds':round(elapsed,2),'followup':response}
            (root/'save/showcase-check/live-interruption-report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps(result),flush=True)
            return 0
        if args.with_voice:
            os.environ['SDL_AUDIODRIVER'] = 'dummy'
            import pygame
            pygame.mixer.init()
        cases = [
            ('council', 'Sansa, propose a plan: cover me while Tormund takes the left flank.',
             {'phase': 'pre_battle_council', 'chapter': 'Battlefield', 'health': 100,
              'team_strategy': {'default': 'follow', 'assignments': {}}}),
            ('team', 'Sansa, keep covering me. Which threat are you watching?',
             {'phase': 'battle', 'channel': 'team', 'chapter': 'Battlefield', 'health': 90,
              'team_strategy': {'default': 'follow', 'assignments': {'sansa stark': 'cover', 'tormund': 'flank_left'}}}),
            ('enemy', 'Your men pulled back when I broke their guard. Will you send them back?',
             {'phase': 'battle', 'channel': 'enemy', 'chapter': 'Battlefield', 'health': 90,
              'recent_battle_events': [{'event': 'guard_broken', 'actor': 'Jon Snow', 'target': 'Bolton soldier'}]}),
        ]
        for request_id, line, state in cases:
            npc.select_character('ramsay_bolton' if request_id == 'enemy' else 'sansa_stark')
            started = time.monotonic()
            npc.send_player_line(line, state, voice=True, request_id=request_id)
            deadline = started + 35
            result = None
            while time.monotonic() < deadline:
                result = npc.poll()
                if result and result.get('request_id') == request_id:
                    break
                time.sleep(.05)
            assert result and result.get('source') == 'codex', result or npc.last_error
            if request_id == 'council':
                assert result.get('orders'), result
            report.append({'turn': request_id, 'elapsed_seconds': round(time.monotonic()-started,2), **result})
            if args.with_voice:
                npc.cancel_speech()
                audio_started = time.monotonic()
                npc.speak(result['text'],character_slug=result['character'],request_id=request_id)
                audio = []
                deadline = audio_started + 25
                while time.monotonic() < deadline:
                    item = npc.poll_speech()
                    if item:
                        path = Path(item[0])
                        sound = pygame.mixer.Sound(str(path))
                        assert sound.get_length() > .1
                        audio.append({'path': str(path), 'duration': sound.get_length(),
                                      'ready_seconds': round(time.monotonic()-audio_started,2)})
                    if audio and not npc.tts_worker_active and npc.speech_queue.empty():
                        break
                    time.sleep(.025)
                expected = min(3,len(re.split(r'(?<=[.!?])\s+',result['text'].strip())))
                assert len(audio)==expected, (audio,npc.last_tts_error)
                report[-1]['audio_backend'] = npc.last_tts_backend_used
                report[-1]['audio'] = audio
            print(json.dumps(report[-1],ensure_ascii=False),flush=True)
        output = root / 'save' / 'showcase-check' / 'live-conversation-report.json'
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return 0
    finally:
        npc.close()
        director.close()
        if args.with_voice:
            pygame.mixer.quit()


if __name__ == '__main__':
    raise SystemExit(main())
