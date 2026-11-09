"""Capture unaltered frames from a normal offline first battle for the reel."""
from __future__ import annotations

import os
import json
import queue
from pathlib import Path
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["IRON_SNOW_OFFLINE"] = "1"

import pygame
from iron_and_snow.game import Game


def main() -> None:
    output = Path(__file__).resolve().parent / "captures"
    output.mkdir(parents=True, exist_ok=True)
    game = Game()
    try:
        game.start_battle(1)
        elapsed = 0.0
        for target in (0.0, 3.0, 6.0, 9.0):
            while elapsed < target:
                game.update(1 / 60)
                game.draw()
                time.sleep(1 / 60)
                elapsed += 1 / 60
            game.draw()
            filename = output / f"battle-{int(target):02d}s.png"
            pygame.image.save(game.canvas, filename)
            print(f"{filename.name}: state={game.state}, allies={len(game.allies)}, "
                  f"enemies={len(game.enemies)}, player_health={game.player.health}", flush=True)

        # Exercise the game's supported T-order route in its normal chapter-one scene.
        game.start_battle(1)
        game.issue_team_order("Attack their archers")
        game.draw()
        pygame.image.save(game.canvas, output / "spoken-order-ui.png")

        # Show a genuine saved Ramsay reply inside the ordinary battle camera/UI.
        game.start_battle(1)
        game.ai.select_character("ramsay_bolton")
        game.conversation.start(game.player, game.commander)
        report = Path("save/showcase-check/live-conversation-report.json")
        if report.exists():
            turns = json.loads(report.read_text(encoding="utf-8"))
            recorded = next(item for item in turns if item.get("turn") == "enemy")
            game.send_player_line("Your men pulled back when I broke their guard. Will you send them back?", voice=True)
            recorded["request_id"] = game.latest_dialogue_request_id
            # The offline game's local fallback is queued synchronously by
            # send_player_line. Replace it with the saved real Codex response.
            while True:
                try:
                    game.ai.result_queue.get_nowait()
                except queue.Empty:
                    break
            game.ai.result_queue.put(recorded)
            game._poll_ai_and_voice()
            game.draw()
            pygame.image.save(game.canvas, output / "ramsay-reply-ui.png")
    finally:
        game.armies.close()
        game.director.close()
        game.ai.close()
        pygame.quit()


if __name__ == "__main__":
    main()
