import pygame
import pymunk
import pymunk.pygame_util

# Initialize Pygame
pygame.init()

# Screen setup
screen_width, screen_height = 800, 600
screen = pygame.display.set_mode((screen_width, screen_height))
pygame.display.set_caption("Physics-Based Player Movement")

# Colors
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
RED = (255, 0, 0)

# Initialize Pymunk space
space = pymunk.Space()
space.gravity = (0, 0)  # No gravity for this 2D plane

# Pymunk helper for drawing
draw_options = pymunk.pygame_util.DrawOptions(screen)

# Override the color_for_shape method
def custom_color_for_shape(shape):
    if hasattr(shape, 'color'):
        return shape.color + (255,)  # Add alpha channel
    return (200, 200, 200, 255)  # Default gray color

draw_options.color_for_shape = custom_color_for_shape

# Helper function to create a player ball
def create_ball(x, y, radius, color):
    body = pymunk.Body(1, float('inf'))  # Dynamic body
    body.position = x, y
    shape = pymunk.Circle(body, radius)
    shape.elasticity = 1.0  # Perfectly elastic collisions
    shape.friction = 0.5
    shape.color = color
    space.add(body, shape)
    return body, shape

# Helper function to create walls
def create_wall(start, end):
    body = pymunk.Body(body_type=pymunk.Body.STATIC)  # Static body
    shape = pymunk.Segment(body, start, end, 1)  # Wall with thickness 1
    shape.elasticity = 1.0  # Perfectly elastic collisions
    shape.friction = 0.5
    space.add(body, shape)

# Create walls (boundaries)
create_wall((1, 1), (1, screen_height - 1))  # Left wall
create_wall((1, screen_height - 1), (screen_width - 1, screen_height - 1))  # Bottom wall
create_wall((screen_width - 1, screen_height - 1), (screen_width - 1, 1))  # Right wall
create_wall((screen_width - 1, 1), (1, 1))  # Top wall

# Create penalty lines
def create_penalty_line(x1, y1, x2, y2):
    body = pymunk.Body(body_type=pymunk.Body.STATIC)
    shape = pymunk.Segment(body, (x1, y1), (x2, y2), 1)
    shape.elasticity = 1.0
    shape.color = RED
    shape.collision_type = 1
    space.add(body, shape)
    return shape

penalty_lines = [
    create_penalty_line(0, screen_height // 2 - 50, 0, screen_height // 2 + 50),  # Left center
    create_penalty_line(screen_width, screen_height // 2 - 50, screen_width, screen_height // 2 + 50),  # Right center
    create_penalty_line(screen_width // 2 - 50, 0, screen_width // 2 + 50, 0),  # Top center
    create_penalty_line(screen_width // 2 - 50, screen_height, screen_width // 2 + 50, screen_height)  # Bottom center
]

# Create players as balls
player1_body, player1_shape = create_ball(200, 275, 25, GREEN)
player2_body, player2_shape = create_ball(600, 275, 25, BLUE)

# Scores
player1_score = 0
player2_score = 0

# Collision handler for penalty lines
def penalty_handler(arbiter, space, data):
    global player1_score, player2_score
    shape = arbiter.shapes[0]
    if shape == player1_shape:
        player1_score -= 1
    elif shape == player2_shape:
        player2_score -= 1
    return True

handler = space.add_collision_handler(0, 1)
handler.begin = penalty_handler

# Game loop
clock = pygame.time.Clock()
running = True
movement_force = 500
start_time = pygame.time.get_ticks()
game_duration = 2 * 60 * 1000  # 2 minutes in milliseconds

while running:
    dt = clock.tick(60) / 1000  # Delta time in seconds

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Handle player controls
    keys = pygame.key.get_pressed()

    # Player 1 controls
    if keys[pygame.K_w]:
        player1_body.apply_force_at_local_point((0, -movement_force), (0, 0))
    if keys[pygame.K_s]:
        player1_body.apply_force_at_local_point((0, movement_force), (0, 0))
    if keys[pygame.K_a]:
        player1_body.apply_force_at_local_point((-movement_force, 0), (0, 0))
    if keys[pygame.K_d]:
        player1_body.apply_force_at_local_point((movement_force, 0), (0, 0))

    # Player 2 controls
    if keys[pygame.K_UP]:
        player2_body.apply_force_at_local_point((0, -movement_force), (0, 0))
    if keys[pygame.K_DOWN]:
        player2_body.apply_force_at_local_point((0, movement_force), (0, 0))
    if keys[pygame.K_LEFT]:
        player2_body.apply_force_at_local_point((-movement_force, 0), (0, 0))
    if keys[pygame.K_RIGHT]:
        player2_body.apply_force_at_local_point((movement_force, 0), (0, 0))

    # Step the physics simulation
    space.step(dt)

    # Clear the screen
    screen.fill(WHITE)

    # Draw everything
    space.debug_draw(draw_options)

    # Draw scores
    font = pygame.font.Font(None, 36)
    score_text = font.render(f"Player 1: {player1_score}  Player 2: {player2_score}", True, (0, 0, 0))
    screen.blit(score_text, (10, 10))

    # Check game timer
    elapsed_time = pygame.time.get_ticks() - start_time
    if elapsed_time > game_duration:
        running = False

    # Update the display
    pygame.display.flip()

# Determine the winner
if player1_score > player2_score:
    print("Player 1 wins!")
elif player2_score > player1_score:
    print("Player 2 wins!")
else:
    print("It's a tie!")

pygame.quit()
