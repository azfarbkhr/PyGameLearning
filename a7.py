import pygame
import random
import sys 

# Initialize Pygame
pygame.init()

# Screen dimensions
SCREEN_WIDTH, SCREEN_HEIGHT = 800, 600
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Battle of Bastards")

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)
BLUE = (0, 0, 255)
GREEN = (0, 255, 0)
YELLOW = (255, 255, 0)

# FPS
clock = pygame.time.Clock()
FPS = 60
# Sprite sheet paths and details
WALKING_SPRITE_SHEET_PATH = "assets/knight/walking.png"
WALKING_SPRITE_COLUMNS = 8
WALKING_SPRITE_WIDTH = 42
WALKING_SPRITE_HEIGHT = 42

IDLE_SPRITE_SHEET_PATH = "assets/knight/idle.png"
IDLE_SPRITE_COLUMNS = 4
IDLE_SPRITE_WIDTH = 42
IDLE_SPRITE_HEIGHT = 42

ATTACK_SPRITE_SHEET_PATH = "assets/knight/attack.png"
ATTACK_SPRITE_COLUMNS = 10
ATTACK_SPRITE_WIDTH = 80
ATTACK_SPRITE_HEIGHT = 80

# Load sprite sheets
walking_sprite_sheet = pygame.image.load(WALKING_SPRITE_SHEET_PATH).convert_alpha()
idle_sprite_sheet = pygame.image.load(IDLE_SPRITE_SHEET_PATH).convert_alpha()
attack_sprite_sheet = pygame.image.load(ATTACK_SPRITE_SHEET_PATH).convert_alpha()

# Function to extract frames from the sprite sheet
def load_frames(sprite_sheet, columns, width, height):
    frames = []
    for col in range(columns):
        x = col * width
        y = sprite_sheet.get_height() - height 
        frame = sprite_sheet.subsurface((x, y, width, height))
        frames.append(frame)
    return frames

# Extract frames for different actions
walking_frames = load_frames(walking_sprite_sheet, WALKING_SPRITE_COLUMNS, WALKING_SPRITE_WIDTH, WALKING_SPRITE_HEIGHT)
idle_frames = load_frames(idle_sprite_sheet, IDLE_SPRITE_COLUMNS, IDLE_SPRITE_WIDTH, IDLE_SPRITE_HEIGHT)
attack_frames = load_frames(attack_sprite_sheet, ATTACK_SPRITE_COLUMNS, ATTACK_SPRITE_WIDTH, ATTACK_SPRITE_HEIGHT)

# Obstacles
def generate_obstacles():
    obstacles = []
    for _ in range(5):
        while True:
            obstacle = pygame.Rect(random.randint(100, 700), random.randint(100, 500), 50, 50)
            if not obstacle.colliderect(player.rect):
                obstacles.append(obstacle)
                break
    return obstacles

# Player class
class Player(pygame.sprite.Sprite):
    def __init__(self, x, y, walking_frames, idle_frames, attack_frames):
        super().__init__()
        self.walking_frames = walking_frames
        self.idle_frames = idle_frames
        self.attack_frames = attack_frames
        self.current_frames = self.idle_frames
        self.current_frame = 0
        self.image = self.current_frames[self.current_frame]
        self.rect = self.image.get_rect()
        self.rect.topleft = (x, y)

        self.base_width = 42  # Keep track of the base width
        self.base_height = 42 # Keep track of the base height

        self.health = 2000
        self.attack_power = 50
        self.attack_range = 200
        self.speed = 20
        
        self.player_direction = 'right'
        self.action_state = 'idle'  # 'idle', 'walking', 'attacking'
        self.frame_rate = 5
        self.animation_timer = 0
        self.attacking = False
        self.attack_animation_timer = 10
        self.attack_frame_rate = 3

    def update_animation(self):
        self.animation_timer += 1
        if self.animation_timer >= self.frame_rate:
            self.animation_timer = 0
            self.current_frame = (self.current_frame + 1) % len(self.current_frames)
            self.image = self.current_frames[self.current_frame]

    def update(self, keys):
        old_x, old_y = self.rect.x, self.rect.y
        moved = False

        if self.attacking:
            self.current_frames = self.attack_frames
            if not self.attack_animation_timer:
                self.current_frame = 0  # Reset attack animation
            self.attack_animation_timer += 1
            if self.attack_animation_timer >= self.attack_frame_rate:
                self.attack_animation_timer = 0
                self.current_frame += 1
                if self.current_frame >= len(self.current_frames):
                    self.attacking = False
                    self.current_frames = self.idle_frames
                    self.current_frame = 0
                else:
                    self.image = self.current_frames[self.current_frame]
            return  # Skip movement if attacking

        if keys[pygame.K_UP]:
            self.rect.y -= self.speed
            self.player_direction = 'up'
            moved = True
        if keys[pygame.K_DOWN]:
            self.rect.y += self.speed
            self.player_direction = 'down'
            moved = True
        if keys[pygame.K_LEFT]:
            self.rect.x -= self.speed
            self.player_direction = 'left'
            moved = True
        if keys[pygame.K_RIGHT]:
            self.rect.x += self.speed
            self.player_direction = 'right'
            moved = True

        for obstacle in obstacles:
            if self.rect.colliderect(obstacle):
                self.rect.x, self.rect.y = old_x, old_y

        if moved:
            if self.current_frames != self.walking_frames:
                self.current_frames = self.walking_frames
                self.current_frame = 0
            self.update_animation()
        else:
            if self.current_frames != self.idle_frames:
                self.current_frames = self.idle_frames
                self.current_frame = 0
            self.update_animation()
     
    def attack(self, enemies):
        if not self.attacking:
            self.attacking = True
            self.action_state = 'attacking'
            self.attack_animation_timer = 0

            attack_rect = self.rect.copy()
            if self.player_direction == 'right':
                attack_rect.width = self.attack_range
            elif self.player_direction == 'left':
                attack_rect.x -= (self.attack_range - self.rect.width)
                attack_rect.width = self.attack_range
            elif self.player_direction == 'up':
                attack_rect.y -= (self.attack_range - self.rect.height)
                attack_rect.height = self.attack_range
            elif self.player_direction == 'down':
                attack_rect.height = self.attack_range

            pygame.draw.rect(screen, YELLOW, attack_rect, 1)
            for idx, enemy in enumerate(enemies):
                if attack_rect.colliderect(enemy.rect):
                    enemy.health -= self.attack_power
                    print(f"Enemy {idx} attacked. Remaining Health: {enemy.health}")

# Enemy class
class Enemy(pygame.sprite.Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.image = pygame.Surface((40, 40))  # Representing enemy as a box
        self.image.fill(RED)
        self.rect = self.image.get_rect()
        self.rect.topleft = (x, y)
        self.health = 50
        self.speed = 1
        self.initial_position = (x, y)
        self.max_radius = 200

    def update(self, player):
        # Save current position to check for collisions
        old_x, old_y = self.rect.x, self.rect.y

        # Chase player if within radius
        # distance_to_player = ((player.rect.x - self.initial_position[0]) ** 2 + (player.rect.y - self.initial_position[1]) ** 2) ** 0.5
        # if distance_to_player < self.max_radius:
        if 1 == 1:
            if player.rect.x > self.rect.x:
                self.rect.x += self.speed
            elif player.rect.x < self.rect.x:
                self.rect.x -= self.speed

            if player.rect.y > self.rect.y:
                self.rect.y += self.speed
            elif player.rect.y < self.rect.y:
                self.rect.y -= self.speed

        # Collision with obstacles
        for obstacle in obstacles:
            if self.rect.colliderect(obstacle):
                self.rect.x, self.rect.y = old_x, old_y  # Revert to old position on collision

        # Avoid overlapping with other enemies
        for other in enemies:
            if other != self and self.rect.colliderect(other.rect):
                self.rect.x, self.rect.y = old_x, old_y  # Revert to old position

# Castle class
class Castle(pygame.sprite.Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.image = pygame.Surface((100, 100))  # Representing castle as a box
        self.image.fill(WHITE)
        self.rect = self.image.get_rect()
        self.rect.topleft = (x, y)

# Game loop
def main():
    global enemies, obstacles, player
    running = True

    player = Player(100, 100, walking_frames, idle_frames, attack_frames)
    enemies = pygame.sprite.Group([Enemy(random.randint(300, 700), random.randint(100, 500)) for _ in range(5)])
    obstacles = generate_obstacles()
    castle = Castle(700, 250)
    all_sprites = pygame.sprite.Group()
    all_sprites.add(player)
    all_sprites.add(enemies)

    while running:
        screen.fill(BLACK)
        keys = pygame.key.get_pressed()

        # Event handling
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_a:  # Attack with 'A'
                    player.attack(enemies)

        # Update player
        player.update(keys)

        # Update enemies
        for enemy in enemies:
            enemy.update(player)

        # Remove dead enemies
        enemies = [enemy for enemy in enemies if enemy.health > 0]
        all_sprites.remove(*[enemy for enemy in all_sprites if enemy.health <= 0])

        # Check victory condition
        if player.rect.colliderect(castle.rect) and len(enemies) == 0:
            print("You captured the castle! Victory!")
            running = False

        # Check game over condition
        for enemy in enemies:
            if enemy.rect.colliderect(player.rect):
                player.health -= 1
                if player.health <= 0:
                    print("Defeat! Jon Snow has fallen.")
                    running = False

        # Draw obstacles
        for obstacle in obstacles:
            pygame.draw.ellipse(screen, GREEN, obstacle)

        all_sprites.draw(screen)
        screen.blit(castle.image, castle.rect)

        # Display health
        font = pygame.font.SysFont(None, 30)
        health_text = font.render(f"Health: {player.health}", True, WHITE)
        screen.blit(health_text, (10, 10))

        # Update screen
        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()

if __name__ == "__main__":
    main()
