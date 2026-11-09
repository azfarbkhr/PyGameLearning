"""Wall-clock camera and turn-taking presentation independent of combat time."""
from __future__ import annotations

import math
import time
import pygame


class ConversationShot:
    _light_cutout = None

    def __init__(self):
        self.stage = "idle"
        self.started = 0.0
        self.replied_at = 0.0
        self.return_at = 0.0
        self.reply_length = 0
        self.listener = None
        self.focus = pygame.Vector2()
        self.zoom = 1.0
        self.label = ""
        if ConversationShot._light_cutout is None:
            cutout = pygame.Surface((512,512),pygame.SRCALPHA)
            cutout.fill((5,9,15,105))
            for radius in range(255,0,-1):
                alpha = round(105 * max(0,min(1,(radius-130)/125)))
                pygame.draw.circle(cutout,(5,9,15,alpha),(256,256),radius)
            ConversationShot._light_cutout = cutout

    @property
    def active(self):
        return self.stage != "idle"

    def start(self, player, listener):
        self.stage = "player"
        self.started = time.monotonic()
        self.replied_at = 0.0
        self.listener = listener or player
        self.focus = player.pos.copy()
        direction = self.listener.pos - player.pos
        if direction.length_squared():
            player.facing = direction.normalize()
            self.listener.facing = -player.facing
        self.label = "JON · YOUR TURN"

    def reply(self, text):
        if self.active:
            self.stage = "reply"
            self.replied_at = time.monotonic()
            self.reply_length = len(text)

    def finish(self):
        if self.active and self.stage != "return":
            self.stage = "return"
            self.return_at = time.monotonic()
            self.label = "RETURNING TO BATTLE"

    def update(self, game, dt):
        if not self.active:
            return
        now = time.monotonic()
        if game.state != "battle":
            self.stage = "idle"
            self.zoom = 1
            return
        if now - self.started > 40:
            self.finish()
        if self.stage == "player" and game.ai.speech_state not in {"starting", "listening"}:
            self.stage = "listener"
        if self.stage == "player":
            target = game.player
            self.label = "JON · SPEAKING" if game.ai.listening else "JON · YOUR TURN"
        elif self.stage in {"listener", "reply"}:
            target = self.listener if self.listener and self.listener.alive else game.player
            name = target.name.upper()
            self.label = name + (" · RESPONDING" if self.stage == "reply" else " · LISTENING")
            if self.stage == "reply" and not game.conversation_active() and now - self.replied_at > min(6, 1 + self.reply_length * .04):
                self.finish()
            # A failed microphone capture needs no invented reply or long pause.
            if self.stage == "listener" and not game.conversation_active() and now - self.started > 2:
                self.finish()
        else:
            target = game.player
            if now - self.return_at > 1:
                self.stage = "idle"
                self.zoom = 1
        blend = 1 - math.exp(-dt * (2.4 if self.stage == "listener" else 4))
        self.focus += (target.pos - self.focus) * blend
        desired_zoom = 1.0 if self.stage in {"return", "idle"} else 1.4
        self.zoom += (desired_zoom - self.zoom) * (1 - math.exp(-dt * 3))

    def view(self, game, width, height, world_width, world_height):
        if not self.active:
            return pygame.Rect(round(game.camera.x), round(game.camera.y), width, height)
        w, h = round(width / self.zoom), round(height / self.zoom)
        x = max(0, min(world_width - w, self.focus.x - w * .5))
        y = max(0, min(world_height - h, self.focus.y - h * .58))
        shot = pygame.Rect(round(x), round(y), w, h)
        if self.stage == "return":
            fraction = min(1, max(0, (time.monotonic() - self.return_at)))
            normal = pygame.Vector2(game.camera)
            shot.topleft = pygame.Vector2(shot.topleft).lerp(normal, fraction)
        return shot

    def draw_focus(self, canvas, view):
        if not self.active:
            return
        width, height = canvas.get_size()
        fade = max(0, 1 - (time.monotonic() - self.return_at)) if self.stage == "return" else 1
        center = ((self.focus.x - view.x) * width / view.width,
                  (self.focus.y - 45 - view.y) * height / view.height)
        shade = pygame.Surface((width, height), pygame.SRCALPHA)
        shade.fill((5, 9, 15, 105))
        shade.blit(self._light_cutout,(round(center[0]-256),round(center[1]-256)),special_flags=pygame.BLEND_RGBA_MIN)
        shade.set_alpha(round(255*fade))
        canvas.blit(shade, (0, 0))
