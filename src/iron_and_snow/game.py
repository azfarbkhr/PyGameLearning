from __future__ import annotations

import math
import random
import re
import time
import uuid
from pathlib import Path

import pygame

from iron_and_snow.npc import CodexNPC
from iron_and_snow.game_control import GameControl
from iron_and_snow.armies import ArmyController
from iron_and_snow.combat import CombatSystem
from iron_and_snow.director import BattleDirector
from iron_and_snow.conversation import ConversationShot

ROOT = Path(__file__).resolve().parents[2]
ASSETS = Path(__file__).resolve().parent / "assets"
WIDTH, HEIGHT = 1100, 700
WORLD_WIDTH, WORLD_HEIGHT = 3300, 1100
WORLD_SEGMENT = 1100
WORLD_PLAY_TOP = 640
WORLD_Y_SCALE = .65
FPS = 60
DEFEAT_RETRY_RECT = pygame.Rect(175, 430, 250, 44)
DEFEAT_TITLE_RECT = pygame.Rect(445, 430, 285, 44)
PLANNING_START_RECT = pygame.Rect(750, 600, 230, 48)
PLANNING_APPLY_RECT = pygame.Rect(120, 600, 300, 48)
PLANNING_RESET_RECT = pygame.Rect(450, 600, 220, 48)
PLANNING_ADVISOR_RECTS = {
    "sansa_stark": pygame.Rect(120, 170, 380, 132),
    "tormund_giantsbane": pygame.Rect(520, 170, 380, 132),
}
PLANNING_SECONDS = 60.0
IVORY = (236, 231, 211)
GOLD = (208, 172, 102)
INK = (19, 22, 28)
MUTED = (167, 171, 176)


def clamp(value, low, high):
    return max(low, min(high, value))


class SpriteAnimator:
    ROWS = {"idle": 0, "walk": 1, "attack": 2, "hit": 3, "death": 4}

    def __init__(self, path: Path, target_height: int):
        sheet = pygame.image.load(path).convert_alpha()
        self.frames = {name: [] for name in self.ROWS}
        self.cell_w, self.cell_h = sheet.get_width() // 6, sheet.get_height() // 5
        for name, row in self.ROWS.items():
            for col in range(6):
                cell = sheet.subsurface((col * self.cell_w, row * self.cell_h, self.cell_w, self.cell_h))
                bounds = cell.get_bounding_rect(min_alpha=8)
                frame = cell.subsurface(bounds) if bounds.width and bounds.height else cell.copy()
                if name == "idle" and col == 0:
                    self.portrait_source = frame.subsurface((0, 0, frame.get_width(), max(1, round(frame.get_height() * .38)))).copy()
                scale = target_height / max(1, frame.get_height())
                size = (max(1, round(frame.get_width() * scale)), target_height)
                self.frames[name].append(pygame.transform.scale(frame, size))

    def draw(self, surface, pos, action, elapsed, face_left=False, flash=False, tilt=0):
        row = self.frames.get(action, self.frames["idle"])
        if action == "death":
            index = min(len(row) - 1, int(elapsed * 10))
        else:
            index = int(elapsed * 9) % len(row)
        frame = row[index]
        if face_left:
            frame = pygame.transform.flip(frame, True, False)
        if flash:
            frame = frame.copy()
            frame.fill((255, 66, 34, 112), special_flags=pygame.BLEND_RGBA_ADD)
        if tilt:
            frame = pygame.transform.rotate(frame, tilt)
        rect = frame.get_rect(midbottom=(round(pos[0]), round(pos[1]) + 23))
        # Keep tall characters inside the battlefield below the fixed HUD.
        previous_clip = surface.get_clip()
        surface.set_clip(previous_clip.clip(pygame.Rect(0, 0, WORLD_WIDTH, WORLD_HEIGHT)))
        surface.blit(frame, rect)
        surface.set_clip(previous_clip)


class Combatant:
    def __init__(self, x, y, *, name, color, health, speed, radius=18):
        self.pos = pygame.Vector2(x, y)
        self.uid = uuid.uuid4().hex[:10]
        self.ranged = False
        self.stamina = 100.0
        self.posture = 0.0
        self.velocity = pygame.Vector2()
        self.pending_strike = None
        self.attack_kind = "quick"
        self.stagger_until = 0.0
        self.dodge_until = 0.0
        self.dodge_cooldown = 0.0
        self.dodge_direction = pygame.Vector2()
        self.intent = "idle"
        self.intent_reason = ""
        self.navigator = None
        self.hold_point = self.pos.copy()
        self.name = name
        self.color = color
        self.health = self.max_health = health
        self.speed = speed
        self.radius = radius
        self.facing = pygame.Vector2(1, 0)
        self.attack_cooldown = 0.0
        self.flash = 0.0
        self.invulnerable = 0.0
        self.sprint_time = 0.0
        self.sprint_cooldown = 0.0
        self.block_time = 0.0
        self.block_perfect_time = 0.0
        self.block_cooldown = 0.0
        self.arrow_cooldown = 0.0
        self.alive = True
        self.animation = "idle"
        self.animation_started = 0.0
        self.animation_until = 0.0
        self.moving = False
        self.pending_melee_hit_at = None

    @property
    def rect(self):
        return pygame.Rect(int(self.pos.x - self.radius), int(self.pos.y - self.radius), self.radius * 2, self.radius * 2)

    def move_toward(self, target, dt, obstacles, now=0.0, crowd=(), speed_multiplier=1.0):
        target = pygame.Vector2(target)
        if self.stagger_until > now or self.dodge_until > now:
            return
        if self.pending_strike:
            speed_multiplier *= .2
        if self.navigator:
            target = self.navigator.waypoint(self, target, now)
        delta = target - self.pos
        direction = delta.normalize() if delta.length_squared() >= 4 else pygame.Vector2()
        # Keep the battlefield actors from collapsing into a single stack of sprites.
        for other in crowd:
            away = self.pos - other.pos
            distance = away.length()
            min_gap = self.radius + other.radius + 14
            if distance < min_gap:
                if distance == 0:
                    away.update(1 if id(self) < id(other) else -1, .25)
                    distance = away.length()
                direction += away.normalize() * (1.1 + (min_gap - distance) / min_gap)
        self.moving = direction.length_squared() >= .04
        if not self.moving:
            self._update_animation(now)
            return
        direction = direction.normalize()
        for obstacle in obstacles if not self.navigator else ():
            expanded = obstacle.inflate(self.radius * 2 + 12, self.radius * 2 + 12)
            if expanded.clipline((round(self.pos.x), round(self.pos.y)), (round(target.x), round(target.y))):
                margin = 5
                corners = (
                    pygame.Vector2(expanded.left - margin, expanded.top - margin),
                    pygame.Vector2(expanded.right + margin, expanded.top - margin),
                    pygame.Vector2(expanded.left - margin, expanded.bottom + margin),
                    pygame.Vector2(expanded.right + margin, expanded.bottom + margin),
                )
                waypoint = min(corners, key=lambda point: point.distance_squared_to(self.pos) + point.distance_squared_to(target) * .7)
                direction = (waypoint - self.pos).normalize()
                break
        if direction.length_squared() > 0:
            direction = direction.normalize()
            face = self.facing.lerp(direction, 1 - math.exp(-dt * 12))
            self.facing = face.normalize() if face.length_squared() else direction
            desired = direction * self.speed * speed_multiplier
            self.velocity = self.velocity.lerp(desired, 1 - math.exp(-dt * 10))
            self.pos += self.velocity * dt
        self.pos.x = clamp(self.pos.x, 32, WORLD_WIDTH - 32)
        self.pos.y = clamp(self.pos.y, WORLD_PLAY_TOP, WORLD_HEIGHT - 38)
        self._resolve_obstacles(obstacles)
        self._update_animation(now)

    def set_animation(self, action, now, duration=0.0):
        self.animation = action
        self.animation_started = now
        self.animation_until = now + duration

    def _update_animation(self, now):
        if now < self.animation_until:
            return
        action = "walk" if self.moving else "idle"
        if self.animation != action:
            self.set_animation(action, now)

    def _resolve_obstacles(self, obstacles):
        for obstacle in obstacles:
            body = self.rect
            if not body.colliderect(obstacle):
                continue
            pushes = (
                (body.right - obstacle.left, pygame.Vector2(-1, 0)),
                (obstacle.right - body.left, pygame.Vector2(1, 0)),
                (body.bottom - obstacle.top, pygame.Vector2(0, -1)),
                (obstacle.bottom - body.top, pygame.Vector2(0, 1)),
            )
            distance, axis = min(pushes, key=lambda item: item[0])
            self.pos += axis * (distance + 1)

    def draw(self, surface, tick, hero=False, sprite=None, show_health=False, show_name=False, label_font=None, speaking=False):
        x, y = round(self.pos.x), round(self.pos.y)
        shadow_width = max(36, round(self.radius * 2.5))
        shadow_height = max(12, round(self.radius * 0.55))
        pygame.draw.ellipse(surface, (12, 15, 19), (x - shadow_width // 2, y + 14, shadow_width, shadow_height))
        frame_height = sprite.frames["idle"][0].get_height() if sprite else self.radius * 2
        if sprite is not None:
            tilt = (18 if self.dodge_direction.x >= 0 else -18) if self.dodge_until > tick else (-10 if self.facing.x > 0 else 10) if self.pending_strike and self.attack_kind == "heavy" else 0
            if speaking:
                tilt = 0
            pose_pos = self.pos + pygame.Vector2(0, math.sin(time.monotonic() * 2.8) * 1.2) if speaking else self.pos
            sprite.draw(surface, pose_pos, "idle" if speaking else self.animation,
                        time.monotonic() * .35 if speaking else tick - self.animation_started,
                        self.facing.x < 0, self.flash > 0, tilt)
            if self.pending_strike:
                reach = 92 if self.attack_kind == "heavy" else 75
                direction = self.pending_strike["direction"]
                color = (238, 155, 75) if self.attack_kind == "heavy" else (223, 190, 130)
                angle = math.atan2(-direction.y, direction.x)
                pygame.draw.arc(surface, color, (x - reach, y - reach // 2, reach * 2, reach), angle - .65, angle + .65, 3)
                if self.attack_kind == "heavy":
                    hand = pygame.Vector2(x, y - frame_height * .6)
                    tip = hand + pygame.Vector2(direction.x * 22, -45)
                    pygame.draw.line(surface, (239, 220, 180), hand, tip, 4)
            if self.dodge_until > tick:
                trail = self.pos - self.dodge_direction * 35
                pygame.draw.line(surface, (125, 180, 205), (x, y + 15), trail + pygame.Vector2(0, 15), 3)
        else:
            body_color = IVORY if self.flash > 0 and int(tick * 18) % 2 else self.color
            pygame.draw.circle(surface, body_color, (x, y), self.radius)
            pygame.draw.circle(surface, (18, 21, 27), (x, y), self.radius, 2)
            pygame.draw.circle(surface, (226, 213, 185), (x - 4, y - 4), 4)
            if hero:
                pygame.draw.arc(surface, (189, 194, 197), (x - 17, y - 17, 34, 34), 0.2, 2.7, 4)
                pygame.draw.line(surface, (205, 210, 218), (x + self.facing.x * 10, y + self.facing.y * 10), (x + self.facing.x * 32, y + self.facing.y * 32), 4)
            else:
                pygame.draw.line(surface, (117, 39, 40), (x + self.facing.x * 9, y + self.facing.y * 9), (x + self.facing.x * 28, y + self.facing.y * 28), 4)
        if getattr(self, "ranged", False) and self.name not in {"Sansa Stark", "Northern Archer"}:
            bow_center = (round(x + self.facing.x * 17), round(y - 30 + self.facing.y * 5))
            pygame.draw.arc(surface, (177, 143, 95), (bow_center[0] - 9, bow_center[1] - 16, 18, 32), -1.35, 1.35, 2)
            pygame.draw.line(surface, (217, 203, 170), (bow_center[0] - 3, bow_center[1] - 13), (bow_center[0] - 3, bow_center[1] + 13), 1)
        if show_health:
            bar_width = 62 if self.name == "Ramsay Bolton" else 50
            bar = pygame.Rect(x - bar_width // 2, y + 23 - frame_height - 9, bar_width, 5)
            pygame.draw.rect(surface, (29, 30, 31), bar, border_radius=3)
            fill = bar.copy()
            fill.width = max(0, round(bar.width * max(0, self.health) / self.max_health))
            if fill.width:
                pygame.draw.rect(surface, (202, 71, 60), fill, border_radius=3)
        if show_name:
            font = label_font or pygame.font.Font(None, 17)
            label = font.render(self.name.upper(), True, GOLD if hero else IVORY)
            label_y = y + 23 - frame_height - 10 if sprite else y - self.radius - 21
            label_rect = label.get_rect(center=(x, label_y))
            surface.blit(label, label_rect)


class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("IRON & SNOW  |  The Bastard's Winter")
        self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        self.canvas = pygame.Surface((WIDTH, HEIGHT))
        self.world_canvas = pygame.Surface((WORLD_WIDTH, WORLD_HEIGHT))
        self.camera = pygame.Vector2()
        self.camera_target = pygame.Vector2()
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.small = pygame.font.Font(None, 19)
        self.dialogue_font = pygame.font.Font(None, 31)
        self.speaker_font = pygame.font.Font(None, 24)
        self.title = pygame.font.Font(None, 72)
        self.running = True
        self.state = "title"
        self.chapter = 0
        self.planning_deadline = 0.0
        self.planning_last_tick = 0.0
        self.planning_clock_paused = False
        self.planning_suggestion = []
        self.battle_time_scale = 1.0
        self.conversation_focus_until = 0.0
        self.planning_notes = []
        self.planning_advisors = ["sansa_stark", "tormund_giantsbane"]
        self.team_strategy = {"default": "follow", "assignments": {}}
        self.flags = {"allies": False, "archers": False, "won": False}
        self.story_lines = []
        self.story_index = 0
        self.story_advance_at = 0.0
        self.combat_time = 0
        self.chapter_wave = 1
        self.chapter_wave_count = 1
        self.wave_pending = False
        self.wave_spawn_at = 0.0
        self.support_archer_timer = 0
        self.player = None
        self.commander = None
        self.enemies = []
        self.obstacles = []
        self.terrain_props = []
        self.effects = []
        self.pending_support_shots = []
        self.dialogue = []
        self.mouse_move_target = None
        self.mouse_attack_target = None
        self.input_mode = "enemy"
        self.dialogue_request_seq = 0
        self.latest_dialogue_request_id = None
        self.voice_capture_mode = None
        self.team_order = "follow"
        self.team_order_actor = None
        self.team_order_time = 0.0
        self.team_order_feedback = ""
        self.team_order_feedback_until = 0.0
        self.listening = False
        self.max_arrow_ammo = 8
        self.arrow_ammo = self.max_arrow_ammo
        self.help_calls_remaining = 1
        self.projectiles = []
        self.control = GameControl()
        self.combat = CombatSystem(self)
        self.armies = ArmyController(self)
        self.director = BattleDirector(ROOT)
        self.director.start()
        self.director_signature = None
        self.conversation = ConversationShot()
        self.ai = CodexNPC(ROOT, director=self.director)
        self.hero_sprite = self.load_sprite("jon_snow_sheet.png", 92)
        self.bolton_sprite = self.load_sprite("ramsay_bolton_sheet.png", 102)
        self.bolton_soldier_sprite = self.load_sprite("bolton_soldier_sheet.png", 98)
        self.bolton_archer_sprite = self.load_sprite("bolton_archer_sheet.png", 98)
        self.stark_soldier_sprite = self.load_sprite("stark_soldier_sheet.png", 100)
        self.stark_archer_sprite = self.load_sprite("stark_archer_sheet.png", 100)
        self.tormund_sprite = self.load_sprite("tormund_giantsbane_sheet.png", 118)
        self.wunwun_sprite = self.load_sprite("wun_wun_sheet.png", 198)
        self.sansa_sprite = self.load_sprite("sansa_archer_sheet.png", 98)
        self.arrow_projectile = self.load_cutout(ASSETS / "sprites" / "arrow_projectile.png", (58, 15))
        self.hostile_arrow_projectile = self.arrow_projectile.copy() if self.arrow_projectile else None
        if self.hostile_arrow_projectile:
            self.hostile_arrow_projectile.fill((255, 104, 86, 255), special_flags=pygame.BLEND_RGBA_MULT)
        self.terrain_assets = {
            "boulder": self.load_cutout(ASSETS / "terrain" / "snow_boulder_cluster.png", (150, 104)),
            "fallen_pine": self.load_cutout(ASSETS / "terrain" / "fallen_pine.png", (210, 95)),
        }
        self.arrow_rotation_cache = {}
        self.battlefield_image = pygame.image.load(ASSETS / "winterfell_battlefield_panorama.png").convert()
        self.battlefield_image = pygame.transform.smoothscale(self.battlefield_image, (WORLD_WIDTH, WORLD_HEIGHT))
        self.menu_background = pygame.transform.smoothscale(self.battlefield_image, (WIDTH, HEIGHT))
        self.battlefield_shade = pygame.Surface((WORLD_WIDTH, WORLD_HEIGHT), pygame.SRCALPHA)
        self.battlefield_shade.fill((14, 19, 24, 62))
        self.last_tactic_time = 0
        self.bolton_pressure_line_played = False
        self.ramsay_reacted_to_hit = False
        self.voice_capture_started = None
        self.ai_tactic = "press"
        try:
            self.attack_sound = pygame.mixer.Sound(ASSETS / "audio" / "attack.wav")
            self.attack_sound.set_volume(.28)
        except pygame.error:
            self.attack_sound = None
        try:
            self.hit_sound = pygame.mixer.Sound(ASSETS / "audio" / "hit_impact.wav")
            self.hit_sound.set_volume(.42)
        except pygame.error:
            self.hit_sound = None
        self.voice_channel = pygame.mixer.Channel(2)
        self.voice_sound = None
        self.voice_path = None
        self.battle_audio_active = False
        self.screen_shake = 0.0
        self.enemy_spawn_index = 0
        self.ally_spawn_index = 0

    @staticmethod
    def load_sprite(filename, height):
        try:
            return SpriteAnimator(ASSETS / "sprites" / filename, height)
        except (pygame.error, FileNotFoundError, ZeroDivisionError):
            return None

    def canvas_pos(self, screen_pos):
        """Convert fullscreen desktop mouse coordinates to the game's logical canvas."""
        screen_w, screen_h = self.screen.get_size()
        return round(screen_pos[0] * WIDTH / screen_w), round(screen_pos[1] * HEIGHT / screen_h)

    @staticmethod
    def load_cutout(path, size):
        try:
            image = pygame.image.load(path).convert_alpha()
            bounds = image.get_bounding_rect(min_alpha=8)
            if bounds.width <= 0 or bounds.height <= 0:
                return None
            return pygame.transform.smoothscale(image.subsurface(bounds).copy(), size)
        except (pygame.error, FileNotFoundError):
            return None

    def set_terrain(self, props):
        """Build terrain visuals and solid hitboxes from shared, data-driven prop layouts."""
        self.terrain_props = []
        self.obstacles = []
        for kind, visual_rect, collision_rect in props:
            collision = pygame.Rect(collision_rect)
            self.obstacles.append(collision)
            image = self.terrain_assets.get(kind)
            if image:
                scaled = pygame.transform.smoothscale(image, pygame.Rect(visual_rect).size)
                self.terrain_props.append({"kind": kind, "image": scaled, "rect": pygame.Rect(visual_rect), "collision": collision})

    @staticmethod
    def world_y(local_y):
        return 620 + (local_y - 80) * WORLD_Y_SCALE

    def place_battle_segment(self, chapter):
        """Move a chapter's familiar encounter layout into its world segment."""
        x_offset = (chapter - 1) * WORLD_SEGMENT
        actors = [self.player, *self.allies, *self.enemies]
        for actor in actors:
            actor.pos.x += x_offset
            actor.pos.y = max(WORLD_PLAY_TOP + 6, self.world_y(actor.pos.y))
            if hasattr(actor, "engage_slot"):
                actor.engage_slot.x += x_offset
                actor.engage_slot.y = self.world_y(actor.engage_slot.y)
            if hasattr(actor, "follow_offset"):
                actor.follow_offset.y *= WORLD_Y_SCALE
        for obstacle in self.obstacles:
            obstacle.x += x_offset
            obstacle.y = round(self.world_y(obstacle.y))
            obstacle.height = max(1, round(obstacle.height * WORLD_Y_SCALE))
        for prop in self.terrain_props:
            rect = prop["rect"]
            rect.x += x_offset
            rect.y = round(self.world_y(rect.y))
            rect.height = max(1, round(rect.height * WORLD_Y_SCALE))
            prop["image"] = pygame.transform.smoothscale(prop["image"], rect.size)
        # The north edge is occupied by Winterfell's outer wall and wooded
        # approach. Its collision band makes the illustrated castle physical.
        self.obstacles.append(pygame.Rect(x_offset, 330, WORLD_SEGMENT, 290))
        self.update_camera(0, snap=True)

    def update_camera(self, dt, snap=False):
        if not self.player:
            return
        left, right = WIDTH * .32, WIDTH * .68
        top, bottom = 155, 405
        screen_x = self.player.pos.x - self.camera.x
        screen_y = self.player.pos.y - self.camera.y
        target_x = self.camera.x
        target_y = self.camera.y
        if screen_x < left:
            target_x = self.player.pos.x - left
        elif screen_x > right:
            target_x = self.player.pos.x - right
        if screen_y < top:
            target_y = self.player.pos.y - top
        elif screen_y > bottom:
            target_y = self.player.pos.y - bottom
        target_x = clamp(target_x, 0, WORLD_WIDTH - WIDTH)
        target_y = clamp(target_y, 0, WORLD_HEIGHT - HEIGHT)
        self.camera_target.update(target_x, target_y)
        if snap:
            self.camera.update(target_x, target_y)
        else:
            blend = 1 - math.exp(-dt * 5.5)
            self.camera += (self.camera_target - self.camera) * blend

    def run(self):
        try:
            while self.running:
                dt = min(self.clock.tick(FPS) / 1000, 0.04)
                self.handle_events()
                self.update(dt)
                self.draw()
        finally:
            self.armies.close()
            self.director.close()
            self.ai.close()
            pygame.mixer.music.stop()
            pygame.quit()

    def begin_story(self, chapter=0):
        scripts = [
            ["WINTERFELL · BEFORE DAWN", "Ramsay has the numbers and the walls. Keep the North alive, break his lines, and take Winterfell."],
            ["THE FIELD · HOLD THE LINE", "Bolton infantry and archers are closing in. Survive the first push; their reserve is already moving."],
            ["THE SHIELD WALL · BREAK THROUGH", "The Boltons reform behind a shield wall. Protect the archers, call your allies, and open a path to the gate."],
            ["WINTERFELL COURTYARD · END THE SIEGE", "Clear the courtyard reinforcements. Ramsay will enter only after his guards fall."],
        ]
        self.story_lines = scripts[chapter]
        self.story_index = 0
        self.story_advance_at = 0.0
        self.state = "story"
        self.chapter = chapter

    def advance_story(self):
        now = time.monotonic()
        if now < self.story_advance_at:
            return
        self.story_advance_at = now + .18
        if self.story_index >= len(self.story_lines) - 2:
            if self.chapter == 0:
                self.begin_story(1)
            else:
                self.begin_planning(self.chapter)
        else:
            self.story_index += 1

    def begin_campaign(self):
        self.flags = {"allies": False, "archers": False, "won": False}
        self.arrow_ammo = self.max_arrow_ammo
        self.team_strategy = {"default": "follow", "assignments": {}}
        self.begin_story(0)

    def begin_planning(self, chapter):
        # Prepare the real full army now, giving Codex the council interval to
        # inspect and command it while combat time remains frozen.
        self.start_battle(chapter)
        self.chapter = chapter
        self.state = "planning"
        self.planning_deadline = time.monotonic() + PLANNING_SECONDS
        self.planning_last_tick = time.monotonic()
        self.planning_clock_paused = False
        self.planning_suggestion = []
        self.planning_notes = []
        self.team_strategy = {"default": "follow", "assignments": {}}
        self.team_order_feedback = ""
        self.team_order_feedback_until = 0.0
        self.dialogue.clear()
        self.latest_dialogue_request_id = None
        self.ai.latest_dialogue_request_id = None
        self.ai.cancel_dialogue()
        self.voice_capture_mode = None
        self.stop_voice_playback()
        self.ai.select_character("sansa_stark")
        self.control.tick(self, force=True)

    def finish_planning(self):
        if self.state != "planning":
            return
        self.state = "battle"
        self.ai.cancel_dialogue()
        self.dialogue.clear()
        self.latest_dialogue_request_id = None
        self.ai.latest_dialogue_request_id = None
        self.stop_voice_playback()

    def conversation_active(self):
        pending = any(entry.get("provisional") for entry in self.dialogue)
        return (self.ai.listening or pending or self.ai.tts_worker_active
                or not self.ai.speech_queue.empty() or self.voice_channel.get_busy())

    def voice_warming(self):
        return ((self.ai.tts_backend == "kokoro" and not self.ai.kokoro_ready.is_set())
                or (self.ai.stt_backend == "whisper" and not self.ai.whisper_ready.is_set()))

    def apply_planning_suggestion(self):
        if self.state != "planning" or not self.planning_suggestion:
            self.team_order_feedback = "NO AI PLAN TO APPLY YET"
            self.team_order_feedback_until = time.monotonic() + 3
            return
        # The service validated every proposed target and action.
        for order in self.planning_suggestion:
            if order["target"] == "team":
                self.team_strategy["default"] = order["action"]
                self.team_strategy["explicit_default"] = True
                self.team_strategy["assignments"].clear()
                self.team_strategy["positions"] = {}
        for order in self.planning_suggestion:
            if order["target"] != "team":
                self.team_strategy["assignments"][order["target"]] = order["action"]
                positions = self.team_strategy.setdefault("positions", {})
                if order.get("point"):
                    point = pygame.Vector2(order["point"])
                    if any(o.inflate(48, 48).collidepoint(point) for o in self.obstacles):
                        path = self.armies.navigator.path(self.player.pos, point)
                        if path:
                            point = path[-1]
                    positions[order["target"]] = list(point)
                else:
                    positions.pop(order["target"], None)
        self.planning_suggestion = []
        self.team_order_feedback = "AI PLAN ACCEPTED · ORDERS STAY ACTIVE THROUGH BATTLE"
        self.team_order_feedback_until = time.monotonic() + 6

    def cycle_planning_advisor(self):
        if self.ai.listening:
            return
        current = self.ai.active_character
        try:
            index = self.planning_advisors.index(current)
        except ValueError:
            index = -1
        self.ai.select_character(self.planning_advisors[(index + 1) % len(self.planning_advisors)])

    @staticmethod
    def planning_done_phrase(line):
        normalized = str(line).lower().replace("'", "").replace("’", "")
        words = re.sub(r"[^a-z0-9]+", " ", normalized).split()
        phrase = " ".join(words)
        return phrase in {
            "done", "im done", "i am done", "we are done", "were done", "all done",
            "im all done", "i am all done", "im finished", "i am finished",
            "ready", "im ready", "i am ready", "we are ready", "were ready",
            "start battle", "begin battle", "lets begin", "lets start", "lets go",
        }

    def start_battle(self, chapter):
        self.control.new_battle()
        self.conversation = ConversationShot()
        self.director_signature = None
        self.chapter = chapter
        self.state = "battle"
        self.battle_time_scale = 1.0
        self.conversation_focus_until = 0.0
        self.combat_time = 0
        self.chapter_wave = 1
        self.chapter_wave_count = {1: 2, 2: 2, 3: 3}.get(chapter, 1)
        self.wave_pending = False
        self.wave_spawn_at = 0.0
        self.enemy_spawn_index = 0
        self.ally_spawn_index = 0
        self.help_calls_remaining = 1
        self.projectiles.clear()
        self.support_archer_timer = 0
        self.effects.clear()
        self.pending_support_shots.clear()
        self.dialogue.clear()
        self.latest_dialogue_request_id = None
        self.ai.latest_dialogue_request_id = None
        self.stop_voice_playback()
        self.mouse_move_target = None
        self.mouse_attack_target = None
        self.ai.poll_tactic()
        self.bolton_pressure_line_played = False
        self.ramsay_reacted_to_hit = False
        self.team_order = "follow"
        self.team_order_actor = None
        self.team_order_time = 0.0
        self.team_order_feedback = ""
        self.team_order_feedback_until = 0.0
        if chapter == 1:
            self.player = Combatant(150, 365, name="Jon Snow", color=(44, 55, 67), health=100, speed=235)
            self.player.sprite = self.hero_sprite
            self.set_terrain([
                ("fallen_pine", (300, 145, 210, 95), (334, 207, 150, 24)),
                ("boulder", (440, 390, 150, 104), (474, 464, 82, 26)),
                ("boulder", (755, 265, 132, 92), (788, 330, 70, 22)),
            ])
            self.enemies = [self.new_enemy(x, y, "Bolton soldier") for x, y in [
                (620, 135), (865, 190), (1010, 330), (910, 535), (660, 560), (525, 285),
                (1090, 155), (1095, 485), (780, 95),
            ]]
            self.enemies.extend([
                self.new_enemy(1070, 260, "Bolton archer", 40),
                self.new_enemy(1055, 585, "Bolton archer", 40),
            ])
            self.allies = [self.new_tormund(115, 455), self.new_stark_ally(60, 555, (-155, 90)), self.new_stark_ally(300, 555, (40, 145))]
            if self.flags["allies"]:
                self.allies.append(self.new_stark_ally(75, 620, (-220, 190)))
        elif chapter == 2:
            self.player = Combatant(125, 360, name="Jon Snow", color=(44, 55, 67), health=100, speed=235)
            self.player.sprite = self.hero_sprite
            self.set_terrain([
                ("boulder", (325, 190, 150, 104), (360, 263, 82, 25)),
                ("fallen_pine", (480, 490, 210, 95), (515, 554, 140, 24)),
                ("boulder", (740, 335, 150, 104), (775, 409, 82, 24)),
            ])
            self.enemies = [self.new_enemy(x, y, "Bolton archer", 40) for x, y in [(670, 120), (930, 245), (1010, 490), (675, 565)]]
            self.enemies.extend(self.new_enemy(x, y, "Bolton soldier", 52) for x, y in [
                (820, 150), (1090, 315), (930, 585), (520, 175), (530, 510),
            ])
            wun = Combatant(190, 465, name="Wun Wun", color=(94, 92, 83), health=190, speed=105, radius=36)
            wun.sprite = self.wunwun_sprite
            wun.follow_offset = pygame.Vector2(-175, -10)
            wun.flank_angle = math.pi
            self.allies = [wun, self.new_tormund(255, 505), self.new_stark_ally(55, 565, (-190, 130)), self.new_stark_ally(330, 570, (55, 180))]
        else:
            self.player = Combatant(120, 365, name="Jon Snow", color=(44, 55, 67), health=100, speed=235)
            self.player.sprite = self.hero_sprite
            self.set_terrain([
                ("fallen_pine", (315, 185, 210, 95), (350, 247, 150, 24)),
                ("boulder", (495, 450, 150, 104), (530, 524, 82, 24)),
                ("boulder", (760, 245, 150, 104), (795, 319, 82, 24)),
            ])
            self.enemies = [self.new_enemy(x, y, "Bolton guard", 56) for x, y in [
                (650, 130), (990, 220), (1000, 560), (770, 105), (1060, 380), (720, 585),
            ]]
            sansa = Combatant(190, 500, name="Sansa Stark", color=(120, 129, 145), health=100, speed=128, radius=17)
            sansa.sprite = self.sansa_sprite
            sansa.ranged = True
            sansa.follow_offset = pygame.Vector2(-180, 120)
            self.allies = [sansa, self.new_tormund(80, 495), self.new_stark_ally(280, 540, (115, 145)), self.new_stark_ally(390, 585, (215, 190))]
        self.place_battle_segment(chapter)
        if not any(a.name == "Sansa Stark" for a in self.allies):
            sansa = Combatant(self.player.pos.x + 65, self.player.pos.y + 85, name="Sansa Stark",
                             color=(120, 129, 145), health=100, speed=128, radius=17)
            sansa.sprite = self.sansa_sprite
            sansa.ranged = True
            self.allies.append(sansa)
        self.commander = Combatant((chapter - 1) * WORLD_SEGMENT + 1000, 610,
                                   name="Ramsay Bolton", color=(112, 43, 42), health=150, speed=116, radius=24)
        self.commander.sprite = self.bolton_sprite
        self.armies.reset()
        self._assign_engagement_slots()
        self.ai.warm(self.chapter_name(chapter), self.ai_context())

    def queue_next_wave(self):
        if self.wave_pending or self.chapter_wave >= self.chapter_wave_count:
            return False
        self.wave_pending = True
        self.wave_spawn_at = self.combat_time + 1.6
        if self.chapter == 3 and self.chapter_wave == 2:
            line = "The last guards scatter. Ramsay steps into the yard with his sword drawn."
        elif self.chapter == 2:
            line = "Bolton reserves reform behind the shield wall. Their archers take position."
        else:
            line = "Bolton reserves rush in from the flank. Keep the line from closing around you."
        self.add_dialogue("BATTLEFIELD", line, event="reinforcements")
        return True

    def spawn_next_wave(self):
        next_wave = self.chapter_wave + 1
        if self.chapter == 1:
            composition = [
                ("Bolton soldier", 48), ("Bolton soldier", 48), ("Bolton soldier", 48),
                ("Bolton soldier", 48), ("Bolton soldier", 48),
                ("Bolton archer", 40), ("Bolton archer", 40),
            ]
        elif self.chapter == 2:
            composition = [
                ("Bolton guard", 56), ("Bolton guard", 56), ("Bolton guard", 56),
                ("Bolton guard", 56), ("Bolton soldier", 52),
                ("Bolton archer", 40), ("Bolton archer", 40),
            ]
        elif next_wave == 2:
            composition = [
                ("Bolton guard", 56), ("Bolton guard", 56), ("Bolton guard", 56),
                ("Bolton guard", 56), ("Bolton archer", 40), ("Bolton archer", 40),
            ]
        else:
            boss = self.commander
            boss.pos.update(clamp(self.player.pos.x + 620, 100, WORLD_WIDTH - 100), self.player.pos.y)
            boss.sprite = self.bolton_sprite
            self.enemies.append(boss)
            self.ramsay_reacted_to_hit = False
            self.add_dialogue("RAMSAY BOLTON", self.ai.scripted_line(
                "ramsay_bolton", "courtyard_entrance", "You made it through my men. Now face me, Snow."
            ), event="boss_entrance")
            self.chapter_wave = next_wave
            self.wave_pending = False
            self._assign_engagement_slots()
            return

        spawn_x = clamp(self.player.pos.x + WORLD_SEGMENT * .72, 48, WORLD_WIDTH - 48)
        count = len(composition)
        for index, (name, health) in enumerate(composition):
            spread = (index - (count - 1) / 2) * 48
            spawn_y = clamp(self.player.pos.y + spread, WORLD_PLAY_TOP, WORLD_HEIGHT - 65)
            x = clamp(spawn_x + (24 if index % 2 else 0), 40, WORLD_WIDTH - 40)
            self.enemies.append(self.new_enemy(x, spawn_y, name, health))
        self.chapter_wave = next_wave
        self.wave_pending = False
        self._assign_engagement_slots()
        self.add_dialogue("BATTLEFIELD", f"Bolton reinforcements arrive. Wave {self.chapter_wave} of {self.chapter_wave_count}.",
                          event="wave_arrival")

    def add_dialogue(self, speaker, text, **metadata):
        # Keep the subtitle panel for player-initiated exchanges and their
        # replies. Opening narration, combat barks, and scripted Jon lines stay
        # out of the conversation UI.
        if not (metadata.get("player_input") or metadata.get("provisional")
                or metadata.get("request_id") or metadata.get("voice")
                or str(speaker).strip().upper() == "VOICE INPUT"):
            return None
        entry = {"speaker": speaker, "text": text, **metadata}
        self.dialogue.append(entry)
        self.dialogue = self.dialogue[-8:]
        if hasattr(self, "ai"):
            voice_slug = {
                "RAMSAY BOLTON": "ramsay_bolton",
                "JON SNOW": "jon_snow",
                "SANSA": "sansa_stark",
                "SANSA STARK": "sansa_stark",
                "TORMUND": "tormund_giantsbane",
                "TORMUND GIANTSBANE": "tormund_giantsbane",
                "WUN WUN": "wun_wun",
            }.get(str(speaker).strip().upper())
            if (voice_slug and metadata.get("voice") and not metadata.get("player_input")
                    and not metadata.get("provisional")):
                self.ai.speak(text, character_slug=voice_slug, request_id=metadata.get("request_id"))
        return entry

    def stop_voice_playback(self):
        """Stop old dialogue so it cannot mask the mic or delay the next reply."""
        if getattr(self, "voice_channel", None):
            self.voice_channel.stop()
        self.voice_sound = None
        if self.voice_path:
            Path(self.voice_path).unlink(missing_ok=True)
            self.voice_path = None
        if getattr(self, "ai", None):
            self.ai.cancel_speech()

    def _team_target(self, ally, order=None):
        if not self.enemies:
            return None
        if (order or self.team_order) == "focus":
            leader = next((enemy for enemy in self.enemies if enemy.name == "Ramsay Bolton"), None)
            if leader:
                return leader
        if (order or self.team_order) == "target_archers":
            archers = [enemy for enemy in self.enemies if getattr(enemy, "ranged", False) or "archer" in enemy.name.lower()]
            if archers:
                return min(archers, key=lambda enemy: ally.pos.distance_squared_to(enemy.pos))
        if (order or self.team_order) == "cover":
            return min(self.enemies, key=lambda enemy: enemy.pos.distance_squared_to(self.player.pos))
        return min(self.enemies, key=lambda enemy: ally.pos.distance_squared_to(enemy.pos))

    @staticmethod
    def strategy_target_from_phrase(line):
        text = str(line or "").lower()
        matches = []
        for target, terms in (
            ("sansa stark", ("sansa",)),
            ("tormund", ("tormund",)),
            ("wun wun", ("wun wun", "giant")),
            ("archers", ("our archers", "stark archers", "vale archers", "north archers")),
            ("northmen", ("northmen", "north men", "infantry", "soldiers")),
        ):
            if any(term in text for term in terms):
                matches.append(target)
        if len(matches) > 1:
            return "ambiguous"
        return matches[0] if matches else None

    @staticmethod
    def ally_strategy_key(ally):
        name = ally.name.lower()
        if "sansa" in name:
            return "sansa stark"
        if "tormund" in name:
            return "tormund"
        if "wun wun" in name:
            return "wun wun"
        if getattr(ally, "ranged", False) or "archer" in name:
            return "archers"
        if name in {"northman", "reinforcement"}:
            return "northmen"
        return name

    def has_explicit_order(self, ally, temporary_only=False):
        strategy = self.team_strategy
        key = self.ally_strategy_key(ally)
        group = "archers" if ally.ranged else "northmen"
        target = self.team_order_actor
        temporary = self.team_order_time > 0 and (target is None or target in key or key in target
                    or target in {"archer", "archers"} and group == "archers"
                    or target in {"northman", "northmen"} and group == "northmen")
        if temporary_only:
            return bool(temporary)
        return bool(temporary or key in strategy.get("assignments", {}) or group in strategy.get("assignments", {})
                    or strategy.get("explicit_default") or strategy.get("default", "follow") != "follow")

    def order_for_ally(self, ally):
        strategy = getattr(self, "team_strategy", {"default": "follow", "assignments": {}})
        key = self.ally_strategy_key(ally)
        group = "archers" if ally.ranged else "northmen"
        order = strategy.get("assignments", {}).get(key, strategy.get("assignments", {}).get(group, strategy.get("default", "follow")))
        if self.team_order_time <= 0:
            return order
        target = self.team_order_actor
        if target is None:
            return self.team_order
        if target in {"archer", "archers"} and group == "archers":
            return self.team_order
        if target in {"northman", "northmen"} and group == "northmen":
            return self.team_order
        if target in key or key in target:
            return self.team_order
        return order

    def strategy_summary(self):
        strategy = getattr(self, "team_strategy", {"default": "follow", "assignments": {}})
        labels = {"sansa stark": "SANSA", "tormund": "TORMUND", "wun wun": "WUN WUN",
                  "archers": "ARCHERS", "northmen": "NORTHMEN"}
        parts = []
        if strategy.get("default", "follow") != "follow" or not strategy.get("assignments"):
            parts.append(f"TEAM {strategy.get('default', 'follow').replace('_', ' ').upper()}")
        parts.extend(f"{labels.get(target, target.upper())} {order.replace('_', ' ').upper()}"
                     for target, order in strategy.get("assignments", {}).items())
        return "  ·  ".join(parts) if parts else "TEAM FOLLOW"

    def new_enemy(self, x, y, name, health=48):
        health = max(80, round(health * 1.75))
        enemy = Combatant(x, y, name=name, color=(126, 49, 48), health=health, speed=random.randint(65, 80), radius=20)
        if "archer" in name.lower():
            enemy.sprite = self.bolton_archer_sprite or self.bolton_soldier_sprite
            enemy.ranged = True
            enemy.attack_cooldown = random.uniform(.35, 1.4)
            enemy.pending_arrow_at = None
        else:
            enemy.sprite = self.bolton_soldier_sprite
        # Spread enemies around Jon's perimeter so a group does not pile into one sprite.
        enemy.engagement_angle = 0.0
        self.enemy_spawn_index += 1
        return enemy

    def _assign_engagement_slots(self):
        count = len(self.enemies)
        if not count:
            return
        for index, enemy in enumerate(self.enemies):
            enemy.engagement_angle = math.tau * index / count

    def new_tormund(self, x, y):
        ally = Combatant(x, y, name="Tormund", color=(106, 111, 89), health=120, speed=145, radius=20)
        ally.sprite = self.tormund_sprite
        ally.follow_offset = pygame.Vector2(-105, 40)
        ally.flank_angle = -math.pi / 2
        ally.support_damage = 9
        ally.support_cooldown = 1.0
        return ally

    def new_stark_ally(self, x, y, offset):
        ally = Combatant(x, y, name="Northman", color=(76, 91, 101), health=90, speed=138, radius=19)
        ally.sprite = self.stark_soldier_sprite
        ally.follow_offset = pygame.Vector2(offset)
        ally.flank_angle = (0.0, math.pi, math.pi / 2)[self.ally_spawn_index % 3]
        self.ally_spawn_index += 1
        ally.support_damage = 7
        ally.support_cooldown = 1.35
        return ally

    def new_stark_archer(self, x, y, offset):
        ally = self.new_stark_ally(x, y, offset)
        ally.name = "Northern Archer"
        ally.sprite = self.stark_archer_sprite or self.stark_soldier_sprite
        ally.ranged = True
        ally.speed = 128
        ally.support_damage = 14
        return ally

    @staticmethod
    def chapter_name(chapter):
        return {1: "Battlefield", 2: "Shield Wall", 3: "Winterfell Courtyard"}.get(chapter, "Battlefield")

    def ai_context(self):
        context = {"chapter": self.chapter_name(self.chapter), "health": round(self.player.health) if self.player else 100,
                   "enemies": len(self.enemies), "allies": len(getattr(self, "allies", [])), "arrows": self.arrow_ammo,
                   "help_calls": self.help_calls_remaining, "ally_present": bool(getattr(self, "allies", [])), "flags": self.flags,
                   "team_strategy": getattr(self, "team_strategy", {"default": "follow", "assignments": {}})}
        named = {a.uid: a.name for a in [self.player, *getattr(self, "allies", []), *self.enemies] if a}
        context["recent_battle_events"] = [
            {k: named.get(v, v) if k in {"actor", "target"} else v for k, v in event.items()}
            for event in list(self.control.events)[-4:]]
        context["player_moves"] = self.combat.tendencies
        if self.state == "planning":
            context.update({"phase": "pre_battle_council",
                            "available_units": ["sansa stark", "tormund", "archers", "northmen"] + (["wun wun"] if self.chapter == 2 else []),
                            "cover": [{"kind": p["kind"], "position": list(p["collision"].center)} for p in self.terrain_props],
                            "planning_seconds_remaining": max(0, round(self.planning_deadline - time.monotonic())),
                            "player_strategy_notes": self.planning_notes[-6:],
                            "team_strategy": self.team_strategy})
        return context

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if getattr(event, "repeat", False) and self.state in {"title", "victory"}:
                    continue
                elif self.state == "battle" and self.conversation.active and event.key == pygame.K_RETURN:
                    self.dismiss_conversation()
                elif self.state == "battle" and self.conversation.active and event.key not in (pygame.K_e, pygame.K_t, pygame.K_b):
                    continue
                elif self.state == "title" and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self.begin_campaign()
                elif self.state == "story" and event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    if getattr(event, "repeat", False):
                        continue
                    self.advance_story()
                elif self.state == "planning" and event.key in (pygame.K_RETURN, pygame.K_SPACE) and not getattr(event, "repeat", False):
                    self.finish_planning()
                elif self.state == "planning" and event.key == pygame.K_t and not getattr(event, "repeat", False):
                    self.start_voice_capture("planning")
                elif self.state == "planning" and event.key == pygame.K_b and not getattr(event, "repeat", False):
                    self.start_voice_capture("planning")
                elif self.state == "planning" and event.key == pygame.K_TAB and not getattr(event, "repeat", False):
                    self.cycle_planning_advisor()
                elif self.state in ("battle", "defeat") and event.key == pygame.K_SPACE and self.state == "battle":
                    self.attack()
                elif self.state == "battle" and event.key == pygame.K_e and not getattr(event, "repeat", False):
                    self.ai.select_character("ramsay_bolton")
                    self.input_mode = "enemy"
                    self.start_voice_capture("enemy")
                elif self.state == "battle" and event.key == pygame.K_t and not getattr(event, "repeat", False):
                    self.input_mode = "team"
                    self.start_voice_capture("team")
                elif self.state == "battle" and event.key == pygame.K_b and not getattr(event, "repeat", False):
                    self.input_mode = "enemy"
                    self.start_voice_capture("enemy")
                elif self.state == "battle" and event.key == pygame.K_y:
                    self.ask_tactics()
                elif self.state == "battle" and event.key == pygame.K_q:
                    self.defend()
                elif self.state == "battle" and event.key == pygame.K_c:
                    self.attack(kind="heavy")
                elif self.state == "battle" and event.key == pygame.K_x:
                    self.attack(kind="feint")
                elif self.state == "battle" and event.key in (pygame.K_LALT, pygame.K_RALT):
                    self.dodge()
                elif self.state == "battle" and event.key == pygame.K_f:
                    self.call_for_help()
                elif self.state == "battle" and event.key == pygame.K_r:
                    self.shoot_arrow()
                elif self.state == "battle" and event.key == pygame.K_TAB:
                    self.cycle_dialogue_target()
                elif self.state == "battle" and event.key in (pygame.K_LSHIFT, pygame.K_RSHIFT):
                    self.start_sprint()
                elif self.state == "defeat" and event.key == pygame.K_r:
                    self.retry_after_defeat()
                elif self.state == "defeat" and event.key == pygame.K_q:
                    self.state = "title"
                elif self.state == "victory" and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self.state = "title"
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if self.state == "title":
                    self.begin_campaign()
                elif self.state == "story":
                    self.advance_story()
                elif self.state == "planning" and event.button == 1:
                    point = self.canvas_pos(event.pos)
                    if PLANNING_START_RECT.collidepoint(point):
                        self.finish_planning()
                    elif PLANNING_APPLY_RECT.collidepoint(point):
                        self.apply_planning_suggestion()
                    elif PLANNING_RESET_RECT.collidepoint(point):
                        self.team_strategy = {"default": "follow", "assignments": {}}
                    elif not self.ai.listening:
                        for character, rect in PLANNING_ADVISOR_RECTS.items():
                            if rect.collidepoint(point):
                                self.ai.select_character(character)
                                break
                elif self.state == "victory":
                    self.state = "title"
                elif self.state == "defeat":
                    canvas_pos = self.canvas_pos(event.pos)
                    if DEFEAT_RETRY_RECT.collidepoint(canvas_pos):
                        self.retry_after_defeat()
                    elif DEFEAT_TITLE_RECT.collidepoint(canvas_pos):
                        self.state = "title"
                elif self.state == "battle" and event.button == 1:
                    if self.conversation.active:
                        continue
                    point = pygame.Vector2(self.canvas_pos(event.pos))
                    if 32 <= point.x <= WIDTH - 32 and 88 <= point.y <= HEIGHT - 40:
                        point += self.camera
                        target = next((enemy for enemy in self.enemies
                                       if enemy.pos.distance_to(point) <= max(24, enemy.radius + 18)), None)
                        if target:
                            self.mouse_attack_target = target
                            self.mouse_move_target = None
                        else:
                            self.mouse_move_target = point
                            self.mouse_attack_target = None
                elif self.state == "battle" and event.button == 3:
                    if not self.conversation.active:
                        self.dodge()
    def update(self, dt):
        self.control.tick(self)
        if self.state in {"planning", "battle"}:
            signature = (self.control.battle_id, self.chapter_wave, len(self.enemies) // 4,
                         int(self.player.health // 25), len(self.allies))
            if signature != self.director_signature:
                if self.director.request("enemies", f"Battle changed: chapter {self.chapter}, wave {self.chapter_wave}, "
                                         f"{len(self.enemies)} enemy troops remain; inspect threats and coordinate."):
                    self.director_signature = signature
                    self.director.request("allies", "Prepare or adjust the allied formation. Honor Jon's explicit council/spoken orders. "
                                          "Give free units independent useful jobs and protect the wounded; do not speak at startup.")
        if self.state not in {"planning", "battle"}:
            if self.battle_audio_active:
                self.ai.cancel_speech()
                self.voice_channel.stop()
                self.battle_audio_active = False
            self.listening = self.ai.listening
            return
        self.battle_audio_active = True
        now = time.monotonic()
        council_busy = self.conversation_active() or self.voice_warming()
        self._poll_ai_and_voice()
        self.listening = self.ai.listening
        if self.state == "planning":
            self.armies.service_policy()
            elapsed = max(0, now - self.planning_last_tick)
            self.planning_last_tick = now
            self.planning_clock_paused = council_busy or self.conversation_active() or self.voice_warming()
            if self.planning_clock_paused:
                self.planning_deadline += elapsed
            if now >= self.planning_deadline:
                self.finish_planning()
            return
        self.conversation.update(self, dt)
        if self.conversation.active:
            self.screen_shake = max(0, self.screen_shake - dt * 28)
            self.armies.service_policy()
            return
        frame_dt = dt
        focused = self.conversation_active() and now < self.conversation_focus_until
        target_scale = .25 if focused else 1.0
        self.battle_time_scale += (target_scale - self.battle_time_scale) * (1 - math.exp(-dt * 9))
        dt *= self.battle_time_scale
        self.combat_time += dt
        if self.wave_pending and self.combat_time >= self.wave_spawn_at:
            self.spawn_next_wave()
        self.team_order_time = max(0.0, self.team_order_time - dt)
        if self.team_order_time == 0:
            self.team_order = "follow"
            self.team_order_actor = None
        self.screen_shake = max(0.0, self.screen_shake - dt * 28)
        self.player.moving = False
        self.player.sprint_time = max(0, self.player.sprint_time - dt)
        self.player.sprint_cooldown = max(0, self.player.sprint_cooldown - dt)
        self.player.block_time = max(0, self.player.block_time - dt)
        self.player.block_perfect_time = max(0, self.player.block_perfect_time - dt)
        self.player.block_cooldown = max(0, self.player.block_cooldown - dt)
        self.player.arrow_cooldown = max(0, self.player.arrow_cooldown - dt)
        target = self.mouse_attack_target
        if target not in self.enemies:
            self.mouse_attack_target = None
            target = None
        keys = pygame.key.get_pressed()
        move_direction = pygame.Vector2(
            float(keys[pygame.K_RIGHT]) - float(keys[pygame.K_LEFT]),
            float(keys[pygame.K_DOWN]) - float(keys[pygame.K_UP]),
        )
        keyboard_moving = move_direction.length_squared() > 0
        if keyboard_moving:
            move_direction = move_direction.normalize()
            self.mouse_move_target = None
            self.mouse_attack_target = None
            target = None
        sprint_multiplier = 1.85 if self.player.sprint_time > 0 else 1.0
        if keyboard_moving:
            self.player.move_toward(
                self.player.pos + move_direction * 100,
                dt, self.obstacles, self.combat_time,
                crowd=[*self.allies, *self.enemies],
                speed_multiplier=sprint_multiplier,
            )
        elif target:
            delta = target.pos - self.player.pos
            distance = delta.length()
            stand_off = self.player.radius + target.radius + 18
            if distance > stand_off + 5:
                self.player.move_toward(target.pos - delta.normalize() * stand_off,
                                        dt, self.obstacles, self.combat_time,
                                        crowd=[*self.allies, *(enemy for enemy in self.enemies if enemy is not target)],
                                        speed_multiplier=sprint_multiplier)
            else:
                self.player.moving = False
                self.player.facing = delta.normalize() if distance > 0 else self.player.facing
                self.player._update_animation(self.combat_time)
                if self.player.attack_cooldown <= 0:
                    self.attack(target)
        elif self.mouse_move_target is not None:
            if self.player.pos.distance_to(self.mouse_move_target) <= 9:
                self.mouse_move_target = None
            else:
                self.player.move_toward(self.mouse_move_target, dt, self.obstacles, self.combat_time,
                                        crowd=[*self.allies, *self.enemies],
                                        speed_multiplier=sprint_multiplier)
        self.player._update_animation(self.combat_time)
        self.player.attack_cooldown = max(0, self.player.attack_cooldown - dt)
        self.player.flash = max(0, self.player.flash - dt)
        self.player.invulnerable = max(0, self.player.invulnerable - dt)
        self.armies.update(dt)
        for shot in self.pending_support_shots[:]:
            if self.combat_time >= shot["release_at"]:
                self.pending_support_shots.remove(shot)
                if shot["shooter"].alive and shot["target"].alive:
                    self._shoot_support_arrow(shot["shooter"], shot["target"], shot["damage"], animate=False)
        self.combat.update(dt)
        self._update_projectiles(dt)
        self.effects = [e for e in self.effects if time.monotonic() - e[0] < (.95 if e[2] == "help" else .42)]
        self.player.health = max(0, self.player.health)
        self.update_camera(frame_dt)
        if self.player.health <= 0:
            self.state = "defeat"
            self.flags["allies"] = True
            self.flags["archers"] = True
        elif not self.enemies:
            if self.wave_pending:
                pass
            elif self.chapter_wave < self.chapter_wave_count:
                self.queue_next_wave()
            elif self.chapter == 1:
                self.begin_story(2)
            elif self.chapter == 2:
                self.begin_story(3)
            else:
                self.flags["won"] = True
                self.state = "victory"
                self.chapter = 4
                self.add_dialogue("JON SNOW", "Winterfell is ours. The North is home again.")
                self.add_dialogue("RAMSAY BOLTON", self.ai.scripted_line("ramsay_bolton", "death", "No... this is my home!"))
    def _poll_ai_and_voice(self):
        now = time.monotonic()
        state = self.ai.poll()
        if state and state.get("transcript"):
            channel = state.get("channel") or self.voice_capture_mode or self.input_mode
            stale_capture = (self.state == "planning") != (channel == "planning")
            if stale_capture:
                print(f"[voice] discarded stale {channel} transcript during {self.state}", flush=True)
            else:
                latency = self.ai.last_stt_latency
                latency_text = f" in {latency:.2f}s" if latency is not None else ""
                total = state.get("total_latency")
                total_text = f" ({total:.2f}s capture-to-text)" if total is not None else ""
                print(f"[voice] {channel} transcript{latency_text}{total_text}: {state['transcript']}", flush=True)
                self.handle_voice_transcript(state["transcript"], channel)
            self.voice_capture_mode = None
        elif state and state.get("notice"):
            channel = state.get("channel") or self.voice_capture_mode or self.input_mode
            total = state.get("total_latency")
            total_text = f" ({total:.2f}s)" if total is not None else ""
            print(f"[voice] {channel} input notice{total_text}: {state['notice']}", flush=True)
            self.add_dialogue("VOICE INPUT", state["notice"])
            self.voice_capture_mode = None
        elif state and state.get("request_id"):
            entry = next((item for item in self.dialogue if item.get("request_id") == state["request_id"]), None)
            if (entry and entry.get("provisional") and state["request_id"] == self.latest_dialogue_request_id
                    and time.monotonic() - entry.get("created_at", 0) <= entry.get("max_age", self.ai.max_dialogue_seconds)):
                if not entry.get("fallback_spoken"):
                    print(f"[voice] {state.get('source', 'codex')} reply in {self.ai.last_latency or 0:.2f}s: {state['text']}", flush=True)
                    entry["text"] = state["text"]
                    entry["provisional"] = False
                    entry["source"] = state.get("source", "codex")
                    if self.state == "planning" and entry["source"] == "codex":
                        self.planning_suggestion = state.get("orders", [])
                    if entry.get("voice"):
                        self.ai.speak(state["text"], character_slug=state["character"], request_id=state["request_id"])
                    self.conversation.reply(state["text"])
        for entry in self.dialogue:
            if (entry.get("provisional") and not entry.get("fallback_spoken")
                    and now - entry.get("created_at", now) >= entry.get("max_age", self.ai.max_dialogue_seconds)):
                entry["provisional"] = False
                entry["fallback_spoken"] = True
                entry["text"] = entry.get("fallback_text", "Hold a moment. Keep the line together.")
                entry["source"] = "fallback"
                self.conversation.reply(entry["text"])
                if entry.get("voice") and entry.get("request_id") == self.latest_dialogue_request_id:
                    self.ai.speak(entry["text"], character_slug=entry.get("character"), request_id=entry.get("request_id"))
        if not self.voice_channel.get_busy():
            if self.voice_path:
                Path(self.voice_path).unlink(missing_ok=True)
                self.voice_path = None
                self.voice_sound = None
            speech_item = self.ai.poll_speech()
            if speech_item:
                speech_path, request_id, epoch = speech_item
            else:
                speech_path = None
                request_id = None
                epoch = self.ai.speech_epoch
            if speech_path and epoch == self.ai.speech_epoch and (request_id is None or request_id == self.latest_dialogue_request_id):
                try:
                    self.voice_sound = pygame.mixer.Sound(speech_path)
                    self.voice_sound.set_volume(.9)
                    self.voice_channel.play(self.voice_sound)
                    self.voice_path = speech_path
                    self.ai.last_tts_error = ""
                except (pygame.error, OSError) as exc:
                    Path(speech_path).unlink(missing_ok=True)
                    self.ai.last_tts_error = f"Audio playback: {exc}"
            elif speech_path:
                Path(speech_path).unlink(missing_ok=True)
        tactic = self.ai.poll_tactic()
        if tactic and self.state == "battle":
            self.apply_tactic(tactic)

    def attack(self, target=None, kind="quick"):
        return self.combat.begin(self.player, target, kind)

    def damage_enemy(self, target, amount, *, sound_volume=.6, shake=1.5, knockback_direction=None):
        if target not in self.enemies:
            return
        if target.name == "Ramsay Bolton" and not self.ramsay_reacted_to_hit:
            self.ramsay_reacted_to_hit = True
            self.add_dialogue("RAMSAY BOLTON", self.ai.scripted_line("ramsay_bolton", "jon_hits_ramsay", "You will pay for that, Snow."))
            self.add_dialogue("JON SNOW", self.ai.scripted_line("jon_snow", "boss_hit", "That was for Rickon."))
        impact_pos = target.pos.copy()
        direction = pygame.Vector2(knockback_direction) if knockback_direction is not None else target.pos - self.player.pos
        if not direction.length_squared():
            direction = target.facing.copy()
        if direction.length_squared():
            force = min(18, 6 + amount * .24)
            if target.name == "Ramsay Bolton":
                force *= .8
            target.pos += direction.normalize() * force
            target.pos.x = clamp(target.pos.x, 32, WORLD_WIDTH - 32)
            target.pos.y = clamp(target.pos.y, WORLD_PLAY_TOP, WORLD_HEIGHT - 38)
            target._resolve_obstacles(self.obstacles)
        target.health -= amount
        if (target.health > 0 and target.health <= target.max_health * .35
                and not getattr(target, "retreat_triggered", False)):
            # Wounded fighters try to create space before they commit again.
            target.retreat_triggered = True
            target.retreat_until = self.combat_time + .85
        target.flash = .22
        target.set_animation("hit", self.combat_time, .2)
        self.effects.append([time.monotonic(), impact_pos, "hit"])
        self.play_hit_sound(sound_volume)
        self.screen_shake = max(self.screen_shake, shake)
        if target.health <= 0:
            target.alive = False
            self.enemies.remove(target)
            if target.name == "Ramsay Bolton":
                self.add_dialogue("RAMSAY BOLTON", self.ai.scripted_line("ramsay_bolton", "death", "No... this is my home!"))

    def shoot_arrow(self):
        if self.arrow_ammo <= 0 or self.player.arrow_cooldown > 0 or self.player.stamina < 12:
            if self.arrow_ammo <= 0:
                if not self.dialogue or self.dialogue[-1].get("event") != "empty_arrows":
                    self.add_dialogue("JON SNOW", "No arrows left. I must close the distance.", event="empty_arrows")
            return
        direction = self.player.facing.normalize() if self.player.facing.length_squared() else pygame.Vector2(1, 0)
        self.arrow_ammo -= 1
        self.player.stamina -= 12
        self.player.arrow_cooldown = .42
        self.projectiles.append({
            "pos": self.player.pos + pygame.Vector2(0, -27) + direction * 25,
            "velocity": direction * 590,
            "life": 1.15,
            "damage": 24,
            "color": (245, 204, 126),
            "trail": [],
        })
        if self.attack_sound:
            self.attack_sound.set_volume(.16)
            self.attack_sound.play()

    def _begin_support_shot(self, shooter, target, damage):
        if target not in self.enemies:
            return
        direction = (target.pos + pygame.Vector2(0, -27)) - (shooter.pos + pygame.Vector2(0, -25))
        if direction.length_squared():
            shooter.facing = direction.normalize()
        shooter.set_animation("attack", self.combat_time, .72)
        shooter.attack_cooldown = 1.55 if shooter.name == "Sansa Stark" else 1.25
        self.pending_support_shots.append({
            "shooter": shooter,
            "target": target,
            "damage": damage,
            "release_at": self.combat_time + .5,
        })

    def _shoot_support_arrow(self, shooter, target, damage, *, origin=None, animate=True):
        if not target.alive:
            return
        start = pygame.Vector2(origin) if origin is not None else shooter.pos + pygame.Vector2(0, -25)
        aim = target.pos + pygame.Vector2(0, -27)
        delta = aim - start
        if not delta.length_squared():
            return
        direction = delta.normalize()
        self.projectiles.append({
            "pos": start.copy(),
            "velocity": direction * 680,
            "life": 1.5,
            "damage": damage,
            "color": (171, 203, 155),
            "trail": [],
            "faction": "enemy" if shooter in self.enemies else "ally",
        })
        if shooter:
            shooter.facing = direction
            if animate:
                shooter.set_animation("attack", self.combat_time, .72)

    def _update_projectiles(self, dt):
        for projectile in self.projectiles[:]:
            projectile["trail"].insert(0, projectile["pos"].copy())
            del projectile["trail"][9:]
            projectile["pos"] += projectile["velocity"] * dt
            projectile["life"] -= dt
            pos = projectile["pos"]
            blocked = any(obstacle.collidepoint(round(pos.x), round(pos.y)) for obstacle in self.obstacles)
            hostile = projectile.get("faction") == "enemy"
            opponents = [self.player, *self.allies] if hostile else self.enemies
            target = next((actor for actor in opponents if actor.alive and
                           (actor.pos + pygame.Vector2(0, -27)).distance_to(pos) < actor.radius + 10), None)
            if target:
                if target is self.player:
                    self.damage_player(projectile["damage"], -projectile["velocity"])
                else:
                    self.combat.damage(target, projectile["damage"], -projectile["velocity"])
                self.effects.append([time.monotonic(), pos.copy(), "arrow_impact"])
                self.projectiles.remove(projectile)
            elif blocked or projectile["life"] <= 0 or not (0 <= pos.x <= WORLD_WIDTH and 0 <= pos.y <= WORLD_HEIGHT):
                if blocked:
                    self.effects.append([time.monotonic(), pos.copy(), "arrow_impact"])
                self.projectiles.remove(projectile)

    def damage_player(self, amount, incoming, *, attacker=None):
        if self.player.invulnerable > 0:
            return False
        incoming = pygame.Vector2(incoming)
        toward_attacker = incoming.normalize() if incoming.length_squared() else pygame.Vector2(-1, 0)
        facing_attack = self.player.facing.dot(toward_attacker) > .15
        if self.player.block_time > 0 and facing_attack:
            perfect = self.player.block_perfect_time > 0
            self.player.health -= 0 if perfect else max(1, round(amount * .3))
            self.player.invulnerable = .24
            if attacker:
                attacker.attack_cooldown = max(attacker.attack_cooldown, 1.25 if perfect else .9)
                if perfect:
                    attacker.set_animation("hit", self.combat_time, .28)
                    attacker.pos += toward_attacker * 9
                    attacker.pos.x = clamp(attacker.pos.x, 32, WORLD_WIDTH - 32)
                    attacker.pos.y = clamp(attacker.pos.y, WORLD_PLAY_TOP, WORLD_HEIGHT - 38)
                    attacker._resolve_obstacles(self.obstacles)
            self.effects.append([time.monotonic(), self.player.pos + toward_attacker * 20, "block"])
            self.play_hit_sound(.76)
            self.screen_shake = max(self.screen_shake, 1.4 if perfect else 2.1)
            self.player.block_time = 0
            self.player.block_perfect_time = 0
        else:
            self.player.health -= amount
            self.player.invulnerable = .46
            self.player.flash = .18
            self.player.set_animation("hit", self.combat_time, .2)
            self.player.pos -= toward_attacker * min(18, 6 + amount * .55)
            self.player.pos.x = clamp(self.player.pos.x, 32, WORLD_WIDTH - 32)
            self.player.pos.y = clamp(self.player.pos.y, WORLD_PLAY_TOP, WORLD_HEIGHT - 38)
            self.player._resolve_obstacles(self.obstacles)
            self.effects.append([time.monotonic(), self.player.pos.copy(), "hit"])
            self.play_hit_sound(.72)
            self.screen_shake = max(self.screen_shake, 3.2)
        return True

    def defend(self):
        return self.combat.guard(self.player)

    def dodge(self):
        keys = pygame.key.get_pressed()
        direction = pygame.Vector2(float(keys[pygame.K_RIGHT]) - float(keys[pygame.K_LEFT]),
                                   float(keys[pygame.K_DOWN]) - float(keys[pygame.K_UP]))
        return self.combat.dodge(self.player, direction if direction.length_squared() else None)

    def call_for_help(self):
        if self.help_calls_remaining <= 0:
            return
        spawn_x = clamp(self.player.pos.x - 240, 100, WORLD_WIDTH - 100)
        for index, offset in enumerate(((-185, 95), (-155, 180))):
            spawn_y = clamp(self.player.pos.y + (index - .5) * 70, WORLD_PLAY_TOP, WORLD_HEIGHT - 65)
            reinforcement = self.new_stark_archer(spawn_x, spawn_y, offset)
            reinforcement.health = reinforcement.max_health = 82
            reinforcement.attack_cooldown = .35 + .3 * index
            self.allies.append(reinforcement)
        self.help_calls_remaining -= 1
        self.effects.append([time.monotonic(), reinforcement.pos.copy(), "help"])
        self.add_dialogue("JON SNOW", self.ai.scripted_line("jon_snow", "help_call", "To me! The North stands with us!"))

    def issue_team_order(self, line):
        self.stop_voice_playback()
        self.control.latest_ally_instruction = {"id": uuid.uuid4().hex, "text": line, "at": time.time()}
        action, _ = self.ai.decide_team_order(line, self.ai_context())
        target = self.strategy_target_from_phrase(line)
        self.ai.select_character("sansa_stark" if target == "sansa stark" else "tormund_giantsbane")
        if action != "unrecognized" and target != "ambiguous":
            self.team_order_actor = target
            self.set_team_order(action, acknowledge=False)
            self.team_order_feedback = "ORDER ACTIVE · " + action.replace("_", " ").upper()
        else:
            self.team_order_feedback = "TEAM IS INTERPRETING YOUR STRATEGY"
        self.team_order_feedback_until = time.monotonic() + 5
        self.director.request("allies", "Jon's spoken battlefield instruction: " + line, force=True)
        self.conversation.listener = self.dialogue_actor(self.ai.active_character)
        self.send_player_line(line, voice=True)

    def set_team_order(self, action, acknowledge=True):
        self.team_order = action
        self.team_order_time = 12.0
        if not acknowledge:
            return
        actor = (self.team_order_actor or "").lower()
        if "sansa" in actor:
            character, speaker = "sansa_stark", "SANSA STARK"
        else:
            # Tormund speaks for the group and relays Wun Wun's response.
            character, speaker = "tormund_giantsbane", "TORMUND GIANTSBANE"
        action_words = {
            "follow": "stay with you",
            "cover": "cover you",
            "focus": "focus Ramsay",
            "target_archers": "take their archers",
            "flank_left": "flank from the left",
            "flank_right": "flank from the right",
            "hold": "hold this ground",
            "retreat": "fall back to you",
        }
        template = self.ai.scripted_line(
            character, "order_ack", "Aye, Jon. We'll {action}." if character == "tormund_giantsbane"
            else "Understood, Jon. I'll {action}."
        )
        line = template.replace("{action}", action_words[action])
        self.add_dialogue(speaker, line, voice=True)

    def start_sprint(self):
        if self.player.sprint_cooldown > 0 or self.player.stamina < 18:
            return
        self.player.stamina -= 18
        self.player.sprint_time = .46
        self.player.sprint_cooldown = 1.55
        self.effects.append([time.monotonic(), self.player.pos.copy(), "sprint"])

    def retry_after_defeat(self):
        self.flags["allies"] = True
        self.flags["archers"] = True
        self.arrow_ammo = self.max_arrow_ammo
        self.begin_story(1)

    def play_hit_sound(self, volume=0.6):
        if self.hit_sound:
            self.hit_sound.set_volume(volume)
            self.hit_sound.play()

    def apply_tactic(self, action):
        # The NPC's editable policy returns a constrained intent. The game applies it.
        self.ai_tactic = action
        if action == "press":
            for enemy in self.enemies:
                enemy.speed = min(150, enemy.speed * 1.18)
        elif action == "withdraw":
            for enemy in self.enemies:
                enemy.speed = max(55, enemy.speed * .75)
        elif action == "call_archers":
            if self.chapter == 1 and self.combat_time < 28:
                self.enemies.append(self.new_enemy(
                    clamp(self.player.pos.x + 420, 55, WORLD_WIDTH - 55),
                    random.randint(WORLD_PLAY_TOP, WORLD_HEIGHT - 85), "Bolton archer", 40
                ))
                self._assign_engagement_slots()
        elif action == "feint":
            for enemy in self.enemies:
                enemy.attack_cooldown = max(enemy.attack_cooldown, .5)

    def ask_tactics(self):
        self.director.request("enemies", "Review the current fight and revise tactics or the shared policy.", force=True)

    def cycle_dialogue_target(self):
        targets = ["ramsay_bolton", "sansa_stark", "tormund_giantsbane"]
        current = self.ai.active_character
        self.ai.select_character(targets[(targets.index(current) + 1) % len(targets)])

    def send_player_line(self, line, *, voice=False):
        self.stop_voice_playback()
        for old_entry in self.dialogue:
            if old_entry.get("provisional"):
                old_entry["provisional"] = False
                old_entry["text"] = "Interrupted by your next message."
                old_entry["source"] = "interrupted"
        self.dialogue_request_seq += 1
        request_id = f"conversation-{self.dialogue_request_seq}"
        self.latest_dialogue_request_id = request_id
        self.conversation_focus_until = time.monotonic() + 30
        if self.state == "planning":
            self.planning_suggestion = []
        speaker = self.ai.character_name.upper()
        reply = self.ai.scripted_reply(self.ai.active_character, line)
        player_label = "YOU · TEAM" if self.state == "planning" or self.input_mode == "team" else "YOU · BOLTON"
        self.add_dialogue(player_label, line, player_input=True)
        context = self.ai_context()
        context["channel"] = self.input_mode
        entry = self.add_dialogue(speaker, "Considering your plan…" if self.state == "planning" else "Preparing a reply…",
                                  request_id=request_id, created_at=time.monotonic(), provisional=True,
                                  fallback_text=reply, character=self.ai.active_character,
                                  voice=True, max_age=self.ai.dialogue_timeout(context, voice))
        entry["fallback_spoken"] = False
        self.ai.send_player_line(line, context, voice=voice, request_id=request_id)

    def dismiss_conversation(self):
        self.stop_voice_playback()
        self.ai.cancel_dialogue()
        self.latest_dialogue_request_id = None
        self.ai.latest_dialogue_request_id = None
        for entry in self.dialogue:
            if entry.get("provisional"):
                entry.update(provisional=False, text="Conversation ended.", source="interrupted")
        self.conversation.finish()

    def dialogue_actor(self, slug):
        if slug == "ramsay_bolton":
            return self.commander
        needle = "sansa" if slug == "sansa_stark" else "tormund"
        return next((a for a in getattr(self, "allies", []) if needle in a.name.lower()), self.player)

    def handle_voice_transcript(self, transcript, channel):
        """Route speech based on the key that started this recording."""
        if self.state == "planning":
            if re.sub(r"[^a-z ]", "", transcript.lower()).strip() in {
                    "apply that", "use that plan", "apply plan", "accept plan", "do that"}:
                self.add_dialogue("YOU · TEAM", transcript, player_input=True)
                self.apply_planning_suggestion()
                return
            if self.planning_done_phrase(transcript):
                self.add_dialogue("YOU · TEAM", transcript, player_input=True)
                self.finish_planning()
                return
            self.planning_notes.append(transcript)
            action, _ = self.ai.decide_team_order(transcript, self.ai_context())
            target = self.strategy_target_from_phrase(transcript)
            if target == "sansa stark":
                self.ai.select_character("sansa_stark")
            elif target == "tormund":
                self.ai.select_character("tormund_giantsbane")
            if target == "ambiguous":
                self.team_order_feedback = "PLAN NOT APPLIED · GIVE ONE UNIT ORDER AT A TIME"
                self.team_order_feedback_until = time.monotonic() + 3.5
            elif action != "unrecognized":
                if target:
                    self.team_strategy["assignments"][target] = action
                    self.team_strategy.setdefault("positions", {}).pop(target, None)
                else:
                    self.team_strategy["default"] = action
                    self.team_strategy["explicit_default"] = True
                    self.team_strategy["assignments"].clear()
                    self.team_strategy["positions"] = {}
                target_label = (target or "team").replace("_", " ").upper()
                self.team_order_feedback = f"PLAN SET · {target_label} → {action.replace('_', ' ').upper()}"
                self.team_order_feedback_until = time.monotonic() + 3.5
            return self.send_player_line(transcript, voice=True)
        if channel == "team":
            return self.issue_team_order(transcript)
        return self.send_player_line(transcript, voice=True)

    def start_voice_capture(self, channel="enemy"):
        if self.voice_warming():
            self.add_dialogue("VOICE INPUT", "Voice models are warming up. The council clock is paused.")
            return
        if self.ai.listening:
            target = {"team": "TEAM", "planning": "WAR COUNCIL"}.get(self.voice_capture_mode, "BOLTON")
            self.add_dialogue("VOICE INPUT", f"Already listening to {target}. Finish that phrase first.")
            return
        channel = channel if channel in {"team", "planning"} else "enemy"
        self.input_mode = channel
        self.voice_capture_mode = channel
        self.conversation_focus_until = time.monotonic() + 30
        self.ai.cancel_dialogue()
        self.latest_dialogue_request_id = None
        self.ai.latest_dialogue_request_id = None
        for entry in self.dialogue:
            if entry.get("provisional"):
                entry["provisional"] = False
                entry["text"] = "Interrupted by your next message."
                entry["source"] = "interrupted"
        self.stop_voice_playback()
        if self.state == "battle":
            if channel == "team":
                self.ai.select_character("tormund_giantsbane")
            self.conversation.start(self.player, self.dialogue_actor(self.ai.active_character))
        self.listening = self.ai.start_listening(self.ai_context(), channel=channel)

    def draw(self):
        self.canvas.fill((32, 40, 45))
        if self.state in {"battle", "defeat", "victory"} and self.player:
            screen_canvas = self.canvas
            self.canvas = self.world_canvas
            self.draw_battlefield()
            self.canvas = screen_canvas
            view = self.conversation.view(self, WIDTH, HEIGHT, WORLD_WIDTH, WORLD_HEIGHT)
            if view.size == (WIDTH, HEIGHT):
                self.canvas.blit(self.world_canvas, (0, 0), view)
            else:
                self.canvas.blit(pygame.transform.smoothscale(self.world_canvas.subsurface(view), (WIDTH, HEIGHT)), (0, 0))
            self.conversation.draw_focus(self.canvas, view)
        else:
            self.canvas.blit(self.menu_background, (0, 0))
        if self.state == "title":
            self.draw_title()
        elif self.state == "story":
            self.draw_story()
        elif self.state == "planning":
            self.draw_planning()
        elif self.state == "battle":
            self.draw_hud()
        elif self.state in ("defeat", "victory"):
            self.draw_ending()
        scaled = pygame.transform.smoothscale(self.canvas, self.screen.get_size())
        self.screen.fill((10, 12, 16))
        shake = self.screen_shake if self.state == "battle" else 0.0
        offset = (round(math.sin(self.combat_time * 76) * shake), round(math.cos(self.combat_time * 59) * shake * .65))
        self.screen.blit(scaled, offset)
        pygame.display.flip()

    def draw_actor_labels(self, actors):
        """Place important name tags without stacking them over nearby characters."""
        named = [actor for actor in actors if actor is self.player or actor.name in {
            "Sansa Stark", "Tormund", "Wun Wun", "Ramsay Bolton"
        }]
        named.sort(key=lambda actor: 0 if actor is self.player else 1 if actor.name == "Ramsay Bolton" else 2)
        occupied = []
        for actor in named:
            sprite = getattr(actor, "sprite", None)
            frame_height = sprite.frames["idle"][0].get_height() if sprite else actor.radius * 2
            base_y = actor.pos.y + 23 - frame_height - 10 if sprite else actor.pos.y - actor.radius - 21
            color = GOLD if actor is self.player else IVORY
            label = self.small.render(actor.name.upper(), True, color)
            candidates = []
            for dx in (0, -28, 28, -56, 56, -84, 84):
                for dy in (0, -18, 18, -36, 36):
                    center_x = clamp(actor.pos.x + dx, label.get_width() / 2 + 8, WORLD_WIDTH - label.get_width() / 2 - 8)
                    center_y = clamp(base_y + dy, WORLD_PLAY_TOP, WORLD_HEIGHT - 145)
                    rect = label.get_rect(center=(round(center_x), round(center_y)))
                    box = rect.inflate(12, 7)
                    overlap = sum(box.clip(old).width * box.clip(old).height for old in occupied)
                    candidates.append((overlap * 1000 + abs(dx) + abs(dy) * 1.4, box, rect))
            _, box, rect = min(candidates, key=lambda item: item[0])
            tag = pygame.Surface(box.size, pygame.SRCALPHA)
            pygame.draw.rect(tag, (13, 17, 22, 198), tag.get_rect(), border_radius=4)
            border = (142, 121, 85, 205) if actor is self.player else (86, 95, 102, 190)
            pygame.draw.rect(tag, border, tag.get_rect(), 1, border_radius=4)
            self.canvas.blit(tag, box)
            self.canvas.blit(label, rect)
            occupied.append(box)

    def draw_battlefield(self):
        self.canvas.blit(self.battlefield_image, (0, 0))
        self.canvas.blit(self.battlefield_shade, (0, 0))
        if self.state in ("battle", "defeat", "victory") and self.player:
            actors = [*getattr(self, "allies", []), *self.enemies, self.player]
            if self.commander and self.commander.alive and self.commander not in self.enemies:
                actors.append(self.commander)
            draw_jobs = [(prop["collision"].bottom, 0, prop) for prop in self.terrain_props]
            draw_jobs.extend((round(actor.pos.y + 23), 1, actor) for actor in actors)
            for _, kind, item in sorted(draw_jobs, key=lambda job: job[0]):
                if kind == 0:
                    self.canvas.blit(item["image"], item["rect"])
                    continue
                if item is self.player:
                    pygame.draw.ellipse(self.canvas, (196, 166, 105), (round(item.pos.x) - 25, round(item.pos.y) + 14, 50, 12), 2)
                    item.draw(self.canvas, self.combat_time, hero=True, sprite=getattr(item, "sprite", None),
                              speaking=self.conversation.stage == "player")
                    if item.block_time > 0:
                        center = (round(item.pos.x), round(item.pos.y - 8))
                        radius = 35
                        angle = math.atan2(item.facing.y, item.facing.x)
                        pygame.draw.arc(self.canvas, (210, 198, 151), (center[0] - radius, center[1] - radius, radius * 2, radius * 2), angle - .78, angle + .78, 4)
                else:
                    item.draw(self.canvas, self.combat_time, sprite=getattr(item, "sprite", None),
                              show_health=item in self.enemies or item in getattr(self, "allies", []),
                              speaking=self.conversation.active and item is self.conversation.listener)
            self.draw_actor_labels(actors)
            for arrow in self.projectiles:
                direction = arrow["velocity"].normalize()
                pos = arrow["pos"]
                hostile = arrow.get("faction") == "enemy"
                for index, trail_pos in enumerate(arrow["trail"]):
                    fade = max(35, 145 - index * 36)
                    trail_end = trail_pos - direction * max(4, 18 - index)
                    trail_color = (fade, round(fade * .35), 75) if hostile else (fade, round(fade * .82), 115)
                    pygame.draw.line(self.canvas, trail_color, (round(trail_pos.x), round(trail_pos.y)), (round(trail_end.x), round(trail_end.y)), max(1, 3 - index // 3))
                arrow_image = self.hostile_arrow_projectile if hostile else self.arrow_projectile
                if arrow_image:
                    angle = int(round(math.degrees(math.atan2(direction.y, direction.x)) / 5) * 5) % 360
                    cache_key = (hostile, angle)
                    rotated = self.arrow_rotation_cache.get(cache_key)
                    if rotated is None:
                        rotated = pygame.transform.rotate(arrow_image, -angle)
                        self.arrow_rotation_cache[cache_key] = rotated
                    self.canvas.blit(rotated, rotated.get_rect(center=(round(pos.x), round(pos.y))))
            for created, pos, kind in self.effects:
                age = time.monotonic() - created
                if kind == "slash":
                    alpha = max(0, 190 * (1 - age / .24))
                    s = pygame.Surface((60, 60), pygame.SRCALPHA)
                    pygame.draw.arc(s, (224, 216, 188, int(alpha)), (5, 5, 50, 50), .25, 2.7, 5)
                    self.canvas.blit(s, (pos.x - 30, pos.y - 30))
                elif kind == "sprint":
                    pygame.draw.circle(self.canvas, (190, 211, 221), (round(pos.x), round(pos.y)), 17 + round(age * 40), 2)
                elif kind == "arrow_shot":
                    pygame.draw.circle(self.canvas, (238, 205, 131), (round(pos.x), round(pos.y)), 12 + round(age * 42), 2)
                elif kind == "arrow_impact":
                    alpha = max(0, 190 * (1 - age / .26))
                    radius = 5 + round(age * 52)
                    sparks = pygame.Surface((radius * 2 + 12, radius * 2 + 12), pygame.SRCALPHA)
                    center = (radius + 6, radius + 6)
                    pygame.draw.circle(sparks, (245, 219, 158, int(alpha)), center, radius, 2)
                    for ray in range(8):
                        angle = ray * math.tau / 8
                        start = (round(center[0] + math.cos(angle) * (radius - 2)), round(center[1] + math.sin(angle) * (radius - 2)))
                        end = (round(center[0] + math.cos(angle) * (radius + 5)), round(center[1] + math.sin(angle) * (radius + 5)))
                        pygame.draw.line(sparks, (255, 227, 174, int(alpha)), start, end, 2)
                    self.canvas.blit(sparks, (round(pos.x) - center[0], round(pos.y) - center[1]))
                elif kind == "arrow":
                    pygame.draw.circle(self.canvas, (236, 205, 131), (round(pos.x), round(pos.y)), 8 + round(age * 20), 2)
                elif kind == "help":
                    pygame.draw.circle(self.canvas, (166, 198, 166), (round(pos.x), round(pos.y)), 14 + round(age * 26), 2)
                elif kind == "hit":
                    sparks = pygame.Surface((72, 72), pygame.SRCALPHA)
                    alpha = max(0, round(255 * (1 - age / .42)))
                    radius = 7 + round(age * 34)
                    center = (36, 36)
                    pygame.draw.circle(sparks, (255, 208, 129, alpha), center, radius, 2)
                    pygame.draw.line(sparks, (255, 229, 179, alpha), (center[0] - radius - 5, center[1]), (center[0] + radius + 5, center[1]), 2)
                    pygame.draw.line(sparks, (231, 92, 63, alpha), (center[0], center[1] - radius - 5), (center[0], center[1] + radius + 5), 2)
                    self.canvas.blit(sparks, (round(pos.x) - 36, round(pos.y) - 36))
                elif kind == "block":
                    sparks = pygame.Surface((68, 68), pygame.SRCALPHA)
                    alpha = max(0, round(255 * (1 - age / .42)))
                    pygame.draw.circle(sparks, (194, 223, 221, alpha), (34, 34), 12 + round(age * 35), 3)
                    pygame.draw.line(sparks, (242, 215, 151, alpha), (9, 34), (59, 34), 2)
                    pygame.draw.line(sparks, (242, 215, 151, alpha), (34, 9), (34, 59), 2)
                    self.canvas.blit(sparks, (round(pos.x) - 34, round(pos.y) - 34))

    def panel(self, rect, color=(17, 21, 27, 230), border=GOLD):
        layer = pygame.Surface(rect.size, pygame.SRCALPHA)
        layer.fill(color)
        self.canvas.blit(layer, rect.topleft)
        pygame.draw.rect(self.canvas, border, rect, 1, border_radius=4)

    def draw_title(self):
        self.panel(pygame.Rect(80, 72, 940, 550), (12, 15, 21, 236))
        self.blit_text("A FAN-MADE TALE OF THE NORTH", 140, 148, self.small, GOLD)
        self.blit_text("IRON & SNOW", 135, 195, self.title, IVORY)
        self.blit_text("THE BASTARD'S WINTER", 141, 273, self.font, (190, 200, 207))
        pygame.draw.line(self.canvas, GOLD, (140, 320), (950, 320), 1)
        for i, line in enumerate(["The Boltons hold Winterfell.", "The North has one last chance to take it back.", "Three fronts. Seven combat phases. One final duel."]):
            self.blit_text(line, 142, 342 + i * 29, self.font, IVORY)
        self.blit_text("ENTER  ·  BEGIN THE STORY", 142, 445, self.font, GOLD)
        self.blit_text("ARROWS MOVE · SPACE SLASH · C HEAVY · X FEINT · Q PARRY · ALT / RIGHT CLICK DODGE", 142, 488, self.small, IVORY)
        self.blit_text("B TALK · E RAMSAY · T TEAM · SHIFT RUN · R ARROW · F REINFORCE · TAB TARGET", 142, 515, self.small, IVORY)
        self.blit_text("For team orders, press T, say one short command, then pause. The order applies immediately.", 142, 546, self.small, MUTED)
        self.blit_text("60-SECOND WAR COUNCIL BEFORE EACH FRONT  ·  DIRECT THE NORTH  ·  RECLAIM WINTERFELL", 142, 582, self.small, MUTED)

    def draw_story(self):
        self.panel(pygame.Rect(120, 150, 860, 410), (16, 19, 25, 238))
        self.blit_text(self.story_lines[0], 160, 188, self.small, GOLD)
        line = self.story_lines[min(self.story_index + 1, len(self.story_lines) - 1)]
        words = line.split()
        y, row = 250, ""
        for word in words:
            trial = f"{row} {word}".strip()
            if self.font.size(trial)[0] > 760:
                self.blit_text(row, 160, y, self.font, IVORY)
                row, y = word, y + 37
            else:
                row = trial
        self.blit_text(row, 160, y, self.font, IVORY)
        self.blit_text("CLICK / SPACE / ENTER  ·  CONTINUE", 160, 530, self.small, GOLD)

    def draw_planning(self):
        veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        veil.fill((8, 12, 18, 190))
        self.canvas.blit(veil, (0, 0))
        self.panel(pygame.Rect(80, 42, 940, 616), (14, 18, 25, 245), (149, 127, 87))
        self.blit_text("WAR COUNCIL", 120, 68, self.title, IVORY)
        self.blit_text(f"{self.chapter_name(self.chapter).upper()} · AGREE ON YOUR OPENING MOVES", 124, 130, self.small, GOLD)
        remaining = max(0, math.ceil(self.planning_deadline - time.monotonic()))
        timer_rect = pygame.Rect(850, 65, 128, 70)
        self.panel(timer_rect, (31, 35, 40, 245), GOLD)
        timer_text = self.font.render(f"{remaining:02d}", True, IVORY)
        self.canvas.blit(timer_text, timer_text.get_rect(center=(timer_rect.centerx, timer_rect.centery - 8)))
        self.blit_text("PAUSED" if self.planning_clock_paused else "SECONDS", timer_rect.x + 34, timer_rect.y + 47, self.small, GOLD)

        advisor_info = {
            "sansa_stark": ("SANSA STARK", "RESERVE · ARCHERS · POSITION"),
            "tormund_giantsbane": ("TORMUND GIANTSBANE", "FRONT LINE · FLANKS · RESCUE"),
        }
        for character, rect in PLANNING_ADVISOR_RECTS.items():
            selected = self.ai.active_character == character
            self.panel(rect, (42, 39, 33, 240) if selected else (24, 29, 35, 235),
                       GOLD if selected else (91, 101, 107))
            name, specialty = advisor_info[character]
            portrait = pygame.Rect(rect.x + 18, rect.y + 22, 74, 86)
            self.draw_dialogue_portrait(name, portrait)
            self.blit_text(name, rect.x + 110, rect.y + 31, self.speaker_font, IVORY)
            self.blit_text(specialty, rect.x + 110, rect.y + 67, self.small, GOLD)
            label = "ADVISER SELECTED" if selected else "CLICK OR TAB TO SELECT"
            self.blit_text(label, rect.x + 110, rect.y + 101, self.small, MUTED)

        self.blit_text("CURRENT ORDERS · ONE UNIT ORDER PER SENTENCE; ORDERS STAY ACTIVE THROUGH BATTLE",
                       124, 322, self.small, GOLD)
        self.draw_wrapped(self.strategy_summary(), pygame.Rect(124, 343, 835, 53), self.font, IVORY, 2)
        dialogue_rect = pygame.Rect(110, 402, 880, 142)
        self.panel(dialogue_rect, (7, 10, 14, 245), (104, 104, 95))
        visible_dialogue = self.dialogue[-2:]
        for index, message in enumerate(visible_dialogue):
            y = dialogue_rect.y + 5 + index * 68
            speaker = str(message.get("speaker", "")).upper()
            portrait = pygame.Rect(dialogue_rect.x + 12, y + 1, 46, 46)
            self.draw_dialogue_portrait(speaker, portrait)
            source = " · AI ADVISER" if message.get("source") == "codex" else " · SCRIPTED FALLBACK" if message.get("source") == "fallback" else ""
            self.blit_text(speaker + source, dialogue_rect.x + 72, y, self.small, GOLD)
            self.draw_dialogue_text(str(message.get("text", "")), dialogue_rect.x + 72,
                                    y + 20, dialogue_rect.width - 95)
        if not visible_dialogue:
            self.blit_text("Tell your advisers what you want to achieve.", 190, 452, self.font, MUTED)

        if self.planning_suggestion:
            proposal = "AI PROPOSES: " + " · ".join(
                f"{order['target'].upper()}: {order['action'].replace('_', ' ')}" for order in self.planning_suggestion)
            self.draw_wrapped(proposal, pygame.Rect(124, 550, 855, 22), self.small, (170, 217, 187), 1)
        speech_state = self.ai.speech_state
        pending = next((entry for entry in reversed(self.dialogue) if entry.get("provisional")), None)
        if self.voice_warming():
            status = "WARMING VOICE MODELS · COUNCIL CLOCK PAUSED"
        elif speech_state == "starting":
            status = "OPENING MICROPHONE…"
        elif speech_state == "listening":
            status = f"LISTENING TO {self.ai.character_name.upper()} · PAUSE WHEN FINISHED"
        elif speech_state == "transcribing":
            status = "TRANSCRIBING YOUR PLAN…"
        elif pending:
            status = f"ADVISER CONSIDERING YOUR PLAN · {time.monotonic() - pending['created_at']:.0f}s · CLOCK PAUSED"
        elif self.ai.tts_worker_active:
            status = "PREPARING ADVISER VOICE · COUNCIL CLOCK PAUSED"
        elif self.team_order_feedback and time.monotonic() < self.team_order_feedback_until:
            status = self.team_order_feedback
        else:
            status = "B / T SPEAK · TAB SWITCH ADVISER · SAY ‘I'M DONE’ TO FIGHT"
        self.draw_wrapped(status, pygame.Rect(124, 576, 855, 22), self.small, GOLD, 1)
        pygame.draw.rect(self.canvas, (61, 86, 72) if self.planning_suggestion else (40, 44, 48), PLANNING_APPLY_RECT, border_radius=6)
        apply_label = self.speaker_font.render("APPLY AI PLAN" if self.planning_suggestion else "AWAITING AI PLAN", True, IVORY if self.planning_suggestion else MUTED)
        self.canvas.blit(apply_label, apply_label.get_rect(center=PLANNING_APPLY_RECT.center))
        pygame.draw.rect(self.canvas, (47, 52, 58), PLANNING_RESET_RECT, border_radius=6)
        reset_label = self.speaker_font.render("RESET ORDERS", True, IVORY)
        self.canvas.blit(reset_label, reset_label.get_rect(center=PLANNING_RESET_RECT.center))
        pygame.draw.rect(self.canvas, GOLD, PLANNING_START_RECT, border_radius=6)
        pygame.draw.rect(self.canvas, (235, 218, 176), PLANNING_START_RECT, 2, border_radius=6)
        button_label = self.speaker_font.render("START BATTLE", True, INK)
        self.canvas.blit(button_label, button_label.get_rect(center=PLANNING_START_RECT.center))

    def draw_dialogue_portrait(self, speaker, rect):
        portraits = {
            "JON SNOW": self.hero_sprite,
            "YOU · TEAM": self.hero_sprite,
            "YOU · BOLTON": self.hero_sprite,
            "RAMSAY BOLTON": self.bolton_sprite,
            "SANSA": self.sansa_sprite,
            "SANSA STARK": self.sansa_sprite,
            "TORMUND": self.tormund_sprite,
            "TORMUND GIANTSBANE": self.tormund_sprite,
            "WUN WUN": self.wunwun_sprite,
        }
        sprite = portraits.get(str(speaker).upper())
        pygame.draw.rect(self.canvas, (31, 37, 43), rect, border_radius=5)
        if sprite and sprite.frames.get("idle"):
            head = sprite.portrait_source
            ratio = max(rect.width / head.get_width(), rect.height / head.get_height())
            portrait = pygame.transform.smoothscale(head, (max(rect.width, round(head.get_width() * ratio)), max(rect.height, round(head.get_height() * ratio))))
            crop = portrait.get_rect(center=(portrait.get_width() // 2, portrait.get_height() // 2))
            crop.size = rect.size
            crop.center = portrait.get_rect().center
            portrait = portrait.subsurface(crop)
            self.canvas.blit(portrait, rect)
        else:
            label = str(speaker)[:1].upper() or "?"
            glyph = self.speaker_font.render(label, True, GOLD)
            self.canvas.blit(glyph, glyph.get_rect(center=rect.center))
        pygame.draw.rect(self.canvas, (132, 113, 81), rect, 1, border_radius=5)

    def draw_hud(self):
        if self.conversation.active:
            self.blit_text("BATTLE PAUSED · " + self.conversation.label, 310, 104, self.small, GOLD)
        elif self.battle_time_scale < .85:
            self.blit_text("CONVERSATION TIME · BATTLE SLOWED", 355, 104, self.small, GOLD)
        self.panel(pygame.Rect(18, 16, 320, 72), (12, 15, 20, 225), (112, 121, 126))
        self.blit_text(f"JON SNOW  ·  ALLIES {len(self.allies):02d}", 32, 23, self.small, IVORY)
        pygame.draw.rect(self.canvas, (49, 51, 52), (32, 50, 270, 8), border_radius=4)
        pygame.draw.rect(self.canvas, (125, 174, 132), (32, 50, int(270 * self.player.health / 100), 8), border_radius=4)
        pygame.draw.rect(self.canvas, (48, 53, 60), (32, 65, 270, 6), border_radius=3)
        pygame.draw.rect(self.canvas, (115, 176, 201), (32, 65, round(270 * self.player.stamina / 100), 6), border_radius=3)
        self.blit_text(f"STAMINA {self.player.stamina:.0f} · POSTURE {self.player.posture:.0f}", 32, 74, self.small, MUTED)
        self.panel(pygame.Rect(800, 15, 282, 54), (12, 15, 20, 225), (112, 121, 126))
        chapter_label = ["THE BATTLEFIELD", "THE SHIELD WALL", "WINTERFELL COURTYARD"][self.chapter - 1]
        wave_label = f"WAVE {self.chapter_wave}/{self.chapter_wave_count}"
        if self.wave_pending:
            seconds = max(1, math.ceil(self.wave_spawn_at - self.combat_time))
            wave_label = f"RESERVES IN {seconds}s"
        self.blit_text(f"{chapter_label}  ·  {wave_label}", 815, 23, self.small, GOLD)
        self.blit_text(f"FOES {len(self.enemies):02d}  ·  ARROWS {self.arrow_ammo:02d}  ·  HELP {self.help_calls_remaining}", 815, 46, self.small, IVORY)
        voice_parts = [f"VOICE: {self.ai.tts_status}"]
        if self.ai.last_stt_latency is not None:
            voice_parts.append(f"STT {self.ai.last_stt_latency:.2f}s")
        if self.ai.last_latency is not None:
            voice_parts.append(f"AI {self.ai.last_latency:.2f}s")
        if self.ai.last_tts_latency is not None:
            voice_parts.append(f"TTS {self.ai.last_tts_latency:.2f}s")
        self.blit_text("  ·  ".join(voice_parts), 355, 48, self.small, GOLD)
        plan_label = f"TEAM PLAN: {self.strategy_summary()}"
        if self.small.size(plan_label)[0] > 435:
            plan_label = plan_label[:53].rstrip() + "…"
        self.blit_text(plan_label, 355, 68, self.small, IVORY)
        order_event = next((e for e in reversed(self.control.events) if e.get("source") == "codex" and e.get("kind") == "order"), None)
        if order_event:
            detail = order_event["detail"]
            self.draw_wrapped("CODEX ORDERS: " + detail["action"].replace("_", " ").upper() + " · " + detail.get("reason", ""),
                              pygame.Rect(355, 80, 720, 22), self.small, GOLD, 1)
        dialogue_panel = pygame.Rect(18, HEIGHT - 158, WIDTH - 36, 146)
        self.panel(dialogue_panel, (7, 10, 14, 246), (125, 111, 87))
        visible_dialogue = self.dialogue[-2:]
        row_height = 68
        for i, msg in enumerate(visible_dialogue):
            y = dialogue_panel.y + 4 + i * row_height
            speaker = str(msg.get("speaker", "BATTLEFIELD")).upper()
            portrait_rect = pygame.Rect(31, y + 3, 52, 52)
            right_side = speaker == "RAMSAY BOLTON"
            if right_side:
                portrait_rect.right = dialogue_panel.right - 13
            self.draw_dialogue_portrait(speaker, portrait_rect)
            source = " · AI" if msg.get("source") == "codex" else " · SCRIPTED" if msg.get("source") == "fallback" else ""
            name = self.speaker_font.render(speaker + source, True, GOLD if right_side else (192, 204, 207))
            text = str(msg.get("text", ""))
            text_x = 96
            max_width = WIDTH - 139
            if right_side:
                name_rect = name.get_rect(right=portrait_rect.left - 12, top=y + 1)
                text_x = 28
                max_width = name_rect.right - text_x
                self.canvas.blit(name, name_rect)
                self.draw_dialogue_text(text, text_x, y + 29, max_width, right_aligned=True)
            else:
                self.canvas.blit(name, (text_x, y + 1))
                self.draw_dialogue_text(text, text_x, y + 29, max_width)
        speech_state = self.ai.speech_state
        target_name = "TEAM" if self.voice_capture_mode == "team" else "BOLTON"
        if speech_state == "starting":
            status = f"{target_name} MICROPHONE STARTING"
        elif speech_state == "listening":
            status = ("TEAM ORDER · SAY: COVER ME / ATTACK ARCHERS / FLANK LEFT · PAUSE TO SEND"
                      if target_name == "TEAM" else "TALK TO BOLTON · SPEAK NOW · PAUSE TO SEND")
        elif speech_state == "transcribing":
            status = f"{target_name} · RECOGNIZING YOUR WORDS…"
        elif self.team_order_feedback and time.monotonic() < self.team_order_feedback_until:
            status = self.team_order_feedback
        else:
            status = ""
        voice_active = speech_state in {"starting", "listening", "transcribing"}
        if status:
            status_img = self.small.render(status, True, (255, 212, 120) if voice_active else GOLD)
            self.canvas.blit(status_img, status_img.get_rect(center=(WIDTH // 2, 88)))
        error_status = self.ai.last_stt_error or self.ai.last_tts_error
        if error_status:
            self.blit_text(error_status[:54], 360, 30, self.small, (255, 166, 139))
        director_status = self.director.status["enemies"]
        command_label = "PLANNING" if self.director.busy["enemies"] else "UNAVAILABLE" if "unavailable" in director_status.lower() else "CONNECTED" if order_event else "AWAITING ORDERS"
        self.blit_text("BOLTON COMMANDER: " + command_label, 355, 28, self.small, (245, 187, 123))

    def draw_wrapped(self, text, rect, font, color, max_lines=2):
        words = str(text).split()
        lines = []
        line = ""
        for word in words:
            candidate = (line + " " + word).strip()
            if line and font.size(candidate)[0] > rect.width:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        visible = lines[:max_lines]
        if len(lines) > max_lines:
            last = visible[-1]
            while last and font.size(last + "…")[0] > rect.width:
                last = last[:-1]
            visible[-1] = last.rstrip() + "…"
        previous_clip = self.canvas.get_clip()
        self.canvas.set_clip(previous_clip.clip(rect))
        for index, row in enumerate(visible):
            self.canvas.blit(font.render(row, True, color), (rect.x, rect.y + index * font.get_linesize()))
        self.canvas.set_clip(previous_clip)

    def draw_dialogue_text(self, text, x, y, max_width, right_aligned=False):
        """Draw up to two readable subtitle lines, trimming only after wrapping."""
        words = str(text).split()
        lines, current = [], ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and self.dialogue_font.size(candidate)[0] > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        if len(lines) > 2:
            lines = lines[:2]
            while lines[-1] and self.dialogue_font.size(lines[-1] + "…")[0] > max_width:
                lines[-1] = lines[-1][:-1]
            lines[-1] = lines[-1].rstrip() + "…"
        for line_index, line in enumerate(lines):
            rendered = self.dialogue_font.render(line, True, IVORY)
            rect = rendered.get_rect(top=y + line_index * 28)
            if right_aligned:
                rect.right = x + max_width
            else:
                rect.left = x
            self.canvas.blit(rendered, rect)

    def draw_ending(self):
        self.panel(pygame.Rect(130, 180, 840, 330), (15, 18, 24, 240))
        if self.state == "defeat":
            heading = "THE NORTH IS SCATTERED"
            lines = ["You fall beneath the Bolton shields. The battle is lost, but the story isn't over.", "The remaining loyalists rally at the edge of the field. Return with allies and archers.", "R  ·  REBUILD AND TRY AGAIN        Q  ·  RETURN TO TITLE"]
        else:
            heading = "WINTERFELL IS YOURS"
            lines = ["Ramsay is defeated. The Stark banners rise above Winterfell once more.", "The North remembers those who stood in the snow.", "CLICK / ENTER  ·  RETURN TO TITLE"]
        self.blit_text(heading, 175, 218, self.title, IVORY)
        for i, line in enumerate(lines[:2]):
            self.blit_text(line, 178, 330 + i * 39, self.font, MUTED)
        if self.state == "defeat":
            pygame.draw.rect(self.canvas, GOLD, DEFEAT_RETRY_RECT, 1, border_radius=5)
            pygame.draw.rect(self.canvas, (112, 121, 126), DEFEAT_TITLE_RECT, 1, border_radius=5)
            self.blit_text("R · REBUILD AND RETRY", 190, 442, self.small, GOLD)
            self.blit_text("Q · RETURN TO TITLE", 464, 442, self.small, IVORY)
        else:
            self.blit_text("CLICK / ENTER · RETURN TO TITLE", 178, 408, self.font, GOLD)

    def blit_text(self, value, x, y, font=None, color=IVORY):
        font = font or self.font
        self.canvas.blit(font.render(value, True, color), (x, y))


def main():
    Game().run()


if __name__ == "__main__":
    main()
