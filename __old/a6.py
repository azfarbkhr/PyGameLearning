import pygame
import random

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

# FPS
clock = pygame.time.Clock()
FPS = 60

# Obstacles
obstacles = [pygame.Rect(random.randint(100, 700), random.randint(100, 500), 50, 50) for _ in range(5)]

# Player class
class Player(pygame.sprite.Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.image = pygame.Surface((50, 50))  # Representing player as a box
        self.image.fill(BLUE)
        self.rect = self.image.get_rect()
        self.rect.topleft = (x, y)
        self.health = 100
        self.attack_power = 10
        self.speed = 5

    def update(self, keys):
        # Save current position to check for collisions
        old_x, old_y = self.rect.x, self.rect.y

        # Movement
        if keys[pygame.K_w]:  # Move up
            self.rect.y -= self.speed
        if keys[pygame.K_s]:  # Move down
            self.rect.y += self.speed
        if keys[pygame.K_a]:  # Move left
            self.rect.x -= self.speed
        if keys[pygame.K_d]:  # Move right
            self.rect.x += self.speed

        # Collision with obstacles
        for obstacle in obstacles:
            if self.rect.colliderect(obstacle):
                self.rect.x, self.rect.y = old_x, old_y  # Revert to old position on collision

    def attack(self, enemies):
        for enemy in enemies:
            if self.rect.colliderect(enemy.rect):
                enemy.health -= self.attack_power
                print("Attacked enemy! Enemy health:", enemy.health)

# Enemy class
class Enemy(pygame.sprite.Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.image = pygame.Surface((40, 40))  # Representing enemy as a box
        self.image.fill(RED)
        self.rect = self.image.get_rect()
        self.rect.topleft = (x, y)
        self.health = 50
        self.speed = 1  # Reduced speed of enemy

    def update(self, player):
        if player.rect.x > self.rect.x:  # Move toward player
            self.rect.x += self.speed
        elif player.rect.x < self.rect.x:
            self.rect.x -= self.speed

        if player.rect.y > self.rect.y:
            self.rect.y += self.speed
        elif player.rect.y < self.rect.y:
            self.rect.y -= self.speed

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
    running = True

    # Create player and groups
    player = Player(100, 300)
    enemies = pygame.sprite.Group([Enemy(random.randint(300, 700), random.randint(100, 500)) for _ in range(3)])
    castle = Castle(700, 250)

    while running:
        screen.fill(BLACK)
        keys = pygame.key.get_pressed()

        # Event handling
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        # Update player
        player.update(keys)

        # Update enemies
        for enemy in enemies:
            enemy.update(player)
            if enemy.health <= 0:
                enemies.remove(enemy)

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

        # Draw everything
        screen.blit(player.image, player.rect)
        for enemy in enemies:
            screen.blit(enemy.image, enemy.rect)
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