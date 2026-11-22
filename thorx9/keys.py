"""Key names -> HID keyboard usage IDs (USB HID Usage Tables, page 0x07)."""

from __future__ import annotations

from typing import List, Tuple

KEYS = {}
for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    KEYS[c] = 0x04 + i
for i, c in enumerate("1234567890"):
    KEYS[c] = 0x1E + i
for i in range(12):
    KEYS[f"f{i + 1}"] = 0x3A + i       # F1..F12
for i in range(12):
    KEYS[f"f{i + 13}"] = 0x68 + i      # F13..F24
KEYS.update({
    "enter": 0x28, "return": 0x28, "esc": 0x29, "escape": 0x29, "backspace": 0x2A,
    "tab": 0x2B, "space": 0x2C, "minus": 0x2D, "equal": 0x2E, "leftbrace": 0x2F,
    "rightbrace": 0x30, "backslash": 0x31, "semicolon": 0x33, "apostrophe": 0x34,
    "grave": 0x35, "comma": 0x36, "dot": 0x37, "slash": 0x38, "capslock": 0x39,
    "printscreen": 0x46, "sysrq": 0x46, "scrolllock": 0x47, "pause": 0x48,
    "insert": 0x49, "home": 0x4A, "pageup": 0x4B, "delete": 0x4C, "del": 0x4C,
    "end": 0x4D, "pagedown": 0x4E, "right": 0x4F, "left": 0x50, "down": 0x51,
    "up": 0x52, "numlock": 0x53, "kpslash": 0x54, "kpasterisk": 0x55,
    "kpminus": 0x56, "kpplus": 0x57, "kpenter": 0x58, "kpdot": 0x63, "menu": 0x65,
    "ctrl": 0xE0, "lctrl": 0xE0, "shift": 0xE1, "lshift": 0xE1, "alt": 0xE2,
    "lalt": 0xE2, "meta": 0xE3, "super": 0xE3, "win": 0xE3, "cmd": 0xE3,
    "rctrl": 0xE4, "rshift": 0xE5, "ralt": 0xE6, "altgr": 0xE6, "rmeta": 0xE7,
})
for i in range(1, 10):
    KEYS[f"kp{i}"] = 0x58 + i
KEYS["kp0"] = 0x62

# US layout: character -> (usage, needs shift)
_SHIFTED = dict(zip('!@#$%^&*()_+{}|:"~<>?', "1234567890") )
_SHIFTED.update({"_": "minus", "+": "equal", "{": "leftbrace", "}": "rightbrace", "|": "backslash",
                 ":": "semicolon", '"': "apostrophe", "~": "grave", "<": "comma", ">": "dot", "?": "slash"})
_PLAIN = {" ": "space", "-": "minus", "=": "equal", "[": "leftbrace", "]": "rightbrace",
          "\\": "backslash", ";": "semicolon", "'": "apostrophe", "`": "grave", ",": "comma",
          ".": "dot", "/": "slash", "\n": "enter", "\t": "tab"}


def key_code(name) -> int:
    """'f13' / 'A' / 'ctrl' / '0x68' / 104 -> usage id."""
    if isinstance(name, int):
        return name
    n = str(name).strip().lower()
    if n.startswith("0x") or n.isdigit() and len(n) > 1:
        return int(n, 0)
    if n not in KEYS:
        raise ValueError(f"unknown key {name!r}; see thorx9 keys")
    return KEYS[n]


def combo(spec) -> List[int]:
    """'ctrl+shift+f13' -> [0xE0, 0xE1, 0x68]; lists are accepted too."""
    if isinstance(spec, (list, tuple)):
        return [key_code(k) for k in spec]
    s = str(spec)
    parts = ["+"] if s == "+" else [p for p in s.split("+") if p]
    return [key_code(p) for p in parts]


def char_keys(ch: str) -> Tuple[int, bool]:
    if ch.isalpha() and ch.isascii():
        return KEYS[ch.lower()], ch.isupper()
    if ch.isdigit():
        return KEYS[ch], False
    if ch in _PLAIN:
        return KEYS[_PLAIN[ch]], False
    if ch in _SHIFTED:
        return KEYS[_SHIFTED[ch]], True
    raise ValueError(f"can't type {ch!r} (US layout ASCII only)")
