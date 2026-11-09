"""Behavioral integration checks and a headless host for the game CLI."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", type=float, default=0, help="Host an offline battle for N seconds for external CLI/Codex checks")
    args = parser.parse_args()
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    os.environ["IRON_SNOW_OFFLINE"] = "1"
    import pygame
    from .game import Game, PLANNING_START_RECT, PLANNING_APPLY_RECT, PLANNING_RESET_RECT
    from .control import publish_policy
    from .navigation import Navigator

    game = Game()
    try:
        game.begin_planning(1)
        game.draw()
        output = Path("save/showcase-check")
        output.mkdir(parents=True, exist_ok=True)
        pygame.image.save(game.canvas, output / "council.png")
        live_conversation = output / 'live-conversation-report.json'
        if live_conversation.exists():
            recorded = json.loads(live_conversation.read_text(encoding='utf-8'))[0]
            game.send_player_line('Sansa, propose a plan: cover me while Tormund takes the left flank.',voice=True)
            recorded['request_id'] = game.latest_dialogue_request_id
            game.ai.result_queue.put(recorded)
            game._poll_ai_and_voice()
            game.draw()
            pygame.image.save(game.canvas, output / 'council-recorded-live-reply.png')
        panel = pygame.Rect(80, 42, 940, 616)
        assert all(panel.contains(r) for r in (PLANNING_START_RECT, PLANNING_APPLY_RECT, PLANNING_RESET_RECT))
        assert not PLANNING_START_RECT.colliderect(PLANNING_RESET_RECT)
        assert game.sansa_sprite.portrait_source.get_height() > game.sansa_sprite.frames['idle'][0].get_height() * .38
        print("PASS council buttons fit their panel and use source-resolution portraits", flush=True)
        prepared = [a.uid for a in game.enemies]
        battle_id = game.control.battle_id
        game.planning_suggestion = [{'target': 'sansa stark', 'action': 'hold', 'point': [400, 800]},
                                   {'target': 'tormund', 'action': 'flank_left'}]
        game.apply_planning_suggestion()
        screen_w,screen_h=game.screen.get_size()
        click=(round(PLANNING_START_RECT.centerx*screen_w/1100),round(PLANNING_START_RECT.centery*screen_h/700))
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=click))
        game.handle_events()
        assert game.state=='battle'
        sansa = next(a for a in game.allies if a.name == 'Sansa Stark')
        assert game.armies.order(sansa)['action'] == 'hold'
        assert game.armies.order(sansa)['point'] == [400,800]
        assert prepared == [a.uid for a in game.enemies] and game.control.battle_id == battle_id
        game.team_strategy={'default':'follow','assignments':{'archers':'cover'}}
        assert game.order_for_ally(sansa)=='cover'
        game.team_strategy = {'default': 'follow', 'assignments': {}}
        print('PASS accepted council plan reaches real units without respawning the prepared army',flush=True)
        for chapter, expected in ((1, 11), (2, 9), (3, 6)):
            game.start_battle(chapter)
            assert len(game.enemies) == expected, (chapter, len(game.enemies))
            for expected_wave in ({1:[7],2:[7],3:[6,1]}[chapter]):
                game.enemies=[]
                game.spawn_next_wave()
                assert len(game.enemies)==expected_wave,(chapter,game.chapter_wave,len(game.enemies))
        game.start_battle(1)
        game.control.tick(game, force=True)
        if args.serve:
            # Live CLI checks can act on the full army while the host pumps frames.
            game.conversation.start(game.player, game.commander)
            game.ai.listening = True
            game.ai.speech_state = "listening"
            deadline = time.monotonic() + args.serve
            print("HEADLESS_GAME_READY", flush=True)
            while time.monotonic() < deadline:
                game.conversation.started = time.monotonic()
                game.update(1 / 60)
                game.draw()
                time.sleep(1 / 60)
            return 0
        print("PASS original guard counts retained in every chapter", flush=True)
        command = [sys.executable, '-m', 'iron_and_snow.control', '--wait', '2', 'order', '--side', 'enemies',
                   '--units', 'archers', '--action', 'hold', '--reason', 'Keep bowmen behind the line']
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        while process.poll() is None:
            game.control.tick(game, force=True)
            time.sleep(.02)
        stdout, stderr = process.communicate()
        assert process.returncode == 0, (stdout, stderr)
        receipt = json.loads(stdout)
        assert receipt['status'] == 'applied', receipt
        assert all(a.control_order['action'] == 'hold' for a in game.enemies if a.ranged)
        print("PASS external CLI order receives an applied receipt from the running game", flush=True)
        # An old battle command cannot affect a new battle, and explicit player
        # orders protect their assigned unit while free allies remain commandable.
        from .control import atomic_json
        import uuid
        stale_id = uuid.uuid4().hex
        atomic_json(game.control.directory / 'commands' / (stale_id+'.json'),
                    {'kind':'order','id':stale_id,'side':'enemies','units':['all'],'action':'retreat',
                     'run_id':game.control.run_id,'battle_id':'old-battle','created_at':time.time()})
        game.control.tick(game,force=True)
        stale = json.loads((game.control.directory / 'receipts' / (stale_id+'.json')).read_text())
        assert stale['status']=='rejected'
        game.team_strategy['assignments']['sansa stark']='cover'
        sansa = next(a for a in game.allies if a.name == 'Sansa Stark')
        detail = game.control.apply(game,{'kind':'order','side':'allies','units':['all'],'action':'hold','duration':10})
        assert sansa.uid not in detail['units']
        game.control.latest_ally_instruction={'id':'current-instruction','text':'Sansa, fall back now','at':time.time()}
        game.control.apply(game,{'kind':'order','side':'allies','units':[sansa.uid],'action':'retreat',
                                'duration':10,'source':'codex','instruction':'current-instruction'})
        assert game.armies.order(sansa)['action']=='retreat'
        game.control.latest_ally_instruction={'id':'newer-instruction','text':'Sansa, cover me again','at':time.time()}
        assert game.armies.order(sansa)['action']=='cover'
        game.team_strategy={'default':'follow','assignments':{}}
        print('PASS stale commands rejected and player assignments protected',flush=True)

        # Actual combat timing and resource use: damage only when the blade lands.
        enemy = game.enemies[0]
        enemy.pos.update(650, 850); game.player.pos.update(590, 850)
        game.player.facing.update(1, 0)
        health = enemy.health
        assert game.attack(enemy)
        assert enemy.health == health
        game.combat_time += .23
        game.combat.update(.23)
        assert enemy.health == health - 18, (health, enemy.health)
        assert game.player.stamina < 100
        print("PASS sword hit has a windup and consumes stamina", flush=True)
        # A dodge before the committed strike prevents the hit.
        game.player.attack_cooldown = 0; game.player.stamina = 100
        enemy.invulnerable = 0; enemy.pos.update(650, 850)
        assert game.attack(enemy, kind='heavy')
        assert game.combat.dodge(enemy, (0, 1))
        for _ in range(35):
            game.combat_time += 1 / 60
            game.combat.update(1 / 60)
            enemy.invulnerable = max(0, enemy.invulnerable - 1 / 60)
        assert enemy.health == health - 18
        print("PASS sidestep avoids the committed overhead strike", flush=True)

        # A late timed guard parries; a feint spends stamina without damage.
        game.player.attack_cooldown = 0; game.player.stamina = 100
        game.player.pos.update(590, 850); game.player.facing.update(1, 0)
        enemy.pos.update(650, 850); enemy.attack_cooldown = 0; enemy.stamina = 100
        enemy.invulnerable = 0; enemy.dodge_until = 0
        assert game.combat.begin(enemy, game.player)
        game.combat_time += .13
        assert game.defend()
        before_health = game.player.health
        game.combat_time += .10
        game.combat.update(.10)
        assert game.player.health == before_health and enemy.stagger_until > game.combat_time
        game.player.attack_cooldown = 0; game.player.stamina = 100
        before_health = enemy.health
        assert game.attack(enemy, kind='feint')
        game.combat_time += .3; game.combat.update(.3)
        assert enemy.health == before_health
        print("PASS timed parry creates a counter opening and feints do no phantom damage", flush=True)

        # Heavy blows can break a committed guard using the shared posture rules.
        game.player.attack_cooldown = 0; game.player.stamina = 100
        enemy.health = 100; enemy.max_health = 100; enemy.invulnerable = 0
        enemy.stagger_until = 0; enemy.block_time = 1; enemy.block_perfect_time = 0
        enemy.posture = 80; enemy.stamina = 100; enemy.facing.update(-1, 0)
        assert game.attack(enemy, kind='heavy')
        game.combat_time += .58; game.combat.update(.58)
        assert enemy.stagger_until > game.combat_time and enemy.health < 70
        print("PASS overhead attack breaks posture and has a meaningful recovery cost", flush=True)

        game.player.pos.update(150, 850)
        enemy.health = enemy.max_health * .2; enemy.pos.update(260, 850)
        enemy.stagger_until = 0; enemy.block_time = 0; enemy.pending_strike = None
        for ally in game.allies:
            ally.pos.update(50, 1000)
        before = enemy.pos.distance_to(game.player.pos)
        for _ in range(50):
            game.combat_time += .016
            game.armies.update(.016)
            game.combat.update(.016)
        assert enemy.pos.distance_to(game.player.pos) > before + 20
        print("PASS wounded guard withdraws instead of charging Jon", flush=True)

        navigator = Navigator([pygame.Rect(400, 700, 180, 200)])
        path = navigator.path((300, 800), (700, 800))
        assert path
        assert all(not pygame.Rect(400, 700, 180, 200).inflate(40, 40).collidepoint(p) for p in path)
        print("PASS pathfinding routes around physical cover", flush=True)
        # Allies do not inherit the player's movement vector.
        for foe in game.enemies:
            foe.pos.x = 2500
        for ally in game.allies:
            if hasattr(ally,'control_order'): ally.control_order = {}
        game.armies.reset()
        positions = [a.pos.copy() for a in game.allies]
        game.player.pos.x += 65
        for _ in range(20):
            game.combat_time += .016
            game.armies.update(.016)
        assert all(a.pos.distance_to(p)<15 for a,p in zip(game.allies,positions))
        print('PASS nearby idle allies hold their own positions when Jon moves',flush=True)

        # Cinematic UI and camera continue while combat time stays frozen.
        game.ai.listening = True; game.ai.speech_state = 'listening'
        game.conversation.start(game.player, game.commander)
        before_time = game.combat_time
        for _ in range(30): game.update(1 / 60)
        assert game.combat_time == before_time
        game.ai.speech_state = 'transcribing'
        before_distance = game.conversation.focus.distance_to(game.commander.pos)
        for _ in range(60): game.update(1 / 60)
        assert game.conversation.focus.distance_to(game.commander.pos) < before_distance * .2
        game.draw()
        pygame.image.save(game.canvas, output / 'conversation.png')
        game.ai.listening = False
        from unittest.mock import patch
        game.conversation.finish()
        with patch('time.monotonic', return_value=game.conversation.return_at+1.1):
            game.conversation.update(game,1/60)
        assert not game.conversation.active and game.conversation.zoom==1
        print("PASS battle pauses and camera shifts from Jon to the responding commander", flush=True)
        game.send_player_line('Keep watching the flank.',voice=True)
        pending=game.dialogue[-1]
        game.dismiss_conversation()
        game.ai.result_queue.put({'request_id':pending['request_id'],'text':'A stale reply',
                                  'character':'tormund_giantsbane','source':'codex','orders':[]})
        game._poll_ai_and_voice()
        assert pending['source']=='interrupted' and pending['text']=='Conversation ended.'
        print('PASS interrupted reply is discarded and the camera returns to normal',flush=True)

        # Publish real executable code and observe it becoming the active worker policy.
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / 'candidate.py'
            candidate.write_text('def decide_actor(unit, world, profile):\n    return {"action": "guard", "reason": "Preserve the line"}\n')
            version = publish_policy(candidate)
            game.armies.publish_policy(game.control.directory / 'policies' / (version + '.py'))
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                game.armies.think_at = 0
                game.combat_time += .02
                game.armies.update(.02)
                if version in game.armies.policy_status:
                    break
                time.sleep(.025)
            assert version in game.armies.policy_status, game.armies.policy_status
            assert game.armies.runner.decisions
            print("PASS shared executable policy activates outside the render process", flush=True)
        game.draw()
        pygame.image.save(game.canvas, output / 'battle.png')

        # Load proof for a larger army, preserving the standard game's composition.
        game.armies.close()
        from .policy_runner import PolicyRunner
        game.armies.runner = PolicyRunner()
        game.start_battle(1)
        for index in range(69):
            game.enemies.append(game.new_enemy(600 + (index % 10) * 180,
                                               660 + (index // 10) * 56, 'Bolton soldier'))
        game.player.invulnerable = 1000
        live_report = output / 'live-codex-report.json'
        if live_report.exists():
            live = json.loads(live_report.read_text(encoding='utf-8'))
            live_version = live.get('active_policy','').split(' ')[0]
            live_policy = game.control.directory / 'policies' / (live_version+'.py')
            if live_policy.exists():
                game.armies.publish_policy(live_policy)
                deadline=time.monotonic()+5
                while time.monotonic()<deadline and live_version not in game.armies.policy_status:
                    game.armies.think_at=0
                    game.armies.update(.01)
                    time.sleep(.02)
                assert live_version in game.armies.policy_status
        durations = []
        for frame in range(120):
            started = time.perf_counter()
            game.update(1 / 60)
            game.draw()
            durations.append((time.perf_counter() - started) * 1000)
        measured = sorted(durations[20:])
        perf = {'initial_enemies': 80, 'median_frame_ms': measured[len(measured)//2],
                'p95_frame_ms': measured[round(len(measured)*.95)-1], 'frames': len(durations),
                'policy':game.armies.policy_status}
        (output / 'performance.json').write_text(json.dumps(perf,indent=2),encoding='utf-8')
        assert perf['p95_frame_ms'] < 60, perf
        print('PASS 80-enemy stress scene: ' + json.dumps(perf),flush=True)

        # A hanging candidate must never hang the render/update loop.
        with tempfile.TemporaryDirectory() as temporary:
            bad = Path(temporary) / 'slow.py'
            previous_good = game.armies.runner.good_path
            bad.write_text('def decide_actor(unit, world, profile):\n    while True: pass\n')
            version = publish_policy(bad)
            game.armies.publish_policy(game.control.directory / 'policies' / (version + '.py'))
            deadline = time.monotonic() + 6
            rejected = False
            while time.monotonic() < deadline:
                game.combat_time += .1
                game.armies.update(.02)
                if 'slow policy rejected' in game.armies.policy_status:
                    rejected = True
                    break
                time.sleep(.015)
            assert rejected, game.armies.policy_status
            assert version not in game.armies.runner.good_path
            assert game.armies.runner.good_path == previous_good
        print('PASS runaway generated script is terminated and last good policy retained',flush=True)
        return 0
    finally:
        game.armies.close()
        game.director.close()
        game.ai.close()
        pygame.quit()


if __name__ == '__main__':
    raise SystemExit(main())
