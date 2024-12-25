import pygame

# Initialize Pygame
pygame.init()

# Screen setup
screen_width, screen_height = 800, 600
screen = pygame.display.set_mode((screen_width, screen_height))
pygame.display.set_caption("Enhanced Player Movement and Collision")

# Colors
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)

# Create a Player sprite with animation
class Player(pygame.sprite.Sprite):
    def __init__(self, x, y, color, controls):
        super().__init__()
        self.frames = [
            pygame.Surface((50, 50)),
            pygame.Surface((50, 50))
        ]
        self.frames[0].fill(color)
        self.frames[1].fill((color[0] // 2, color[1] // 2, color[2] // 2))  # Dimmer version for animation
        self.current_frame = 0
        self.image = self.frames[self.current_frame]
        self.rect = self.image.get_rect()
        self.rect.topleft = (x, y)
        self.speed = 5
        self.max_speed = 10
        self.boosted = False
        self.controls = controls  # Controls dictionary for movement keys
        self.time_since_last_frame = 0
        self.direction = None

    def update(self, keys, dt):
        # Reset boosted status each frame
        self.boosted = False

        # Animate by toggling frames
        self.time_since_last_frame += dt
        if self.time_since_last_frame > 200:  # Switch frames every 200ms
            self.current_frame = (self.current_frame + 1) % len(self.frames)
            self.image = self.frames[self.current_frame]
            self.time_since_last_frame = 0

        # Movement and boundary checks
        self.direction = None
        if keys[self.controls["up"]] and self.rect.top > 0:
            self.rect.y -= self.speed
            self.direction = "up"
        if keys[self.controls["down"]] and self.rect.bottom < screen_height:
            self.rect.y += self.speed
            self.direction = "down"
        if keys[self.controls["left"]] and self.rect.left > 0:
            self.rect.x -= self.speed
            self.direction = "left"
        if keys[self.controls["right"]] and self.rect.right < screen_width:
            self.rect.x += self.speed
            self.direction = "right"

# Create sprite groups
player1 = Player(200, 275, GREEN, {
    "up": pygame.K_w,
    "down": pygame.K_s,
    "left": pygame.K_a,
    "right": pygame.K_d
})

player2 = Player(600, 275, BLUE, {
    "up": pygame.K_UP,
    "down": pygame.K_DOWN,
    "left": pygame.K_LEFT,
    "right": pygame.K_RIGHT
})

all_sprites = pygame.sprite.Group()
all_sprites.add(player1, player2)

# Game loop
clock = pygame.time.Clock()
running = True

while running:
    dt = clock.tick(60)  # Delta time in milliseconds (60 FPS)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Update all sprites
    keys = pygame.key.get_pressed()

    # Check for same direction movement
    if player1.direction and player1.direction == player2.direction:
        player1.speed = min(player1.max_speed, player1.speed + 1)
        player2.speed = min(player2.max_speed, player2.speed + 1)
        player1.boosted = True
        player2.boosted = True
    else:
        player1.speed = 5
        player2.speed = 5

    all_sprites.update(keys, dt)

    # Collision detection
    if pygame.sprite.collide_rect(player1, player2):
        if player1.boosted or player2.boosted:  # High-speed collision
            # Push them apart
            if player1.rect.centerx < player2.rect.centerx:
                player1.rect.x -= 50
                player2.rect.x += 50
            else:
                player1.rect.x += 50
                player2.rect.x -= 50

            if player1.rect.centery < player2.rect.centery:
                player1.rect.y -= 50
                player2.rect.y += 50
            else:
                player1.rect.y += 50
                player2.rect.y -= 50
        else:
            # Standard collision bounce
            if player1.rect.colliderect(player2.rect):
                player1.rect.x -= player1.speed
                player2.rect.x += player2.speed

    # Draw everything
    screen.fill(WHITE)
    all_sprites.draw(screen)
    pygame.display.flip()

pygame.quit()
    