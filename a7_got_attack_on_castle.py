import pygame
import random
import sys 

# Initialize Pygame
pygame.init()

# Initialize the mixer
pygame.mixer.init()

# Load the music file
pygame.mixer.music.load("assets/music/time_for_adventure.mp3")

# Load the attack sound
attack_sound = pygame.mixer.Sound("assets/sound/attack.wav")
# pygame.mixer.Sound.set_volume(attack_sound, 0.1)

# Play the music
pygame.mixer.music.play(-1)  # -1 means the music will loop indefinitely
pygame.mixer.music.set_volume(0.5)

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
ATTACK_SPRITE_HEIGHT = 42


SLIME_SPRITE_SHEET_PATH = "assets/slime/slime_purple.png"
SLIME_SPRITE_COLUMNS = 4 
SLIME_SPRITE_ROWS = 3
SLIME_SPRITE_WIDTH = 24
SLIME_SPRITE_HEIGHT = 24 


# Load background image
BACKGROUNG_IMAGE_PATH = "assets/background/TX_Tileset_Grass.png"
background_image = pygame.image.load(BACKGROUNG_IMAGE_PATH).convert() 
background_image = pygame.transform.scale(background_image, (SCREEN_WIDTH, SCREEN_HEIGHT))


# Load sprite sheets
walking_sprite_sheet = pygame.image.load(WALKING_SPRITE_SHEET_PATH).convert_alpha()
idle_sprite_sheet = pygame.image.load(IDLE_SPRITE_SHEET_PATH).convert_alpha()
attack_sprite_sheet = pygame.image.load(ATTACK_SPRITE_SHEET_PATH).convert_alpha()
slime_sprite_sheet = pygame.image.load(SLIME_SPRITE_SHEET_PATH).convert_alpha()

# Function to extract frames from the sprite sheet
def load_frames(sprite_sheet, columns, width, height, scale_factor=2, rows=1):
    frames = []
    for row in range(rows):
        for col in range(columns):
            x = col * width
            y = row * height
            frame = sprite_sheet.subsurface((x, y, width, height))
            scaled_frame = pygame.transform.scale(frame, (width * scale_factor, height * scale_factor))
            frames.append(scaled_frame)
    return frames

# Extract frames for different actions
walking_frames = load_frames(walking_sprite_sheet, WALKING_SPRITE_COLUMNS, WALKING_SPRITE_WIDTH, WALKING_SPRITE_HEIGHT)
idle_frames = load_frames(idle_sprite_sheet, IDLE_SPRITE_COLUMNS, IDLE_SPRITE_WIDTH, IDLE_SPRITE_HEIGHT)
attack_frames = load_frames(attack_sprite_sheet, ATTACK_SPRITE_COLUMNS, ATTACK_SPRITE_WIDTH, ATTACK_SPRITE_HEIGHT)
slime_frames = load_frames(slime_sprite_sheet, SLIME_SPRITE_COLUMNS, SLIME_SPRITE_WIDTH, SLIME_SPRITE_HEIGHT, 3, SLIME_SPRITE_ROWS)

# Obstacles
def generate_obstacles():
    obstacles = []
    obstacle_image = pygame.image.load("assets/obstacle/tree_one.png").convert_alpha()
    obstacle_image = pygame.transform.scale(obstacle_image, (114, 141))
    for _ in range(2):
        while True:
            obstacle_rect = obstacle_image.get_rect(topleft=(random.randint(100, 700), random.randint(100, 500)))
            if not obstacle_rect.colliderect(player.rect):
                obstacles.append((obstacle_image, obstacle_rect))
                break
    return obstacles

# Player class
class Player(pygame.sprite.Sprite):
    def __init__(self, x, y, walking_frames, idle_frames, attack_frames, health=200, attack_power=20, attack_range=100, speed=2, score=0):
        super().__init__()
        self.walking_frames = walking_frames
        self.idle_frames = idle_frames
        self.attack_frames = attack_frames
        self.current_frames = self.idle_frames
        self.current_frame = 0
        self.image = self.current_frames[self.current_frame]
        self.rect = self.image.get_rect()
        self.rect.topleft = (x, y)

        self.health = health
        self.attack_power = attack_power
        self.attack_range = attack_range
        self.speed = speed
        self.score = score
        
        self.player_direction = 'right'
        self.action_state = 'idle'  # 'idle', 'walking', 'attacking'
        self.frame_rate = 10
        self.animation_timer = 0
        self.attacking = False
        self.attack_animation_timer = 0
        self.attack_frame_rate = 15

    def update_animation(self):
        self.animation_timer += 1
        if self.animation_timer >= self.frame_rate:
            self.animation_timer = 0
            self.current_frame = (self.current_frame + 1) % len(self.current_frames)
            self.image = self.current_frames[self.current_frame]
            if self.player_direction == 'left':
                self.image = pygame.transform.flip(self.image, True, False)

    def update(self, keys):
        old_x, old_y = self.rect.x, self.rect.y
        moved = False

        if self.attacking:
            self.current_frames = self.attack_frames
            self.current_frame += 1

            if self.current_frame >= len(self.current_frames):
                self.attacking = False
                self.current_frames = self.idle_frames
                self.current_frame = 0
            else:
                self.image = self.current_frames[self.current_frame]
                # if self.player_direction == 'left':
                #     self.image = pygame.transform.flip(self.image, True, False)
                
        # return  # Skip movement if attacking

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
            if self.rect.colliderect(obstacle[1]):
                self.rect.x, self.rect.y = old_x, old_y

        if self.attacking:
            return
        
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
        pygame.mixer.Sound.play(attack_sound)
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
                    self.score += 1
                    print(f"Enemy {idx} attacked. Remaining Health: {enemy.health}")

# Enemy class
class Enemy(pygame.sprite.Sprite):
    def __init__(self, x, y, slime_frames):
        super().__init__()
        self.slime_frames = slime_frames
        self.current_frames = self.slime_frames
        self.current_frame = 0
        self.image = self.current_frames[self.current_frame]
        self.rect = self.image.get_rect()
        self.rect.topleft = (x, y)
        
        self.player_direction = 'right'
        self.action_state = 'walking'  # 'idle', 'walking', 'attacking'
        self.frame_rate = 10
        self.animation_timer = 0

        self.health = 50
        self.speed = random.randint(1, 3)
        
        self.initial_position = (x, y)
        self.max_radius = random.randint(600, 1000)

    def update_animation(self):
        self.animation_timer += 1
        if self.animation_timer >= self.frame_rate:
            self.animation_timer = 0
            self.current_frame = (self.current_frame + 1) % len(self.current_frames)
            self.image = self.current_frames[self.current_frame]
            if self.player_direction == 'left':
                self.image = pygame.transform.flip(self.image, True, False)        

    def update(self, player):
        # Save current position to check for collisions
        old_x, old_y = self.rect.x, self.rect.y

        # Chase player if within radius
        distance_to_player = ((player.rect.x - self.rect.x) ** 2 + (player.rect.y - self.rect.y) ** 2) ** 0.5
        if distance_to_player < self.max_radius:
            if player.rect.x > self.rect.x:
                self.rect.x += self.speed
            elif player.rect.x < self.rect.x:
                self.rect.x -= self.speed

            if player.rect.y > self.rect.y:
                self.rect.y += self.speed
            elif player.rect.y < self.rect.y:
                self.rect.y -= self.speed

        # If stuck on an obstacle, move away
        for obstacle in obstacles:
            if self.rect.colliderect(obstacle[1]):
                if self.rect.x < obstacle[1].x:
                    self.rect.x -= self.speed
                elif self.rect.x > obstacle[1].x:
                    self.rect.x += self.speed
            
                if self.rect.y < obstacle[1].y:
                    self.rect.y -= self.speed
                elif self.rect.y > obstacle[1].y:
                    self.rect.y += self.speed

        # Avoid overlapping with other enemies
        for other in enemies:
            if other != self and self.rect.colliderect(other.rect):
                if self.rect.x < other.rect.x:
                    self.rect.x -= self.speed
                else:
                    self.rect.x += self.speed

                if self.rect.y < other.rect.y:
                    self.rect.y -= self.speed
                else:
                    self.rect.y += self.speed
        
        self.update_animation()

# Castle class
class Castle(pygame.sprite.Sprite):
    def __init__(self, x, y):
        super().__init__()
        castle_image = pygame.image.load("assets/castle/door.png").convert_alpha()
        width, height = castle_image.get_width(), castle_image.get_height()
        castle_image = pygame.transform.scale(castle_image, (width*2, height*2))
        self.image = castle_image
        # self.image.fill(WHITE)
        self.rect = self.image.get_rect()
        self.rect.topleft = (x, y)

# Game loop
def main():
    global enemies, obstacles, player
    running = True
    game_start = True
    game_over = False
    level_up = False

    while running:
        if game_start:
            player = Player(100, 100, walking_frames, idle_frames, attack_frames)
            enemies = pygame.sprite.Group([Enemy(random.randint(300, 700), random.randint(100, 500), slime_frames) for _ in range(random.randint(3, 20))])
            obstacles = generate_obstacles()
            castle = Castle(-15, 0)
            all_sprites = pygame.sprite.Group()
            all_sprites.add(player)
            all_sprites.add(enemies)
            game_start = False

        elif level_up:
            player = Player(100, 100, walking_frames, idle_frames, attack_frames, player.health * 1.20, player.attack_power * 1.10, player.attack_range * 1.20, player.speed * 1.1, player.score + 50)
            enemies = pygame.sprite.Group([Enemy(random.randint(300, 700), random.randint(100, 500), slime_frames) for _ in range(random.randint(3, 20))])
            obstacles = generate_obstacles()
            castle = Castle(700, 250)
            all_sprites = pygame.sprite.Group()
            all_sprites.add(player)
            all_sprites.add(enemies)
            level_up = False

        # screen.fill(BLACK)
        screen.blit(background_image, (0, 0)) 
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
            print("Victory! You captured the castle.")
            victory = True
            while victory:
                screen.fill(WHITE)
                victory_text = font.render("You captured the castle! Victory!", True, BLACK)
                screen.blit(victory_text, (SCREEN_WIDTH // 2 - victory_text.get_width() // 2, SCREEN_HEIGHT // 2 - victory_text.get_height() // 2))
                score_text = font.render(f"Your Score: {player.score}", True, BLACK)
                screen.blit(score_text, (SCREEN_WIDTH // 2 - score_text.get_width() // 2, SCREEN_HEIGHT // 2 - score_text.get_height() // 2 + 50))
                restart_text = font.render("Press C to Continue or Q to Quit", True, BLACK)
                screen.blit(restart_text, (SCREEN_WIDTH // 2 - restart_text.get_width() // 2, SCREEN_HEIGHT // 2 - restart_text.get_height() // 2 + 100))
                pygame.display.flip()
                clock.tick(FPS)

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        victory = False
                        running = False

                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_c:
                            level_up = True
                            victory = False
                        elif event.key == pygame.K_q:
                            victory = False
                            running = False

        # Draw obstacles
        for obstacle in obstacles:
            screen.blit(obstacle[0], obstacle[1])

        all_sprites.draw(screen)
        screen.blit(castle.image, castle.rect)

        # Display health
        font = pygame.font.SysFont(None, 30)
        health_text = font.render(f"Health: {player.health}", True, WHITE)
        screen.blit(health_text, (10, 10))

        # Display score
        score_text = font.render(f"Your Score: {player.score}", True, WHITE)
        screen.blit(score_text, (10, 40))

        # Check game over condition
        for enemy in enemies:
            if enemy.rect.colliderect(player.rect):
                player.health -= 1
                if player.health <= 0:
                    print("Defeat! Jon Snow has fallen.")
                    game_over = True
                    while game_over:
                        screen.fill(BLACK)
                        score_text = font.render(f"Your Score: {player.score}", True, WHITE)
                        screen.blit(score_text, (SCREEN_WIDTH // 2 - score_text.get_width() // 2, SCREEN_HEIGHT // 2 - score_text.get_height() // 2))
                        game_over_text = font.render("Game Over! Press R to Restart or Q to Quit", True, WHITE)
                        screen.blit(game_over_text, (SCREEN_WIDTH // 2 - game_over_text.get_width() // 2, SCREEN_HEIGHT // 2 - game_over_text.get_height() // 2 + 50))
                        pygame.display.flip()
                        clock.tick(FPS)

                        for event in pygame.event.get():
                            if event.type == pygame.QUIT:
                                game_over = False
                                running = False

                            if event.type == pygame.KEYDOWN:
                                if event.key == pygame.K_r:
                                    game_start = True
                                    game_over = False

                                elif event.key == pygame.K_q:
                                    game_over = False
                                    running = False
                        
                        

        # Update screen
        pygame.display.flip()
        clock.tick(FPS)


if __name__ == "__main__":
    main()
