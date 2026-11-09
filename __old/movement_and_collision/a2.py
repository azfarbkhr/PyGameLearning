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
create_wall((0, 0), (0, screen_height))  # Left wall
create_wall((0, screen_height), (screen_width, screen_height))  # Bottom wall
create_wall((screen_width, screen_height), (screen_width, 0))  # Right wall
create_wall((screen_width, 0), (0, 0))  # Top wall

# Create players as balls
player1_body, player1_shape = create_ball(200, 275, 25, GREEN)
player2_body, player2_shape = create_ball(600, 275, 25, BLUE)

# Game loop
clock = pygame.time.Clock()
running = True
movement_force = 500

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

    # Update the display
    pygame.display.flip()

pygame.quit()
