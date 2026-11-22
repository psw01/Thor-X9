"""Host-side button actions: keys, media keys, macros, programs.

The firmware has no "send key X" function and no macro storage, so (like
the vendor app) buttons set to the `host` function are handled here: the
mouse reports the press, and we tell the mouse which keyboard / mouse /
consumer reports to emit (commands 07 15 / 07 16 / 07 17).
"""

from __future__ import annotations

import shlex
import subprocess
import threading
import time
from typing import Dict, List, Optional, Union

from . import protocol as P
from .keys import char_keys, combo

MIN_DELAY_MS = 15  # the vendor player never waits less than this between events
MOUSE_BITS = {"left": 1, "right": 2, "middle": 4}


class Injector:
    """Tracks what the mouse is currently 'holding' and sends the reports."""

    def __init__(self, mouse):
        self.m = mouse
        self.lock = threading.Lock()
        self.keys: List[int] = []
        self.buttons = 0

    def _keys(self):
        self.m.send(P.inject_keys(self.keys[:6]))

    def key_down(self, codes):
        with self.lock:
            for c in codes:
                if c not in self.keys:
                    self.keys.append(c)
            self._keys()

    def key_up(self, codes):
        with self.lock:
            self.keys = [k for k in self.keys if k not in codes]
            self._keys()

    def mouse(self, bit, down):
        with self.lock:
            self.buttons = self.buttons | bit if down else self.buttons & ~bit
            self.m.send(P.inject_mouse(self.buttons))

    def consumer(self, usage):
        with self.lock:
            self.m.send(P.inject_consumer(usage))

    def release_all(self):
        with self.lock:
            self.keys, self.buttons = [], 0
            self.m.send(P.inject_keys())
            self.m.send(P.inject_mouse(0))


def _sleep(ms, stop: Optional[threading.Event] = None):
    ms = max(float(ms), MIN_DELAY_MS) / 1000
    if stop:
        stop.wait(ms)
    else:
        time.sleep(ms)


def parse_macro(steps: List[Union[str, list]]) -> List[tuple]:
    """Validate and compile macro steps.

    tap KEYS | down KEYS | up KEYS     KEYS = ctrl+c, f13, 0x68 ...
    wait MS
    type TEXT                          US layout ASCII
    click BTN | mdown BTN | mup BTN    BTN = left / right / middle
    consumer NAME                      vol_up, mute, play_pause ...
    """
    out = []
    for s in steps:
        if isinstance(s, list):  # legacy [[keys], delay_ms]
            out.append(("tap", combo(s[0]), s[1] if len(s) > 1 else 20))
            continue
        op, _, arg = str(s).strip().partition(" ")
        op, arg = op.lower(), arg.strip()
        if op in ("tap", "down", "up"):
            out.append((op, combo(arg), None))
        elif op == "wait":
            out.append(("wait", float(arg), None))
        elif op == "type":
            for ch in arg:
                char_keys(ch)
            out.append(("type", arg, None))
        elif op in ("click", "mdown", "mup"):
            if arg not in MOUSE_BITS:
                raise ValueError(f"mouse button must be one of {list(MOUSE_BITS)}")
            out.append((op, MOUSE_BITS[arg], None))
        elif op == "consumer":
            out.append(("consumer", P.CONSUMER[arg] if arg in P.CONSUMER else int(arg, 0), None))
        else:
            raise ValueError(f"unknown macro step {s!r}")
    return out


def play(inj: Injector, steps, stop: Optional[threading.Event] = None, gap_ms=20):
    for op, a, delay in steps:
        if stop and stop.is_set():
            return
        if op == "tap":
            inj.key_down(a)
            _sleep(gap_ms, stop)
            inj.key_up(a)
            _sleep(delay if delay is not None else gap_ms, stop)
        elif op == "down":
            inj.key_down(a)
            _sleep(gap_ms, stop)
        elif op == "up":
            inj.key_up(a)
            _sleep(gap_ms, stop)
        elif op == "wait":
            _sleep(a, stop)
        elif op == "type":
            for ch in a:
                code, shift = char_keys(ch)
                keys = [0xE1, code] if shift else [code]
                inj.key_down(keys)
                _sleep(gap_ms, stop)
                inj.key_up(keys)
                _sleep(gap_ms, stop)
        elif op == "click":
            inj.mouse(a, True)
            _sleep(gap_ms, stop)
            inj.mouse(a, False)
            _sleep(gap_ms, stop)
        elif op in ("mdown", "mup"):
            inj.mouse(a, op == "mdown")
            _sleep(gap_ms, stop)
        elif op == "consumer":
            inj.consumer(a)
            _sleep(gap_ms, stop)


class Action:
    """One button's behaviour. Built from the JSON config."""

    def __init__(self, spec, macros: Dict[str, list]):
        if isinstance(spec, str):  # "f13" / "ctrl+c" shorthand = held key
            spec = {"key": spec}
        self.spec = spec
        self.hold = combo(spec["key"]) if "key" in spec else None
        self.tap = combo(spec["keys"]) if "keys" in spec else None
        self.hold_ms = spec.get("hold_ms", 20)
        c = spec.get("consumer")
        self.consumer = None if c is None else (P.CONSUMER[c] if isinstance(c, str) else int(c))
        m = spec.get("macro", spec.get("sequence"))
        if isinstance(m, str):
            if m not in macros:
                raise ValueError(f"macro {m!r} not defined under \"macros\"")
            m = macros[m]
        self.macro = parse_macro(m) if m is not None else None
        self.repeat = spec.get("repeat", 1)  # N, "while_held" or "toggle"
        if not (isinstance(self.repeat, int) or self.repeat in ("while_held", "toggle")):
            raise ValueError("repeat must be a number, 'while_held' or 'toggle'")
        self.gap_ms = spec.get("gap_ms", 20)
        self.run = spec.get("run")
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def _macro_loop(self, inj):
        n = 0
        while not self._stop.is_set():
            play(inj, self.macro, self._stop, self.gap_ms)
            n += 1
            if isinstance(self.repeat, int) and n >= self.repeat:
                break
        if self._stop.is_set():
            inj.release_all()  # don't leave keys stuck when interrupted

    def _start_macro(self, inj):
        self._stop.clear()
        self._thread = threading.Thread(target=self._macro_loop, args=(inj,), daemon=True)
        self._thread.start()

    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def press(self, inj: Injector):
        if self.hold:
            inj.key_down(self.hold)
        if self.tap:
            inj.key_down(self.tap)
            _sleep(self.hold_ms)
            inj.key_up(self.tap)
        if self.consumer is not None:
            inj.consumer(self.consumer)
        if self.macro is not None:
            if self.repeat == "toggle" and self.running():
                self._stop.set()
            elif not self.running():
                self._start_macro(inj)
        if self.run:
            cmd = self.run
            subprocess.Popen(cmd if isinstance(cmd, list) else shlex.split(cmd), start_new_session=True)

    def release(self, inj: Injector):
        if self.hold:
            inj.key_up(self.hold)
        if self.macro is not None and self.repeat == "while_held":
            self._stop.set()


def load_actions(cfg: dict) -> Dict[str, Action]:
    macros = cfg.get("macros", {})
    for name, m in macros.items():
        parse_macro(m)  # validate early
    out = {}
    for button, spec in cfg.items():
        if button == "macros":
            continue
        if button not in P.BUTTONS:
            raise ValueError(f"unknown button {button!r}; one of {list(P.BUTTONS)}")
        out[button] = Action(spec, macros)
    return out
