from array import array
import math
import sys

import pygame
from .marble import Marble
from .wall import Wall

# Game Engine

WHITE = (255, 255, 255)
DARK = (40, 40, 50)
WALL_COLOR = (90, 90, 110)
GOAL_COLOR = (60, 200, 120)

class GameEngine:
    DIFFICULTIES = {
        "Easy": {"tilt_strength": 0.45, "friction": 0.05, "time_limit_ms": 60000},
        "Medium": {"tilt_strength": 0.6, "friction": 0.02, "time_limit_ms": 45000},
        "Hard": {"tilt_strength": 0.8, "friction": 0.01, "time_limit_ms": 30000},
    }

    def __init__(self, width, height):
        self.width = width
        self.height = height

        self.marble = Marble(50, 50)
        self.difficulty = "Medium"
        self.tilt_strength = self.DIFFICULTIES[self.difficulty]["tilt_strength"]
        self.friction = self.DIFFICULTIES[self.difficulty]["friction"]
        self.max_speed = 9

        self.walls = self._build_maze()
        self.goal_x, self.goal_y, self.goal_radius = width - 60, height - 60, 22

        self.time_limit_ms = 45000
        self.start_ticks = pygame.time.get_ticks()

        self.font = pygame.font.SysFont("Arial", 26)
        self.game_over = False
        self.result = None  # "solved" or "timeout"
        self.finish_time_ms = None
        self.exit_requested = False
        self.sounds = self._create_sounds()

    @staticmethod
    def _make_tone(notes):
        """Build a short PCM sound from (frequency, duration) note pairs."""
        mixer_format = pygame.mixer.get_init()
        if mixer_format is None:
            return None
        sample_rate, sample_size, channels = mixer_format
        if sample_size != -16:
            return None

        samples = array("h")
        for frequency, duration in notes:
            count = int(sample_rate * duration)
            for i in range(count):
                # Brief fade-in/out avoids clicks at the start and end of notes.
                envelope = min(1.0, i / 180, (count - i - 1) / 500)
                sample = int(10000 * max(0, envelope) * math.sin(2 * math.pi * frequency * i / sample_rate))
                for _ in range(channels):
                    samples.append(sample)

        if sys.byteorder != "little":
            samples.byteswap()
        return pygame.mixer.Sound(buffer=samples.tobytes())

    @classmethod
    def _create_sounds(cls):
        """Initialize the mixer when available and create the three game cues."""
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=22050, size=-16, channels=1)
            return {
                "bounce": cls._make_tone([(280, 0.07)]),
                "goal": cls._make_tone([(523, 0.11), (659, 0.11), (784, 0.18)]),
                "timeout": cls._make_tone([(587, 0.14), (440, 0.14), (294, 0.24)]),
            }
        except (pygame.error, ValueError):
            # Audio is optional; gameplay remains available without a device.
            return {"bounce": None, "goal": None, "timeout": None}

    def _play_sound(self, name):
        sound = self.sounds.get(name)
        if sound is not None:
            sound.play()

    def _build_maze(self):
        walls = []
        t = 16  # wall thickness

        # outer boundary
        walls.append(Wall(0, 0, self.width, t))
        walls.append(Wall(0, self.height - t, self.width, t))
        walls.append(Wall(0, 0, t, self.height))
        walls.append(Wall(self.width - t, 0, t, self.height))

        # a few internal walls forming a simple winding path
        walls.append(Wall(0, 140, self.width - 140, t))
        walls.append(Wall(140, 260, self.width - 140, t))
        walls.append(Wall(0, 380, self.width - 140, t))

        return walls

    def handle_event(self, event):
        if not self.game_over or event.type != pygame.KEYDOWN:
            return

        key_to_difficulty = {
            pygame.K_1: "Easy",
            pygame.K_2: "Medium",
            pygame.K_3: "Hard",
        }
        if event.key in key_to_difficulty:
            self.start_new_game(key_to_difficulty[event.key])
        elif event.key in (pygame.K_ESCAPE, pygame.K_q):
            self.exit_requested = True

    def start_new_game(self, difficulty):
        """Reset the round and apply the selected difficulty settings."""
        settings = self.DIFFICULTIES[difficulty]
        self.difficulty = difficulty
        self.tilt_strength = settings["tilt_strength"]
        self.friction = settings["friction"]
        self.time_limit_ms = settings["time_limit_ms"]
        self.marble.x, self.marble.y = 50, 50
        self.marble.vx = self.marble.vy = 0
        self.start_ticks = pygame.time.get_ticks()
        self.game_over = False
        self.result = None
        self.finish_time_ms = None

    def handle_input(self):
        if self.game_over:
            return

        mouse_x, mouse_y = pygame.mouse.get_pos()
        dx = mouse_x - self.width // 2
        dy = mouse_y - self.height // 2
        dist = max(1, (dx ** 2 + dy ** 2) ** 0.5)
        ax = (dx / dist) * self.tilt_strength
        ay = (dy / dist) * self.tilt_strength
        self.marble.vx += ax
        self.marble.vy += ay

    def update(self):
        if self.game_over:
            return

        elapsed = pygame.time.get_ticks() - self.start_ticks
        if elapsed >= self.time_limit_ms:
            self.game_over = True
            self.result = "timeout"
            self._play_sound("timeout")
            return

        self.marble.vx *= (1 - self.friction)
        self.marble.vy *= (1 - self.friction)

        speed = (self.marble.vx ** 2 + self.marble.vy ** 2) ** 0.5
        if speed > self.max_speed:
            scale = self.max_speed / speed
            self.marble.vx *= scale
            self.marble.vy *= scale

        self.marble.x += self.marble.vx
        self.marble.y += self.marble.vy

        if self._resolve_wall_collisions():
            self._play_sound("bounce")

        gx = self.goal_x - self.marble.x
        gy = self.goal_y - self.marble.y
        if (gx ** 2 + gy ** 2) ** 0.5 <= self.goal_radius:
            self.game_over = True
            self.result = "solved"
            self.finish_time_ms = elapsed
            self._play_sound("goal")

    def _resolve_wall_collisions(self):
        bounced = False
        for wall in self.walls:
            wall_rect = wall.rect()
            # Clamp the circle center to the rectangle. The distance to
            # this closest point is the true circle/rectangle distance;
            # unlike the marble's bounding box, it does not report a
            # collision in the empty diagonal area around a wall corner.
            closest_x = max(wall_rect.left, min(self.marble.x, wall_rect.right))
            closest_y = max(wall_rect.top, min(self.marble.y, wall_rect.bottom))
            dx = self.marble.x - closest_x
            dy = self.marble.y - closest_y
            distance_sq = dx * dx + dy * dy
            radius = self.marble.radius

            if distance_sq >= radius * radius:
                continue

            if distance_sq > 0:
                distance = distance_sq ** 0.5
                nx, ny = dx / distance, dy / distance
                penetration = radius - distance
            else:
                # The center is inside the wall rectangle. Push it out
                # through the nearest face so it cannot remain embedded.
                face_distances = (
                    (self.marble.x - wall_rect.left, -1.0, 0.0),
                    (wall_rect.right - self.marble.x, 1.0, 0.0),
                    (self.marble.y - wall_rect.top, 0.0, -1.0),
                    (wall_rect.bottom - self.marble.y, 0.0, 1.0),
                )
                face_distance, nx, ny = min(face_distances, key=lambda face: face[0])
                penetration = radius + face_distance

            self.marble.x += nx * penetration
            self.marble.y += ny * penetration

            # Reflect only the velocity pointing into the surface. This
            # preserves tangential motion and avoids repeatedly reversing
            # velocity while the marble is being separated from a wall.
            normal_speed = self.marble.vx * nx + self.marble.vy * ny
            if normal_speed < 0:
                restitution = 0.3
                self.marble.vx -= (1 + restitution) * normal_speed * nx
                self.marble.vy -= (1 + restitution) * normal_speed * ny
                bounced = True

        return bounced

    def render(self, screen):
        screen.fill(DARK)

        for wall in self.walls:
            pygame.draw.rect(screen, WALL_COLOR, wall.rect())

        pygame.draw.circle(screen, GOAL_COLOR, (self.goal_x, self.goal_y), self.goal_radius)
        pygame.draw.circle(screen, WHITE, (int(self.marble.x), int(self.marble.y)), self.marble.radius)

        elapsed = pygame.time.get_ticks() - self.start_ticks
        seconds_left = max(0, (self.time_limit_ms - elapsed) // 1000)
        timer_text = self.font.render(f"Time: {seconds_left}s", True, WHITE)
        screen.blit(timer_text, (10, 10))

        if self.game_over:
            # Dim the playfield and present the result in the game window.
            overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 185))
            screen.blit(overlay, (0, 0))

            panel_width = min(440, self.width - 40)
            panel_height = 240
            panel = pygame.Rect(
                (self.width - panel_width) // 2,
                (self.height - panel_height) // 2,
                panel_width,
                panel_height,
            )
            pygame.draw.rect(screen, (32, 36, 48), panel, border_radius=12)
            pygame.draw.rect(screen, (110, 120, 145), panel, width=2, border_radius=12)

            title_font = pygame.font.SysFont("Arial", 34, bold=True)
            detail_font = pygame.font.SysFont("Arial", 23)
            prompt_font = pygame.font.SysFont("Arial", 18)
            if self.result == "solved":
                title = "Maze Solved!"
                detail = f"Finish time: {self.finish_time_ms / 1000:.1f} seconds"
                title_color = GOAL_COLOR
            else:
                title = "Time's Up!"
                detail = "The maze was not solved in time."
                title_color = (245, 145, 120)

            title_surface = title_font.render(title, True, title_color)
            detail_surface = detail_font.render(detail, True, WHITE)
            prompt_surface = prompt_font.render("Choose a difficulty to play again", True, (190, 195, 210))
            choices_surface = prompt_font.render("1  Easy     2  Medium     3  Hard", True, WHITE)
            exit_surface = prompt_font.render("Esc or Q  Exit", True, (190, 195, 210))
            screen.blit(title_surface, title_surface.get_rect(center=(self.width // 2, panel.y + 48)))
            screen.blit(detail_surface, detail_surface.get_rect(center=(self.width // 2, panel.y + 98)))
            screen.blit(prompt_surface, prompt_surface.get_rect(center=(self.width // 2, panel.y + 145)))
            screen.blit(choices_surface, choices_surface.get_rect(center=(self.width // 2, panel.y + 178)))
            screen.blit(exit_surface, exit_surface.get_rect(center=(self.width // 2, panel.y + 210)))
