"""
Quick axis probe — plug in the controller and run:
  python probe_axes.py

Move the controller through each movement and note which axis number responds.
Press Ctrl+C when done.
"""
import pygame, time, os

pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    print("No joystick found. Plug in the controller and try again.")
    raise SystemExit

j = pygame.joystick.Joystick(0)
j.init()
print(f"Controller: {j.get_name()}  |  Axes: {j.get_numaxes()}\n")
print(f"{'AXIS':<6} " + "  ".join(f"  ax{i:<3}" for i in range(j.get_numaxes())))
print("-" * (6 + 8 * j.get_numaxes()))

try:
    while True:
        pygame.event.pump()
        vals = [j.get_axis(i) for i in range(j.get_numaxes())]
        bars = ""
        for v in vals:
            filled = int((v + 1) / 2 * 8)  # map -1..1 to 0..8
            bar = "[" + "#" * filled + " " * (8 - filled) + "]"
            bars += f" {bar}"
        print(f"\r{bars}  {[f'{v:+.2f}' for v in vals]}", end="", flush=True)
        time.sleep(0.05)
except KeyboardInterrupt:
    print("\nDone.")
