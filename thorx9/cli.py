"""Command line interface: `thorx9 --help`."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time

from . import protocol as P
from .device import Mouse, find_hidraw

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


def open_mouse(a) -> Mouse:
    return Mouse(a.device, a.report_len, a.dry_run, a.verbose)


# --- commands ------------------------------------------------------------

def cmd_list(a):
    nodes = find_hidraw()
    if not nodes:
        print("no Thor X9 hidraw nodes found (VID 18f8, PID 1086/0fc0)")
        return 1
    for n in nodes:
        pages = ",".join(f"{x:04x}" for x in n.info.top_pages)
        feat = {f"{k:#04x}": v for k, v in n.info.feature.items()}
        inp = {f"{k:#04x}": v for k, v in n.info.input.items()}
        ok = os.access(n.path, os.R_OK | os.W_OK)
        print(f"{n.path}  {n.vid:04x}:{n.pid:04x}  usage pages [{pages}]  "
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


def _keys(spec):
    return [int(k, 0) if isinstance(k, str) else int(k) for k in spec]


def run_action(m: Mouse, action: dict):
    """Host-side button actions, same mechanisms as the vendor app."""
    if "consumer" in action:
        u = action["consumer"]
        m.send(P.inject_consumer(P.CONSUMER[u] if isinstance(u, str) else int(u)))
    if "keys" in action:  # HID usage ids pressed together, then released
        m.send(P.inject_keys(_keys(action["keys"])))
        time.sleep(action.get("hold_ms", 20) / 1000)
        m.send(P.inject_keys())
    if "sequence" in action:  # [[usages...], delay_ms] steps
        for step in action["sequence"]:
            keys, delay = step if len(step) == 2 else (step[0], 20)
            m.send(P.inject_keys(_keys(keys)))
            time.sleep(max(delay, 15) / 1000)
        m.send(P.inject_keys())
    if "run" in action:
        cmd = action["run"]
        subprocess.Popen(cmd if isinstance(cmd, list) else shlex.split(cmd),
                         start_new_session=True)


def cmd_listen(a):
    actions = {}
    if a.actions:
        with open(a.actions) as f:
            actions = json.load(f)
    print("listening for host-handled buttons (set a button's function to 'host'); Ctrl-C to stop",
          file=sys.stderr)
    with open_mouse(a) as m:
        try:
            for ev in m.events():
                state = f"pressed (dpi slot {ev.dpi_slot})" if ev.pressed else "released"
                print(f"{ev.name} (hw id {ev.hw_id}) {state}", flush=True)
                if ev.pressed and ev.name in actions:
                    run_action(m, actions[ev.name])
        except KeyboardInterrupt:
            pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="thorx9", description="Configure the FANTECH Thor X9 mouse.")
    ap.add_argument("--device", help="hidraw node to use (default: auto-detect)")
    ap.add_argument("--report-len", type=int, help="override feature report length")
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
    sp.set_defaults(fn=cmd_apply)

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

    sp = sub.add_parser("listen", help="print host-button events and optionally run actions")
    sp.add_argument("--actions", help="JSON mapping button name -> action")
    sp.set_defaults(fn=cmd_listen)

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
