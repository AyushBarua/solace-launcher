import pygame
import math
import json
import os
import sys

def get_multiplier():
    """Returns the difficulty multiplier injected into game_config.json."""
    try:
        with open("game_config.json", "r") as f:
            cfg = json.load(f)
            return cfg.get("difficulty_multiplier", 1.0)
    except:
        return 1.0

# Load game_config.json
game_config = {
    "type": "mouse", 
    "force_fullscreen": True, 
    "show_quit_button": True
}
try:
    _cfg_path = "game_config.json"
    if os.path.exists(_cfg_path):
        with open(_cfg_path, "r", encoding="utf-8") as f:
            game_config.update(json.load(f))
except Exception:
    pass

if game_config.get("force_fullscreen", True):
    # Force fullscreen for any game that imports this controller, preserving aspect ratio!
    original_set_mode = pygame.display.set_mode
    def _fullscreen_set_mode(size=(0,0), flags=0, depth=0, display=0, vsync=0):
        if size == (0, 0):
            return original_set_mode(size, flags | pygame.FULLSCREEN, depth, display, vsync)
        return original_set_mode(size, flags | pygame.FULLSCREEN | pygame.SCALED, depth, display, vsync)
    pygame.display.set_mode = _fullscreen_set_mode


class VirtualController:
    def __init__(self):
        try:
            pygame.joystick.init()
            self.joysticks = []
            for i in range(pygame.joystick.get_count()):
                j = pygame.joystick.Joystick(i)
                j.init()
                self.joysticks.append(j)
        except Exception:
            self.joysticks = []
        
        try:
            self.last_pos = pygame.mouse.get_pos()
        except:
            self.last_pos = (400, 250)
            
        self.cursor_x, self.cursor_y = self.last_pos
        self.active = len(self.joysticks) > 0
        self.hover_frames = 0
        
        # Load launcher calibration settings
        self.cfg = {
            "inner_dead_zone": 0.20,
            "sensitivity": 1.0,
            "flip_x": False,
            "flip_y": False,
            "cal_x": 0.0,
            "cal_y": 0.0
        }
        try:
            # Resolve config relative to the game's working directory, then
            # fall back to %LOCALAPPDATA%\Solace\ — never use a hardcoded path.
            candidates = [
                os.path.join(os.getcwd(), "input_config.json"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "input_config.json"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Solace", "input_config.json"),
            ]
            for cfg_path in candidates:
                if os.path.exists(cfg_path):
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        self.cfg.update(json.load(f))
                    break
        except Exception:
            pass

    def update(self):
        if not self.active:
            return
            
        raw_x = 0.0
        raw_y = 0.0
        
        for j in self.joysticks:
            if j.get_numaxes() >= 2:
                rx = j.get_axis(0)
                ry = j.get_axis(1)
                if abs(rx) > abs(raw_x): raw_x = rx
                if abs(ry) > abs(raw_y): raw_y = ry

        x = raw_x - self.cfg["cal_x"]
        y = raw_y - self.cfg["cal_y"]
        x *= self.cfg["sensitivity"]
        y *= self.cfg["sensitivity"]
        x = max(-1.0, min(1.0, x))
        y = max(-1.0, min(1.0, y))
        
        if self.cfg["flip_x"]: x = -x
        if self.cfg["flip_y"]: y = -y

        idz = self.cfg["inner_dead_zone"]
        moved = False
        
        if abs(x) > idz:
            self.cursor_x += x * 15
            moved = True
        if abs(y) > idz:
            self.cursor_y += y * 15
            moved = True
            
        w, h = 800, 600
        try:
            w, h = pygame.display.get_surface().get_size()
        except:
            pass

        self.cursor_x = max(0, min(w, self.cursor_x))
        self.cursor_y = max(0, min(h, self.cursor_y))
        
        if moved:
            pygame.mouse.set_pos((int(self.cursor_x), int(self.cursor_y)))

        # Keyboard emulation
        if game_config.get("type", "mouse") == "keyboard":
            if not hasattr(self, 'key_left_pressed'):
                self.key_left_pressed = False
                self.key_right_pressed = False

            key_l = getattr(pygame, game_config.get("x_axis_left", "K_LEFT"), pygame.K_LEFT)
            key_r = getattr(pygame, game_config.get("x_axis_right", "K_RIGHT"), pygame.K_RIGHT)

            if x < -idz and not self.key_left_pressed:
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, {'key': key_l, 'unicode': '', 'mod': 0, 'scancode': 0, 'window': None}))
                self.key_left_pressed = True
            elif x >= -idz and self.key_left_pressed:
                pygame.event.post(pygame.event.Event(pygame.KEYUP, {'key': key_l, 'unicode': '', 'mod': 0, 'scancode': 0, 'window': None}))
                self.key_left_pressed = False

            if x > idz and not self.key_right_pressed:
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, {'key': key_r, 'unicode': '', 'mod': 0, 'scancode': 0, 'window': None}))
                self.key_right_pressed = True
            elif x <= idz and self.key_right_pressed:
                pygame.event.post(pygame.event.Event(pygame.KEYUP, {'key': key_r, 'unicode': '', 'mod': 0, 'scancode': 0, 'window': None}))
                self.key_right_pressed = False
            
        current_pos = pygame.mouse.get_pos()
        
        # Hover to click logic
        dist_sq = (current_pos[0] - self.last_pos[0])**2 + (current_pos[1] - self.last_pos[1])**2
        if dist_sq < 9:
            self.hover_frames += 1
        else:
            self.hover_frames = 0
            self.last_pos = current_pos
            
        if self.hover_frames == 60:
            if game_config.get("show_quit_button", True):
                # Check if click is on QUIT button
                if current_pos[0] > w - 130 and current_pos[1] < 70:
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
                    self.hover_frames = -40
                    return
                    
            if game_config.get("type", "mouse") == "mouse":
                event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {'pos': current_pos, 'button': 1, 'window': None})
                pygame.event.post(event)
            else:
                action_key = getattr(pygame, game_config.get("action_button", "K_SPACE"), pygame.K_SPACE)
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, {'key': action_key, 'unicode': '', 'mod': 0, 'scancode': 0, 'window': None}))
                pygame.event.post(pygame.event.Event(pygame.KEYUP, {'key': action_key, 'unicode': '', 'mod': 0, 'scancode': 0, 'window': None}))
            self.hover_frames = -40
            
    def draw_cursor(self, window):
        w, h = window.get_size()
        
        if game_config.get("show_quit_button", True):
            btn_rect = pygame.Rect(w - 120, 10, 110, 50)
            pygame.draw.rect(window, (200, 0, 0), btn_rect, border_radius=10)
            pygame.draw.rect(window, (255, 255, 255), btn_rect, 3, border_radius=10)
            
            if pygame.font.get_init():
                try:
                    font = pygame.font.SysFont(None, 36)
                    text = font.render("QUIT", True, (255, 255, 255))
                    text_rect = text.get_rect(center=btn_rect.center)
                    window.blit(text, text_rect)
                except:
                    pygame.draw.line(window, (255,255,255), (w-80, 20), (w-50, 50), 5)
                    pygame.draw.line(window, (255,255,255), (w-50, 20), (w-80, 50), 5)
            else:
                pygame.draw.line(window, (255,255,255), (w-80, 20), (w-50, 50), 5)
                pygame.draw.line(window, (255,255,255), (w-50, 20), (w-80, 50), 5)

        mx, my = pygame.mouse.get_pos()
        
        # Don't draw the virtual cursor in keyboard games to prevent dirty-rect trails,
        # EXCEPT when hovering near the QUIT button so they can see what they're doing!
        is_keyboard = game_config.get("type", "mouse") == "keyboard"
        near_quit = (mx > w - 200 and my < 150)
        
        if is_keyboard and not near_quit:
            return
            
        pygame.draw.circle(window, (255, 0, 0), (mx, my), 8)
        
        if self.hover_frames > 0:
            progress = (self.hover_frames / 60.0) * 2 * math.pi
            rect = (mx - 15, my - 15, 30, 30)
            start_angle = math.pi / 2 - progress
            stop_angle = math.pi / 2
            pygame.draw.arc(window, (0, 255, 0), rect, start_angle, stop_angle, 4)

vc = None
