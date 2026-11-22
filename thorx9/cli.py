"""Command line interface: `thorx9 --help`."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import protocol as P
from .actions import Injector, load_actions
from .keys import KEYS
from .device import ANY_DEVICE_WARNING, Match, Mouse, find_hidraw

CONFIG_PATH = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                           "thorx9", "profile.json")


def _int(s: str) -> int:
    return int(s, 0)


def load_profile(path):
    path = path or (CONFIG_PATH if os.path.exists(CONFIG_PATH) else None)
    if not path:
        return P.Profile()
    with open(path) as f:
        return P.Profile.from_dict(json.load(f))


def save_profile(p: P.Profile, path):
    path = path or CONFIG_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(p.to_dict(), f, indent=2)
        f.write("\n")
    print(f"saved {path}", file=sys.stderr)


def apply_overrides(p: P.Profile, a) -> P.Profile:
    if a.dpi:
        vals = [int(x) for x in a.dpi.split(",")]
        if len(vals) != 6:
            raise SystemExit("--dpi needs 6 comma separated values")
        for lvl, v in zip(p.dpi_levels, vals):
            P.dpi_to_code(v)
            lvl.dpi = v
    if a.dpi_enable:
        if len(a.dpi_enable) != 6 or set(a.dpi_enable) - {"0", "1"}:
            raise SystemExit("--dpi-enable takes 6 digits like 111100")
        for lvl, c in zip(p.dpi_levels, a.dpi_enable):
            lvl.enabled = c == "1"
    if a.dpi_colors:
        cols = a.dpi_colors.split(",")
        if len(cols) != 6:
            raise SystemExit("--dpi-colors needs 6 colours")
        for lvl, c in zip(p.dpi_levels, cols):
            P._parse_color(c)
            lvl.color = c
    if a.active is not None:
        p.active_dpi = a.active
    for spec in a.button or []:
        name, _, fn = spec.partition("=")
        if name not in P.BUTTONS:
            raise SystemExit(f"unknown button {name!r}; one of {list(P.BUTTONS)}")
        if fn not in P.FUNCTIONS:
            try:
                fn = int(fn, 0)
            except ValueError:
                raise SystemExit(f"unknown function {fn!r}; one of {list(P.FUNCTIONS)}")
        p.buttons[name] = fn
    if a.led:
        p.led_mode = a.led
    if a.led_seconds:
        p.led_cycle_seconds = a.led_seconds
    if a.led_mask is not None:
        p.led_cycle_mask = a.led_mask
    if a.wheel:
        p.wheel_volume = a.wheel == "volume"
    if a.fire_ms is not None:
        p.fire_interval_ms = a.fire_ms
    return p


_warned = False


def device_match(a) -> Match:
    global _warned
    m = Match.parse(a.any_device, a.usb_id)
    if (not m.is_thor or (a.device and not a.dry_run and not _is_thor_path(a.device))) and not _warned:
        print(ANY_DEVICE_WARNING, file=sys.stderr)
        _warned = True
    return m


def _is_thor_path(path) -> bool:
    return any(n.path == path for n in find_hidraw())


def open_mouse(a) -> Mouse:
    return Mouse(a.device, a.report_len, a.dry_run, a.verbose, device_match(a))


# --- commands ------------------------------------------------------------

def cmd_list(a):
    match = device_match(a)
    nodes = find_hidraw(match)
    if not nodes:
        print("no Thor X9 hidraw nodes found (VID 18f8, PID 1086/0fc0)" if match.is_thor
              else "no matching hidraw nodes found")
        return 1
    for n in nodes:
        pages = ",".join(f"{x:04x}" for x in n.info.top_pages)
        feat = {f"{k:#04x}": v for k, v in n.info.feature.items()}
        inp = {f"{k:#04x}": v for k, v in n.info.input.items()}
        ok = os.access(n.path, os.R_OK | os.W_OK)
        print(f"{n.path}  {n.vid:04x}:{n.pid:04x}  {n.name}  usage pages [{pages}]  "
              f"feature {feat}  input {inp}  {'rw' if ok else 'NO ACCESS (see udev/)'}")
    return 0


def cmd_show(a):
    p = apply_overrides(load_profile(a.profile), a)
    print(json.dumps(p.to_dict(), indent=2))
    for pkt in p.packets(a.report_len or P.DEFAULT_REPORT_LEN):
        print(pkt.hex(" "))
    return 0


def cmd_apply(a):
    p = apply_overrides(load_profile(a.profile), a)
    if not p.has_left_click() and not a.force:
        raise SystemExit("refusing: no button would be left click, so you couldn't click to undo it.\n"
                         "(The vendor app enforces the same rule.) Use --force if you really mean it.")
    pkts = p.packets(P.DEFAULT_REPORT_LEN)
    with open_mouse(a) as m:
        m.send_all(pkts)
    if a.save:
        save_profile(p, a.profile)
    print(f"applied {len(pkts)} reports", file=sys.stderr)
    return 0


def cmd_import_ini(a):
    raw = open(a.ini, "rb").read()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("latin-1")
    p = P.profile_from_vendor_ini(text, a.section)
    if a.output == "-":
        print(json.dumps(p.to_dict(), indent=2))
    else:
        save_profile(p, a.output)
    return 0


def cmd_raw(a):
    data = bytes(int(x, 16) for x in a.bytes)
    with open_mouse(a) as m:
        m.send(data)
    return 0


def cmd_detach(a):
    with open_mouse(a) as m:
        m.send(P.host_detach())
    return 0


def cmd_listen(a):
    cfg = {}
    if a.actions:
        with open(a.actions) as f:
            cfg = json.load(f)
    for spec in a.map or []:
        name, _, act = spec.partition("=")
        cfg[name] = act
    acts = load_actions(cfg)

    p = load_profile(a.profile)
    not_host = [b for b in acts if p.buttons.get(b) not in ("host", 0)]
    if not_host and a.set_host:
        for b in not_host:
            p.buttons[b] = "host"
        if not p.has_left_click():
            raise SystemExit("refusing: that would leave no left-click button")
        with open_mouse(a) as m:
            m.send_all(p.packets())
        if not a.dry_run:
            save_profile(p, a.profile)
        print(f"set {', '.join(not_host)} to 'host' and saved the profile", file=sys.stderr)
    elif not_host:
        print(f"note: {', '.join(not_host)} not set to 'host' in your saved profile, so the mouse "
              f"won't report them. Add --set-host, or run: thorx9 apply "
              + " ".join(f"--button {b}=host" for b in not_host) + " --save", file=sys.stderr)

    print("listening for host-handled buttons; Ctrl-C to stop", file=sys.stderr)
    with open_mouse(a) as m:
        inj = Injector(m)
        try:
            for ev in m.events():
                if a.verbose or not acts:
                    state = f"pressed (dpi slot {ev.dpi_slot})" if ev.pressed else "released"
                    print(f"{ev.name} (hw id {ev.hw_id}) {state}", flush=True)
                act = acts.get(ev.name)
                if act:
                    (act.press if ev.pressed else act.release)(inj)
        except KeyboardInterrupt:
            pass
        finally:
            for act in acts.values():
                act._stop.set()
            if not a.dry_run:
                inj.release_all()
    return 0


def cmd_keys(a):
    by_code = {}
    for k, v in KEYS.items():
        by_code.setdefault(v, []).append(k)
    for code in sorted(by_code):
        print(f"{code:#04x}  {' / '.join(by_code[code])}")
    print("\nmedia (consumer): " + ", ".join(P.CONSUMER))
    return 0


EXPLORE_DEFAULTS = {"dpi": (0x0, 0xF), "led": (0x80, 0xBF), "func": (0x00, 0x1F)}


def explore_steps(what, p: P.Profile, start, end, button):
    """Yield (value, packet, note). Only parameters of known commands are varied."""
    known_dpi = dict(zip(P.DPI_CODES, P.DPI_STEPS))
    known_fn = {v: k for k, v in P.FUNCTIONS.items()}
    known_led = {0x86: "static", 0x87: "off"}
    known_led.update({0x80 | s: f"fixed, {6 - s}s" for s in range(6)})
    known_led.update({0x90 | s: f"cyclic, {6 - s}s" for s in range(6)})
    mask = sum(1 << i for i, l in enumerate(p.dpi_levels) if l.enabled) | 1
    for v in range(start, end + 1):
        if what == "dpi":
            yield v, P.dpi_slot(0, v, 0, mask), f"{known_dpi[v]} DPI (known)" if v in known_dpi else "UNKNOWN"
        elif what == "led":
            yield v, P._pkt(P.CMD_LED, p.led_cycle_mask, v), known_led.get(v, "UNKNOWN")
        else:
            yield v, P.button(P.BUTTONS[button], v), known_fn.get(v, "UNKNOWN")


def cmd_explore(a):
    p = load_profile(a.profile)
    start, end = EXPLORE_DEFAULTS[a.what]
    start = start if a.start is None else a.start
    end = end if a.end is None else a.end
    if a.what == "func" and a.button == "left":
        raise SystemExit("pick a button other than left for this")
    hint = {"dpi": "DPI slot 1 is made active; move the mouse and compare speed.",
            "led": "Watch the LEDs.",
            "func": f"Press the '{a.button}' button and watch what happens."}[a.what]
    print(f"{hint}\nEnter = next, b = back, n <note> = note it down, q = quit. "
          "Your profile is restored at the end.", file=sys.stderr)
    steps = list(explore_steps(a.what, p, start, end, a.button))
    notes = {}
    with open_mouse(a) as m:
        try:
            if a.what == "dpi":  # put slot 1 active so the change is felt immediately
                m.send_all(P.Profile.from_dict({**p.to_dict(), "dpi": {**p.to_dict()["dpi"], "active": 0}}).packets())
            i = 0
            while 0 <= i < len(steps):
                v, pkt, note = steps[i]
                m.send(pkt)
                for ev in m.events(timeout=0):  # drop stale events
                    pass
                ans = input(f"[{v:#04x}] {note:<20} sent {pkt[:5].hex(' ')} > ").strip()
                for ev in m.events(timeout=0):
                    print(f"    mouse reported: {ev.name} {'pressed' if ev.pressed else 'released'}")
                if ans == "q":
                    break
                if ans == "b":
                    i = max(0, i - 1)
                    continue
                if ans.startswith("n"):
                    notes[v] = ans[1:].strip()
                i += 1
        except (KeyboardInterrupt, EOFError):
            print()
        finally:
            m.send_all(p.packets())
            print("profile restored", file=sys.stderr)
    for v, n in notes.items():
        print(f"{a.what} {v:#04x}: {n}")
    if notes:
        print("Please share these notes in an issue!", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="thorx9", description="Configure the FANTECH Thor X9 mouse.")
    ap.add_argument("--device", help="hidraw node to use (default: auto-detect)")
    ap.add_argument("--report-len", type=int, help="override feature report length")
    ap.add_argument("--any-device", action="store_true",
                    help="allow any HID device, not just the Thor X9 (MAY NOT WORK, use at your own risk)")
    ap.add_argument("--usb-id", metavar="VID:PID",
                    help="target a specific device, e.g. 18f8:1086 (implies --any-device)")
    ap.add_argument("-n", "--dry-run", action="store_true", help="print reports, don't send")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list detected devices").set_defaults(fn=cmd_list)

    def profile_args(sp):
        sp.add_argument("-p", "--profile", help=f"profile JSON (default {CONFIG_PATH} or built-in)")
        sp.add_argument("--dpi", help="6 comma separated DPI values, e.g. 800,1200,1600,2400,3200,4800")
        sp.add_argument("--dpi-enable", help="6 digits, e.g. 111100")
        sp.add_argument("--dpi-colors", help="6 colours, e.g. '#f00,#0f0,#00f,#ff0,#0ff,#fff'")
        sp.add_argument("--active", type=int, help="active DPI slot 0..5")
        sp.add_argument("--button", action="append", metavar="BUTTON=FUNCTION",
                        help=f"buttons: {', '.join(P.BUTTONS)}; functions: {', '.join(P.FUNCTIONS)}")
        sp.add_argument("--led", choices=list(P.LED_MODES))
        sp.add_argument("--led-seconds", type=int, choices=range(1, 7), help="cycle period 1..6 s")
        sp.add_argument("--led-mask", type=_int, help="7-bit mask of colours in the cycle")
        sp.add_argument("--wheel", choices=["scroll", "volume"])
        sp.add_argument("--fire-ms", type=int, help="rapid-fire interval")

    sp = sub.add_parser("apply", help="send a full configuration")
    profile_args(sp)
    sp.add_argument("--save", action="store_true", help="store the result as the default profile")
    sp.add_argument("--force", action="store_true", help="allow a mapping without any left click")
    sp.set_defaults(fn=cmd_apply)

    sp = sub.add_parser("explore", help="interactively test values the vendor app never uses")
    sp.add_argument("what", choices=["dpi", "led", "func"])
    sp.add_argument("-p", "--profile", help="profile to restore afterwards (default: your saved one)")
    sp.add_argument("--button", default="dpi_minus", choices=list(P.BUTTONS),
                    help="button to test functions on (func; default dpi_minus)")
    sp.add_argument("--from", dest="start", type=_int, help="first value")
    sp.add_argument("--to", dest="end", type=_int, help="last value")
    sp.set_defaults(fn=cmd_explore)

    sp = sub.add_parser("show", help="print profile and the reports it produces")
    profile_args(sp)
    sp.set_defaults(fn=cmd_show)

    sp = sub.add_parser("import-ini", help="convert the vendor skins/config/config.ini")
    sp.add_argument("ini")
    sp.add_argument("--section", default="Config1")
    sp.add_argument("-o", "--output", default="-")
    sp.set_defaults(fn=cmd_import_ini)

    sp = sub.add_parser("raw", help="send a raw feature report, e.g. `raw 07 13 7f 86`")
    sp.add_argument("bytes", nargs="+")
    sp.set_defaults(fn=cmd_raw)

    sp = sub.add_parser("listen", help="run keys / macros / media keys for buttons set to 'host'")
    sp.add_argument("--actions", help="JSON file: button name -> action (see examples/actions.json)")
    sp.add_argument("--map", action="append", metavar="BUTTON=KEYS",
                    help="quick key mapping, held while the button is held, e.g. dpi_minus=f13 or back=ctrl+c")
    sp.add_argument("--set-host", action="store_true",
                    help="switch the mapped buttons to 'host' on the mouse (and save the profile) first")
    sp.add_argument("-p", "--profile", help="profile file (default: your saved one)")
    sp.set_defaults(fn=cmd_listen)

    sub.add_parser("keys", help="list key names for --map / macros").set_defaults(fn=cmd_keys)

    sub.add_parser("detach", help="send 07 20 (vendor app does this on exit)").set_defaults(fn=cmd_detach)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a) or 0
    except PermissionError as e:
        print(f"{e}\nInstall udev/70-thorx9.rules (see README) or run with sudo.", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
