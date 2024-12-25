import pygame
import sys

# Initialize Pygame
pygame.init()

# Screen dimensions
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600

# Colors
WHITE = (255, 255, 255)

# Frame rate
FPS = 5

# Load the sprite sheet
SPRITE_SHEET_PATH = "assets/knight/attack.png"  # Replace with your sprite sheet path

# Sprite details
SPRITE_COLUMNS = 10
SPRITE_ROWS = 1
SPRITE_WIDTH = 80  # Replace with the width of a single sprite
SPRITE_HEIGHT = 80  # Replace with the height of a single sprite

# Initialize the screen
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Sprite Animation")

# Load the sprite sheet
sprite_sheet = pygame.image.load(SPRITE_SHEET_PATH).convert_alpha()

# Function to extract frames from the sprite sheet
def load_frames(sprite_sheet, columns, rows, width, height):
    frames = []
    for col in range(columns):
        x = col * width
        y = 0  
        frame = sprite_sheet.subsurface((x, y, width, height))
        frames.append(frame)
    return frames

# Extract frames
frames = load_frames(sprite_sheet, SPRITE_COLUMNS, SPRITE_ROWS, SPRITE_WIDTH, SPRITE_HEIGHT)

# Game loop variables
clock = pygame.time.Clock()
current_frame = 0
running = True

while running:
    # Handle events
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Update frame index
    current_frame = (current_frame + 1) % len(frames)

    # Clear the screen
    screen.fill(WHITE)

    # Draw the current frame
    screen.blit(frames[current_frame], (SCREEN_WIDTH // 2 - SPRITE_WIDTH // 2, SCREEN_HEIGHT // 2 - SPRITE_HEIGHT // 2))

    # Update the display
    pygame.display.flip()

    # Control the frame rate
    clock.tick(FPS)

# Quit Pygame
pygame.quit()
sys.exit()
