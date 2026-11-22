"""
GamepadThread — polls pygame joystick axes (Arduino IMU / custom controller).

Routes raw axes through InputProcessor for dead-zone, calibration,
sensitivity, and axis-flip, then emits directional navigation signals
and a hover-to-launch progress signal.

Axis mapping (post-processor):
  x > +threshold  → 'right'
  x < -threshold  → 'left'
  y > +threshold  → 'down'
  y < -threshold  → 'up'
  Still for 2 s   → 'action'  (hover-to-launch)
"""
import pygame
from PyQt6.QtCore import QThread, pyqtSignal

from core.input_processor import InputProcessor


class GamepadThread(QThread):
    button_pressed   = pyqtSignal(str, bool)          # 'up' | 'down' | 'left' | 'right' | 'action', is_hover
    hover_progress   = pyqtSignal(float)         # 0.0 → 1.0  (fill bar)
    controller_state = pyqtSignal(bool, str)          # True = connected, string = name
    raw_axes         = pyqtSignal(float, float)  # live raw x, y for Settings preview
    raw_squeeze      = pyqtSignal(float)         # analog squeeze 0..1 (axis 2, firmware v6+)

    COOLDOWN_FRAMES      = 20   # ~333 ms at 60 fps  (between navigation steps)
    HOVER_MAX_FRAMES     = 120  # 2 s dwell → 'action'
    POST_ACTION_COOLDOWN = 120  # 2 s after auto-launch before next input

    def __init__(self, processor: InputProcessor, parent=None):
        super().__init__(parent)
        self.running   = True
        self.processor = processor

        pygame.init()
        pygame.joystick.init()
        self.joysticks: list[pygame.joystick.JoystickType] = []
        self._sx = 0.0   # EMA smoothed x axis state
        self._sy = 0.0   # EMA smoothed y axis state

    # ── helpers ───────────────────────────────────────────────────────────────

    def _refresh_joysticks(self):
        for j in self.joysticks:
            try:
                j.quit()
            except Exception:
                pass
        self.joysticks = []
        for i in range(pygame.joystick.get_count()):
            j = pygame.joystick.Joystick(i)
            j.init()
            self.joysticks.append(j)
            
        if len(self.joysticks) > 0:
            name = self.joysticks[0].get_name()
            if name == "ESP32S3_DEV":
                name = "Solace controller"
            self.controller_state.emit(True, name)
        else:
            self.controller_state.emit(False, "Keyboard")

    # ── thread body ───────────────────────────────────────────────────────────

    def run(self):
        self._refresh_joysticks()
        clock       = pygame.time.Clock()
        cooldown    = 0
        hover_timer = 0
        prev_btn    = False

        while self.running:
            clock.tick(60)
            pygame.event.pump()

            # Hot-plug detection
            if pygame.joystick.get_count() != len(self.joysticks):
                self._refresh_joysticks()

            if not self.joysticks:
                self.raw_axes.emit(0.0, 0.0)
                continue

            # Read first joystick (always — so live preview never freezes during cooldown)
            j = self.joysticks[0]
            raw_x = j.get_axis(0) if j.get_numaxes() > 0 else 0.0
            raw_y = j.get_axis(1) if j.get_numaxes() > 1 else 0.0

            # Exponential smoothing (EMA) to suppress noise/jitter across machines.
            # Alpha 0.2 → strong smoothing; raise toward 1.0 for more responsiveness.
            _EMA_ALPHA = 0.2
            self._sx = _EMA_ALPHA * raw_x + (1.0 - _EMA_ALPHA) * self._sx
            self._sy = _EMA_ALPHA * raw_y + (1.0 - _EMA_ALPHA) * self._sy
            self.raw_axes.emit(self._sx, self._sy)

            # Squeeze (FSR). Comes EITHER as analog axis 2 (firmware v6+) OR as
            # gamepad button 0 (any firmware). Forward the stronger of the two so
            # the assessment wizard registers a squeeze regardless of firmware.
            btn = j.get_button(0) if j.get_numbuttons() > 0 else False
            squeeze_analog = max(0.0, j.get_axis(2)) if j.get_numaxes() > 2 else 0.0
            self.raw_squeeze.emit(max(squeeze_analog, 1.0 if btn else 0.0))

            squeeze_edge = btn and not prev_btn      # select/confirm, edge-triggered
            prev_btn = btn

            if cooldown > 0:
                cooldown -= 1
                continue

            if squeeze_edge:
                self.button_pressed.emit("action", False)
                hover_timer = 0
                self.hover_progress.emit(0.0)
                cooldown = self.POST_ACTION_COOLDOWN
                continue

            # Run through the processing pipeline (use smoothed axes)
            nx, ny, direction = self.processor.process(self._sx, self._sy)

            if direction:
                self.button_pressed.emit(direction, False)
                cooldown    = self.COOLDOWN_FRAMES
                hover_timer = 0
                self.hover_progress.emit(0.0)
            # C3 fix: hover-to-launch REMOVED. Squeeze (button 1) is select
            # now; the old stillness-timer fired phantom 'action' events that
            # nothing consumed but still froze navigation for 2 s in a loop
            # whenever a patient simply rested their hand.

    def stop(self):
        self.running = False
        self.wait()
        pygame.quit()
