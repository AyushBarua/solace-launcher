"""
device_link — small serial side-channel to the Solace controller.

The controller is primarily a USB HID gamepad, but the firmware also exposes
a CDC serial port and accepts single-character commands:
  'T' — re-tare: capture current pose as neutral + re-baseline the FSR.

Requires pyserial. Fails soft (returns False) if unavailable — the HID
gamepad keeps working regardless.
"""


def _find_controller_port():
    import serial.tools.list_ports
    candidates = []
    for p in serial.tools.list_ports.comports():
        vid = p.vid or 0
        desc = (p.description or "") + " " + (p.manufacturer or "")
        if vid == 0x303A:                       # Espressif USB VID
            candidates.insert(0, p.device)      # best match first
        elif "esp32" in desc.lower():
            candidates.append(p.device)
    return candidates


def _send(payload: bytes, label: str) -> bool:
    try:
        import serial
    except ImportError:
        print(f"[device_link] pyserial not installed — cannot send {label}")
        return False

    for port in _find_controller_port():
        try:
            with serial.Serial(port, 115200, timeout=0.5, write_timeout=0.5) as s:
                s.write(payload)
            print(f"[device_link] {label} sent on {port}")
            return True
        except Exception as exc:
            print(f"[device_link] {port}: {exc}")
    return False


def send_retare() -> bool:
    """Send 'T' to the controller. Returns True if a port accepted it."""
    return _send(b"T", "re-tare")


def apply_patient_limits(baseline_deg: dict | None) -> bool:
    """
    Send per-patient range limits to firmware v6 so full joystick deflection
    matches the patient's comfortable ROM (ease-of-use fix). Pass the 'deg'
    block of baseline_rom, or None to restore healthy defaults.

    Also updates core.units active limits so degree conversion stays truthful.
    Safe on v5 firmware (unknown commands are ignored) — but then games keep
    the healthy mapping, so only call set_active_limits on v6.
    """
    from core.units import FIRMWARE_LIMITS, set_active_limits, reset_active_limits

    if not baseline_deg:
        reset_active_limits()
        return _send(b"D\n", "default limits")

    # Patient's measured comfortable ROM = full deflection, floored at 10 deg
    # so a near-zero capture can't make the controller unusably twitchy.
    limits = {}
    for key in ("flexion", "extension", "pronation", "supination"):
        v = float(baseline_deg.get(key) or 0.0)
        limits[key] = max(10.0, min(90.0, v)) if v > 0 else FIRMWARE_LIMITS[key]

    cmd = (f"L {limits['flexion']:.1f} {limits['extension']:.1f} "
           f"{limits['pronation']:.1f} {limits['supination']:.1f}\n").encode()
    if _send(cmd, f"patient limits {limits}"):
        set_active_limits(limits)
        return True
    return False
