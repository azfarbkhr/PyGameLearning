"""Run with: uv run python live_box_poc.py

Leave the window open and edit get_velocity() below. Save this file to apply
the change without restarting. Only that function is reloaded; keep its logic
self-contained. The rest of this file owns the window and persistent state.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path
import time

import pygame


# EDIT THIS FUNCTION WHILE THE GAME IS RUNNING.
# For vertical movement, return (0, state["speed"] * state["direction_y"]).
def get_velocity(state):
    """Return horizontal and vertical speed in pixels per second."""
    return (state["speed"] * state["direction_x"], -10)


def validate_velocity(value):
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("get_velocity must return (vx, vy)")
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in value):
        raise ValueError("Velocity must contain two finite numbers")
    return tuple(value)


def load_behavior(source, state):
    """Compile only the editable function, without rerunning this program."""
    tree = ast.parse(source, filename=str(Path(__file__).resolve()))
    functions = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == "get_velocity"]
    if len(functions) != 1:
        raise ValueError("Keep exactly one get_velocity(state) function")
    if functions[0].decorator_list:
        raise ValueError("get_velocity must not have decorators")
    namespace = {"math": math}
    module = ast.Module(body=functions, type_ignores=[])
    exec(compile(module, str(Path(__file__).resolve()), "exec"), namespace)
    behavior = namespace["get_velocity"]
    validate_velocity(behavior(dict(state)))
    return behavior


def move_box(state, velocity, dt):
    for axis, speed, limit in (("x", velocity[0], state["width"]),
                               ("y", velocity[1], state["height"])):
        position = state[axis] + speed * dt
        maximum = limit - state["size"]
        if position <= 0:
            position = 0
            state["direction_" + axis] = 1
        elif position >= maximum:
            position = maximum
            state["direction_" + axis] = -1
        state[axis] = position


def main():
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("Codex live script control POC")
    font = pygame.font.Font(None, 25)
    clock = pygame.time.Clock()
    state = dict(x=100.0, y=280.0, width=800, height=600, size=40,
                 speed=180.0, direction_x=1, direction_y=1)
    path = Path(__file__).resolve()
    last_source = path.read_bytes()
    behavior = get_velocity
    status = "Ready: horizontal movement"
    error = ""
    reload_count = 0
    next_check = 0.0
    running = True

    try:
        while running:
            dt = min(clock.tick(60) / 1000.0, 0.05)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False

            now = time.monotonic()
            if now >= next_check:
                next_check = now + 0.25
                try:
                    source = path.read_bytes()
                    if source != last_source:
                        last_source = source
                        candidate = load_behavior(source, state)
                        behavior = candidate
                        reload_count += 1
                        status = f"Reload {reload_count} applied; position preserved"
                        error = ""
                except Exception as exc:
                    error = f"Reload rejected: {type(exc).__name__}: {exc}"
                    print(error, flush=True)

            try:
                velocity = validate_velocity(behavior(dict(state)))
            except Exception as exc:
                # A function can pass reload validation and fail on a later state.
                velocity = (0, 0)
                message = f"Movement paused: {type(exc).__name__}: {exc}"
                if message != error:
                    print(message, flush=True)
                error = message
            move_box(state, velocity, dt)

            screen.fill((23, 27, 37))
            pygame.draw.rect(screen, (70, 205, 160),
                             (round(state["x"]), round(state["y"]),
                              state["size"], state["size"]))
            lines = ["Edit get_velocity() in live_box_poc.py, then save.",
                     "Changes apply automatically. Escape closes the window.",
                     status,
                     f"Position: ({state['x']:.0f}, {state['y']:.0f})   "
                     f"Velocity: ({velocity[0]:.0f}, {velocity[1]:.0f})"]
            if error:
                lines.append(error)
            for index, line in enumerate(lines):
                color = (255, 140, 130) if line == error else (225, 230, 240)
                screen.blit(font.render(line, True, color), (16, 16 + index * 26))
            pygame.display.flip()
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
