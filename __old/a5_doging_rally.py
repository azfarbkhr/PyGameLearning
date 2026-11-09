import pygame
import pymunk
import pymunk.pygame_util
import threading
import time 
import random

# Initialize Pygame
pygame.init()

# Screen setup
screen_width, screen_height = 800, 600
screen = pygame.display.set_mode((screen_width, screen_height))
pygame.display.set_caption("Doging Rally")

# Colors
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
RED = (255, 0, 0)
BLACK = (0, 0, 0)

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

# Function to display input screen for player names
def get_player_names():
    font = pygame.font.Font(None, 36)
    input_box1 = pygame.Rect(200, 200, 400, 50)
    input_box2 = pygame.Rect(200, 300, 400, 50)
    color_inactive = pygame.Color('lightskyblue3')
    color_active = pygame.Color('dodgerblue2')
    color1 = color_inactive
    color2 = color_inactive
    active1 = False
    active2 = False
    text1 = ''
    text2 = ''
    done = False

    while not done:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                # If the user clicked on the input_box1
                if input_box1.collidepoint(event.pos):
                    active1 = True
                    active2 = False
                elif input_box2.collidepoint(event.pos):
                    active2 = True
                    active1 = False
                else:
                    active1 = False
                    active2 = False
                # Change the current color of the input box
                color1 = color_active if active1 else color_inactive
                color2 = color_active if active2 else color_inactive
            if event.type == pygame.KEYDOWN:
                if active1:
                    if event.key == pygame.K_RETURN:
                        active1 = False
                        color1 = color_inactive
                    elif event.key == pygame.K_BACKSPACE:
                        text1 = text1[:-1]
                    else:
                        text1 += event.unicode
                elif active2:
                    if event.key == pygame.K_RETURN:
                        active2 = False
                        color2 = color_inactive
                    elif event.key == pygame.K_BACKSPACE:
                        text2 = text2[:-1]
                    else:
                        text2 += event.unicode
        
        screen.fill(WHITE)
        txt_surface1 = font.render(text1, True, color1)
        txt_surface2 = font.render(text2, True, color2)
        
        # Resize the box if the text is too long.
        width1 = max(400, txt_surface1.get_width() + 10)
        width2 = max(400, txt_surface2.get_width() + 10)
        input_box1.w = width1
        input_box2.w = width2
        
        # Blit the text.
        screen.blit(txt_surface1, (input_box1.x + 5, input_box1.y + 5))
        screen.blit(txt_surface2, (input_box2.x + 5, input_box2.y + 5))
        
        # Blit the input_box rect.
        pygame.draw.rect(screen, color1, input_box1, 2)
        pygame.draw.rect(screen, color2, input_box2, 2)
        
        # Instruction text
        instruction = font.render("Enter Player 1 and Player 2 Names", True, (0, 0, 0))
        screen.blit(instruction, (200, 150))
        
        pygame.display.flip()
        
        if text1 and text2 and not active1 and not active2:
            done = True

    return text1, text2

# Get player names using the input screen
player1_name, player2_name = get_player_names()

# Create players as balls
player1_body, player1_shape = create_ball(200, 275, 25, GREEN)
player2_body, player2_shape = create_ball(600, 275, 25, BLUE)

# Scores
player1_score = 0
player2_score = 0

# Commentary list
commentary = [
    "The arena is set, and the clash of titans begins! {player1_name} vs {player2_name}!",
]

# Taunts for players
losing_taunts = [
    "{player_name}, seekh kar aao beta, phir aa ke khelo!",
    "Yeh kya ho raha hai, {player_name}? Score ki izzat kar lo!",
    "Haar ka gham hai ya bas slow motion mein chal rahe ho, {player_name}?",
    "{player_name}, kya haal hai bhai? Game se toh lagta hai ghar ka kaam kar rahe ho!",
    "Zyada mat ro, {player_name}, agli dafa jeetne ka bhi chance mil sakta hai.",
    "{player_name}, yeh match chal raha hai ya comedy night? Audience confused hai!",
    "Beta {player_name}, ball ke saath dosti kar lo, woh tumhari sun nahi raha.",
    "Tum jeet rahe ho ya bas maze kar rahe ho, {player_name}?"
]

winning_taunts = [
    "Aray wah {player_name}, itna shor macha rahe ho, lagta hai world cup jeet gaye!",
    "{player_name}, aankhein kholo, kabhi haarna bhi seekho!",
    "Bas, ab brag mat karo, {player_name}, sabko pata hai tum jeet rahe ho.",
    "Khuda ka shukar karo opponent tumhare level ka nahi tha, {player_name}.",
    "Lagta hai practice kar ke aaye ho, ya kisi ko cheat code mil gaya, {player_name}?",
    "Aray wah {player_name}, tumhari toh star player wali vibe hai!",
    "Bhai thoda aram se, {player_name}, duniya ko pata hai tum pro ho.",
    "Lagta hai tumhara din hai, {player_name}, lekin zyada udd mat jaana!"
]

# Function to generate random taunts
def generate_random_taunt(player1_score, player2_score, player1_name, player2_name):
    if random.randint(0, 1) == 0:  # Losing player
        if player1_score < player2_score:
            return random.choice(losing_taunts).format(player_name=player1_name)
        else:
            return random.choice(losing_taunts).format(player_name=player2_name)
    else:  # Winning player
        if player1_score > player2_score:
            return random.choice(winning_taunts).format(player_name=player1_name)
        else:
            return random.choice(winning_taunts).format(player_name=player2_name)

# Commentary generation in a separate thread
def commentary_thread():
    global commentary
    while True:
        time.sleep(5)  # Generate comments every 5 seconds
        comment = generate_random_taunt(player1_score, player2_score, player1_name, player2_name)
        commentary.append(comment)
        if len(commentary) > 3:  # Limit commentary to last 10 messages
            commentary.pop(0)

# Start the commentary thread
threading.Thread(target=commentary_thread, daemon=True).start()

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
game_duration = 1 * 60 * 1000  # 2 minutes in milliseconds

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
    score_text = font.render(f"{player1_name}: {player1_score}  {player2_name}: {player2_score}", True, BLACK)
    screen.blit(score_text, (10, 10))

    # Draw commentary
    commentary_font = pygame.font.Font(None, 24)
    y_offset = 50
    for line in commentary:
        comment_text = commentary_font.render(line, True, BLACK)
        screen.blit(comment_text, (10, y_offset))
        y_offset += 25

    # Check game timer
    elapsed_time = pygame.time.get_ticks() - start_time
    if elapsed_time > game_duration:
        running = False

    # Update the display
    pygame.display.flip()

# Determine the winner
if player1_score > player2_score:
    print(f"{player1_name} wins with a score of {player1_score}!")
    print(f"{player2_name} loses with a score of {player2_score}.")
elif player2_score > player1_score:
    print(f"{player2_name} wins with a score of {player2_score}!")
    print(f"{player1_name} loses with a score of {player1_score}.")
else:
    print("It's a tie!")

pygame.quit()
