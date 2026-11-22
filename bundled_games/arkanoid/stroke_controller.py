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
    "show_quit_button": False
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

        # ── Save-under state for cursor dirty-rect fix ────────────────────────
        # We save the pixels under the cursor before drawing so we can restore
        # them next frame — preventing the cursor from leaving a permanent trail
        # in games that don't redraw their background every frame (e.g. Arkanoid).
        self._cursor_save = None   # dict with 'surf' and 'pos', or None
        
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
            cfg_path = r"E:\Stroke\FlexStoreLauncher\input_config.json"
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    self.cfg.update(json.load(f))
        except Exception:
            pass

    def _get_screen_size(self):
        """Return current screen (w, h) safely."""
        try:
            return pygame.display.get_surface().get_size()
        except:
            return 800, 600

    def _quit_btn_rect(self, w):
        """Return the pygame.Rect of the QUIT button given screen width."""
        return pygame.Rect(w - 120, 10, 110, 50)

    def _check_quit_click(self):
        """
        Check for a direct mouse LEFT-CLICK on the quit button.
        This runs every frame regardless of whether a joystick is connected,
        so that keyboard/mouse players can always quit.
        Returns True if QUIT was posted.
        """
        if not game_config.get("show_quit_button", True):
            return False
        w, h = self._get_screen_size()
        btn = self._quit_btn_rect(w)
        # Check real hardware mouse button press (works for mouse + keyboard players)
        mx, my = pygame.mouse.get_pos()
        if btn.collidepoint(mx, my):
            btns = pygame.mouse.get_pressed()
            if btns[0]:  # left button down
                pygame.event.post(pygame.event.Event(pygame.QUIT))
                return True
            # Also fire after 30 frames of hovering (faster than before: 0.5s)
            if self.hover_frames >= 30:
                pygame.event.post(pygame.event.Event(pygame.QUIT))
                self.hover_frames = -40
                return True
        return False

    def update(self):
        w, h = self._get_screen_size()
        current_pos = pygame.mouse.get_pos()

        # ── Hover counter (used by both joystick AND regular mouse players) ──
        dist_sq = (current_pos[0] - self.last_pos[0])**2 + \
                  (current_pos[1] - self.last_pos[1])**2
        if dist_sq < 9:
            self.hover_frames += 1
        else:
            self.hover_frames = 0
            self.last_pos = current_pos

        # ── Quit button: check direct click / hover (always, no joystick needed) ──
        if self._check_quit_click():
            return

        # ── Everything below only runs when a joystick is connected ──────────
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

        self.cursor_x = max(0, min(w, self.cursor_x))
        self.cursor_y = max(0, min(h, self.cursor_y))
        
        if moved:
            pygame.mouse.set_pos((int(self.cursor_x), int(self.cursor_y)))

        # ANALOG x-axis for smooth paddle control. Instead of posting a fixed
        # LEFT/RIGHT key past a deadzone (threshold-then-fast), expose the raw
        # proportional value so the game can move the paddle in real time. A
        # tiny floor only kills sensor drift at rest.
        self.analog_x = x if abs(x) > 0.03 else 0.0

        # Old hover-to-action (for joystick play area clicks / non-quit actions)
        if self.hover_frames == 60:
            current_pos2 = pygame.mouse.get_pos()
            if game_config.get("type", "mouse") == "mouse":
                event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {'pos': current_pos2, 'button': 1, 'window': None})
                pygame.event.post(event)
            else:
                action_key = getattr(pygame, game_config.get("action_button", "K_SPACE"), pygame.K_SPACE)
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, {'key': action_key, 'unicode': '', 'mod': 0, 'scancode': 0, 'window': None}))
                pygame.event.post(pygame.event.Event(pygame.KEYUP, {'key': action_key, 'unicode': '', 'mod': 0, 'scancode': 0, 'window': None}))
            self.hover_frames = -40
            
    def draw_cursor(self, window):
        w, h = window.get_size()

        # ── Step 1: Restore pixels saved from LAST frame ─────────────────────
        # This erases the cursor dot/arc from wherever it was drawn last frame
        # before anything new is drawn — fixing the permanent trail in games
        # (like Arkanoid) that don't repaint the whole background every frame.
        if self._cursor_save is not None:
            try:
                window.blit(self._cursor_save['surf'], self._cursor_save['pos'])
            except Exception:
                pass
            self._cursor_save = None

        # ── Step 2: Draw the QUIT button (always) ────────────────────────────
        if game_config.get("show_quit_button", True):
            btn_rect = self._quit_btn_rect(w)
            # Highlight button when cursor is hovering over it
            mx_tmp, my_tmp = pygame.mouse.get_pos()
            hovering = btn_rect.collidepoint(mx_tmp, my_tmp)
            bg_color  = (230, 30, 30) if hovering else (180, 0, 0)
            pygame.draw.rect(window, bg_color, btn_rect, border_radius=10)
            pygame.draw.rect(window, (255, 255, 255), btn_rect, 3, border_radius=10)

            # Draw hover-progress arc inside button when hovering
            if hovering and self.hover_frames > 0:
                progress    = min(self.hover_frames / 30.0, 1.0) * 2 * math.pi
                arc_rect    = btn_rect.inflate(-8, -8)
                start_angle = math.pi / 2 - progress
                stop_angle  = math.pi / 2
                pygame.draw.arc(window, (0, 255, 0), arc_rect, start_angle, stop_angle, 4)

            if pygame.font.get_init():
                try:
                    font = pygame.font.SysFont(None, 36)
                    text = font.render("QUIT", True, (255, 255, 255))
                    text_rect = text.get_rect(center=btn_rect.center)
                    window.blit(text, text_rect)
                except:
                    pass

        mx, my = pygame.mouse.get_pos()
        is_keyboard = game_config.get("type", "mouse") == "keyboard"
        near_quit   = (mx > w - 200 and my < 150)

        # ── Step 3: Draw cursor dot (only when near quit for keyboard games) ──
        draw_dot = (not is_keyboard) or near_quit
        if draw_dot:
            pygame.mouse.set_visible(False)

            # Save pixels under cursor BEFORE drawing so we can restore next frame
            radius = 20
            save_rect = pygame.Rect(mx - radius, my - radius, radius * 2, radius * 2)
            save_rect = save_rect.clip(window.get_rect())
            if save_rect.width > 0 and save_rect.height > 0:
                try:
                    saved_surf = window.subsurface(save_rect).copy()
                    self._cursor_save = {'surf': saved_surf, 'pos': save_rect.topleft}
                except Exception:
                    self._cursor_save = None

            # Draw the cursor dot
            dot_color = (255, 80, 80) if is_keyboard else (255, 0, 0)
            pygame.draw.circle(window, dot_color, (mx, my), 8)

            # Draw hover progress ring around cursor (only outside quit button)
            btn_rect2 = self._quit_btn_rect(w)
            if self.hover_frames > 0 and not btn_rect2.collidepoint(mx, my):
                progress    = (self.hover_frames / 60.0) * 2 * math.pi
                arc_rect    = (mx - 15, my - 15, 30, 30)
                start_angle = math.pi / 2 - progress
                stop_angle  = math.pi / 2
                pygame.draw.arc(window, (0, 255, 0), arc_rect, start_angle, stop_angle, 4)
        else:
            pygame.mouse.set_visible(False)

vc = None
