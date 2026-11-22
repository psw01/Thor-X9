"""Thor X9 wire protocol: pure packet builders, no I/O.

Everything here was recovered by static analysis of the vendor
application "Gaming Mouse 2.0.exe" (see docs/PROTOCOL.md for the
addresses each constant came from).

All configuration is sent as HID *feature* reports with report ID 0x07
on the vendor-defined collection (usage page 0xFF01, usage 0x01).
The device reports host-handled button presses as *input* reports with
report ID 0x06 on the collection with usage page 0xFF00.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

VENDOR_ID = 0x18F8
PRODUCT_IDS = (0x1086, 0x0FC0)

USAGE_PAGE_OUT = 0xFF01  # feature reports (host -> mouse)
USAGE_PAGE_IN = 0xFF00   # input reports (mouse -> host)

REPORT_ID_CMD = 0x07
REPORT_ID_EVENT = 0x06
DEFAULT_REPORT_LEN = 8   # incl. report ID; real value is read from the HID descriptor

# Command bytes (2nd byte of a 0x07 feature report)
CMD_DPI_SLOT = 0x09
CMD_BUTTON = 0x10
CMD_WHEEL = 0x11
CMD_FIRE = 0x12
CMD_LED = 0x13
CMD_DPI_COLOR = 0x14
CMD_INJECT_KEYS = 0x15
CMD_INJECT_MOUSE = 0x16
CMD_INJECT_CONSUMER = 0x17
CMD_HOST_DETACH = 0x20

# --- buttons -------------------------------------------------------------

# Physical buttons -> hardware button id (table at VA 0x5bb018).
# Names follow the vendor's factory default function for that slot.
BUTTONS: Dict[str, int] = {
    "left": 1,
    "middle": 2,
    "right": 3,
    "forward": 5,
    "back": 4,
    "dpi_plus": 8,
    "dpi_minus": 6,
}
BUTTON_ORDER = ["left", "middle", "right", "forward", "back", "dpi_plus", "dpi_minus"]

# Hardware button function codes (see Apply routine at VA 0x408630).
FUNCTIONS: Dict[str, int] = {
    "host": 0x00,         # not handled in firmware: mouse emits input report 06 F0+id
    "left": 0x01,
    "middle": 0x02,
    "right": 0x03,
    "back": 0x04,
    "forward": 0x05,
    "dpi_loop": 0x06,
    "show_desktop": 0x07,
    "double_click": 0x08,
    "fire": 0x09,         # rapid fire, interval set with CMD_FIRE
    "off": 0x0A,
    "dpi_up": 0x0B,
    "dpi_down": 0x0C,
}

DEFAULT_BUTTONS = {
    "left": "left", "middle": "middle", "right": "right",
    "forward": "forward", "back": "back",
    "dpi_plus": "dpi_up", "dpi_minus": "dpi_down",
}

# --- DPI -----------------------------------------------------------------

# Slider positions (painted on the vendor skin) -> device code (table at VA 0x5bb044).
DPI_STEPS: List[int] = [200, 400, 600, 800, 1000, 1200, 1600, 2000, 2400, 3200, 4000, 4800]
DPI_CODES: List[int] = [0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x9, 0xB, 0xD, 0xE, 0xF]
NUM_DPI_SLOTS = 6

# --- LED -----------------------------------------------------------------

LED_MODES = {"fixed": 0, "cyclic": 1, "static": 2, "off": 3}
NUM_CYCLE_COLORS = 7

# --- consumer (media) usages used by the vendor app (VA 0x4067e0) ---------

CONSUMER: Dict[str, int] = {
    "browser": 0x223, "player": 0x183, "mail": 0x18A,
    "vol_up": 0xE9, "vol_down": 0xEA, "prev": 0xB6, "next": 0xB5,
    "mute": 0xE2, "play_pause": 0xCD, "calculator": 0x192, "stop": 0xB7,
}


def _pkt(*body: int, length: int = DEFAULT_REPORT_LEN) -> bytes:
    data = bytes([REPORT_ID_CMD, *body])
    if len(data) > length:
        raise ValueError(f"packet {data.hex()} longer than report length {length}")
    return data.ljust(length, b"\x00")


def _nibble(name: str, v: int) -> int:
    if not 0 <= v <= 15:
        raise ValueError(f"{name} must be 0..15, got {v}")
    return v


def dpi_to_code(dpi: int) -> int:
    try:
        return DPI_CODES[DPI_STEPS.index(dpi)]
    except ValueError:
        raise ValueError(f"unsupported DPI {dpi}; choose one of {DPI_STEPS}") from None


# --- packet builders -----------------------------------------------------

def button(hw_id: int, function: int, length: int = DEFAULT_REPORT_LEN) -> bytes:
    """07 10 <hw button id> <function code>"""
    return _pkt(CMD_BUTTON, hw_id, function, length=length)


def wheel(volume: bool, length: int = DEFAULT_REPORT_LEN) -> bytes:
    """07 11 <0=scroll, 1=volume> 00"""
    return _pkt(CMD_WHEEL, 1 if volume else 0, 0, length=length)


def led(mode: str, cycle_seconds: int = 4, cycle_mask: int = 0x7F,
        length: int = DEFAULT_REPORT_LEN) -> bytes:
    """07 13 <7-bit cycle colour mask> <mode byte>

    mode byte: fixed  -> 0x80 | speed
               cyclic -> 0x90 | speed
               static -> 0x86
               off    -> 0x87
    speed = 6 - cycle_seconds (UI "1s" -> 5 ... "6s" -> 0)
    """
    if mode not in LED_MODES:
        raise ValueError(f"LED mode must be one of {list(LED_MODES)}")
    if not 1 <= cycle_seconds <= 6:
        raise ValueError("cycle_seconds must be 1..6")
    if not 0 <= cycle_mask <= 0x7F:
        raise ValueError("cycle_mask must be 0..0x7f")
    speed = 6 - cycle_seconds
    m = LED_MODES[mode]
    if m == 2:
        b = 0x86
    elif m == 3:
        b = 0x87
    else:
        b = ((8 + m) << 4) | speed
    return _pkt(CMD_LED, cycle_mask, b, length=length)


def dpi_slot(slot: int, dpi_code: int, active_slot: int, enabled_mask: int,
             length: int = DEFAULT_REPORT_LEN) -> bytes:
    """07 09 <0x40|active> <(code<<4)|8|slot> <6-bit enabled mask>"""
    if not 0 <= slot < NUM_DPI_SLOTS or not 0 <= active_slot < NUM_DPI_SLOTS:
        raise ValueError("slot index must be 0..5")
    return _pkt(CMD_DPI_SLOT, 0x40 | active_slot,
                ((_nibble("dpi code", dpi_code) << 4) | 8 | slot) & 0xFF,
                enabled_mask & 0x3F, length=length)


def dpi_color(slot: int, r: int, g: int, b: int, length: int = DEFAULT_REPORT_LEN) -> bytes:
    """07 14 <(slot<<5)|G> <(R<<4)|B>   (4 bits per channel)"""
    if not 0 <= slot < NUM_DPI_SLOTS:
        raise ValueError("slot index must be 0..5")
    return _pkt(CMD_DPI_COLOR, (slot << 5) | _nibble("g", g),
                (_nibble("r", r) << 4) | _nibble("b", b), length=length)


def fire_interval(ms: int, length: int = DEFAULT_REPORT_LEN) -> bytes:
    """07 12 <hi> <lo> 00 00 00 00, value = FIRE_TIME / 8 (big endian)"""
    v = int(ms) // 8
    if not 0 <= v <= 0xFFFF:
        raise ValueError("fire interval out of range")
    return _pkt(CMD_FIRE, v >> 8, v & 0xFF, 0, 0, 0, 0, length=length)


def inject_keys(codes: Sequence[int] = (), length: int = DEFAULT_REPORT_LEN) -> bytes:
    """07 15 k1..k6 - make the mouse emit a keyboard report (empty = release all)."""
    codes = list(codes)
    if len(codes) > 6:
        raise ValueError("at most 6 simultaneous keys")
    return _pkt(CMD_INJECT_KEYS, *(codes + [0] * (6 - len(codes))), length=length)


def inject_mouse(pressed_mask: int, length: int = DEFAULT_REPORT_LEN) -> bytes:
    """07 16 00 <active-low button mask> (bit0..2, 1 = released)."""
    return _pkt(CMD_INJECT_MOUSE, 0, (~pressed_mask) & 0xFF, length=length)


def inject_consumer(usage: int, length: int = DEFAULT_REPORT_LEN) -> bytes:
    """07 17 <usage hi> <usage lo>"""
    return _pkt(CMD_INJECT_CONSUMER, (usage >> 8) & 0xFF, usage & 0xFF, length=length)


def host_detach(length: int = DEFAULT_REPORT_LEN) -> bytes:
    """07 20 - sent by the vendor app on exit."""
    return _pkt(CMD_HOST_DETACH, length=length)


# --- input reports -------------------------------------------------------

@dataclass
class ButtonEvent:
    hw_id: int
    pressed: bool
    dpi_slot: Optional[int]  # current DPI slot reported on press

    @property
    def name(self) -> str:
        for k, v in BUTTONS.items():
            if v == self.hw_id:
                return k
        return f"button{self.hw_id}"


def parse_event(report: bytes) -> Optional[ButtonEvent]:
    """Parse input report `06 <F0+id> <state>` (state 0x80 = released)."""
    if len(report) < 3 or report[0] != REPORT_ID_EVENT or report[1] <= 0xF0:
        return None
    released = report[2] == 0x80
    return ButtonEvent(report[1] - 0xF0, not released, None if released else report[2])


# --- full profile --------------------------------------------------------

def _parse_color(c) -> Tuple[int, int, int]:
    if isinstance(c, (list, tuple)):
        r, g, b = c
        return int(r), int(g), int(b)
    s = str(c).lstrip("#")
    if len(s) == 3:
        return int(s[0], 16), int(s[1], 16), int(s[2], 16)
    if len(s) == 6:
        return int(s[0:2], 16) >> 4, int(s[2:4], 16) >> 4, int(s[4:6], 16) >> 4
    raise ValueError(f"bad colour {c!r}; use '#rgb', '#rrggbb' or [r,g,b] with 0..15")


@dataclass
class DpiLevel:
    dpi: int
    enabled: bool = True
    color: object = "#fff"


@dataclass
class Profile:
    buttons: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_BUTTONS))
    dpi_levels: List[DpiLevel] = field(default_factory=lambda: [
        DpiLevel(600, True, "#00f"), DpiLevel(1000, True, "#ff0"),
        DpiLevel(1200, True, "#0f0"), DpiLevel(2000, True, "#f0f"),
        DpiLevel(3200, True, "#0ff"), DpiLevel(4800, True, "#f00"),
    ])
    active_dpi: int = 1
    led_mode: str = "cyclic"
    led_cycle_seconds: int = 4
    led_cycle_mask: int = 0x7F
    wheel_volume: bool = False
    fire_interval_ms: int = 50

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        p = cls()
        if "buttons" in d:
            p.buttons.update(d["buttons"])
        dpi = d.get("dpi", {})
        if "levels" in dpi:
            p.dpi_levels = [DpiLevel(int(l["dpi"]), bool(l.get("enabled", True)),
                                     l.get("color", "#fff")) for l in dpi["levels"]]
        p.active_dpi = int(dpi.get("active", p.active_dpi))
        led_ = d.get("led", {})
        p.led_mode = led_.get("mode", p.led_mode)
        p.led_cycle_seconds = int(led_.get("cycle_seconds", p.led_cycle_seconds))
        p.led_cycle_mask = int(led_.get("cycle_mask", p.led_cycle_mask))
        p.wheel_volume = d.get("wheel", "scroll") == "volume"
        p.fire_interval_ms = int(d.get("fire_interval_ms", p.fire_interval_ms))
        return p

    def to_dict(self) -> dict:
        return {
            "buttons": dict(self.buttons),
            "dpi": {"active": self.active_dpi, "levels": [
                {"dpi": l.dpi, "enabled": l.enabled, "color": l.color} for l in self.dpi_levels]},
            "led": {"mode": self.led_mode, "cycle_seconds": self.led_cycle_seconds,
                    "cycle_mask": self.led_cycle_mask},
            "wheel": "volume" if self.wheel_volume else "scroll",
            "fire_interval_ms": self.fire_interval_ms,
        }

    def packets(self, length: int = DEFAULT_REPORT_LEN) -> List[bytes]:
        """Packet sequence in the same order as the vendor Apply routine."""
        if len(self.dpi_levels) != NUM_DPI_SLOTS:
            raise ValueError("exactly 6 DPI levels are required")
        if not 0 <= self.active_dpi < NUM_DPI_SLOTS:
            raise ValueError("active DPI slot must be 0..5")
        out = []
        for name in BUTTON_ORDER:
            fn = self.buttons.get(name, DEFAULT_BUTTONS[name])
            code = fn if isinstance(fn, int) else FUNCTIONS.get(fn)
            if code is None:
                raise ValueError(f"unknown function {fn!r} for {name}; one of {list(FUNCTIONS)}")
            out.append(button(BUTTONS[name], code, length))
        out.append(wheel(self.wheel_volume, length))
        out.append(led(self.led_mode, self.led_cycle_seconds, self.led_cycle_mask, length))
        mask = sum(1 << i for i, l in enumerate(self.dpi_levels) if l.enabled)
        for i, l in enumerate(self.dpi_levels):
            out.append(dpi_slot(i, dpi_to_code(l.dpi), self.active_dpi, mask, length))
            out.append(dpi_color(i, *_parse_color(l.color), length=length))
        out.append(fire_interval(self.fire_interval_ms, length))
        return out


def profile_from_vendor_ini(text: str, section: str = "Config1") -> Profile:
    """Convert a section of the vendor's skins/config/config.ini."""
    vals: Dict[str, str] = {}
    cur = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            cur = line[1:-1]
        elif cur == section and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    if not vals:
        raise ValueError(f"section [{section}] not found")
    # vendor UI function list index -> our function names (others are host-side)
    ui = {1: "left", 2: "middle", 3: "right", 4: "back", 5: "forward", 6: "dpi_loop",
          11: "show_desktop", 12: "double_click", 13: "fire", 14: "off", 15: "dpi_up", 16: "dpi_down"}
    p = Profile()
    for i, name in enumerate(BUTTON_ORDER):
        k = int(vals.get(f"K{i}", 0))
        p.buttons[name] = ui.get(k, "host")
    levels = []
    for i in range(NUM_DPI_SLOTS):
        idx = int(vals.get(f"DPI_SET{i}", 3))
        levels.append(DpiLevel(DPI_STEPS[max(0, min(idx, 11))],
                               vals.get(f"DPI_SET_EN{i}", "1") != "0",
                               [int(vals.get(f"DPI{i}_{c}", 0)) for c in "RGB"]))
    p.dpi_levels = levels
    p.active_dpi = int(vals.get("DPI_LEVEL", 0))
    p.led_mode = {v: k for k, v in LED_MODES.items()}.get(int(vals.get("LED_TYPE", 1)), "cyclic")
    p.led_cycle_seconds = 6 - int(vals.get("LED_CYC_TIME", 2))
    p.led_cycle_mask = int(vals.get("CYC_7COL_EN", 127)) & 0x7F
    p.wheel_volume = vals.get("WHEEL_STATUS", "0") != "0"
    p.fire_interval_ms = int(vals.get("FIRE_TIME", 50))
    return p
