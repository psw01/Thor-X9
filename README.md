# Thor-X9: a free driver for the FANTECH Thor X9 mouse

FANTECH ships the Thor X9 with a Windows-only, admin-only configuration app.
This repository has:

* **`thorx9`**: a dependency-free Python CLI/library for Linux (macOS/Windows via `hidapi`)
* **`web/index.html`**: a WebHID page that configures the mouse from Chrome/Edge on any OS
* **[docs/PROTOCOL.md](docs/PROTOCOL.md)**: the full USB protocol, with the vendor-binary address each fact came from
* **[docs/SECURITY_ANALYSIS.md](docs/SECURITY_ANALYSIS.md)**: what the vendor app actually does (no evidence of spyware, but sloppy and over-privileged)
* **[docs/HIDDEN_FEATURES.md](docs/HIDDEN_FEATURES.md)**: leftovers, hidden functions, and untested firmware values you can probe with `thorx9 explore`
* **[docs/REVERSING.md](docs/REVERSING.md)**: how to reproduce the analysis

> 🤖 **Vibe-coded disclaimer.** This project was built with an AI coding assistant: the vendor
> app was reverse-engineered, and the code and docs were written, in a few chat sessions. A human
> reviewed it and it works on the author's mouse, but it has not been audited line by line.
> Read the code before trusting it, and expect rough edges. No warranty (see [LICENSE](LICENSE)).

> ✅ **Status: v0.1.0, first release.** The protocol was recovered by static analysis and
> confirmed working on a real Thor X9 (DPI, LEDs, button remapping). Some parts are still
> unverified on hardware: key codes for `listen`, which button `fire` clicks, and the values listed in
> [docs/HIDDEN_FEATURES.md](docs/HIDDEN_FEATURES.md). Please report what works or doesn't
> in an issue; output from `thorx9 list` is especially useful.

Device: USB `18f8:1086` (some units `18f8:0fc0`). Check with `lsusb | grep 18f8`.

## What you can control

| Feature | Supported |
|---|---|
| 6 DPI slots (200–4800), enable/disable, active slot | ✅ |
| Per-slot LED colour (4 bits per channel) | ✅ |
| LED mode: fixed / cyclic / static / off, cycle speed 1–6 s, cycle colours | ✅ |
| Remap 7 buttons: clicks, back/forward, DPI ±/loop, double click, rapid fire, show desktop, off | ✅ (in firmware) |
| Wheel as volume control | ✅ |
| Rapid-fire interval | ✅ |
| Any keyboard key (F13–F24, combos), media keys, macros, launching programs | ✅ via `thorx9 listen` (host-side, like the vendor app) |
| Polling rate | ❌ not in the protocol (vendor app never sends it) |

## Linux quick start

```bash
git clone https://github.com/psw01/Thor-X9 && cd Thor-X9
```
```bash
sudo cp udev/70-thorx9.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger
```
Then unplug and replug the mouse.
```bash
pip install --user .
```
```bash
thorx9 list
```

Without installing, `python3 -m thorx9 …` works from the repo directory.

### Examples

Preview what would be sent, without touching the device:
```bash
thorx9 --dry-run apply --dpi 400,800,1600,2400,3200,4800 --active 2
```

Set DPI, LED and colours, and save it as your default profile (`~/.config/thorx9/profile.json`):
```bash
thorx9 apply --dpi 400,800,1600,2400,3200,4800 --dpi-colors '#f00,#ff0,#0f0,#0ff,#00f,#f0f' --active 2 --led fixed --save
```

Only use three DPI slots:
```bash
thorx9 apply --dpi-enable 111000
```

Remap buttons (functions: `host left middle right back forward dpi_loop show_desktop double_click fire off dpi_up dpi_down`):
```bash
thorx9 apply --button back=fire --button forward=double_click --fire-ms 40
```

Turn the LEDs off:
```bash
thorx9 apply --led off
```

Apply a profile file (see `examples/profile.json`):
```bash
thorx9 apply -p examples/profile.json
```

Import your old Windows settings from the vendor `skins/config/config.ini`:
```bash
thorx9 import-ini config.ini --section Config1 -o ~/.config/thorx9/profile.json
```

### Any key (F13…F24, combos), media keys and macros

The firmware can only do clicks, back/forward, DPI, double click, fire, show desktop and off.
**It cannot send keyboard keys on its own, and it has no macro memory.** The vendor app handled
all of that on the PC, and so does `thorx9 listen`. The button's function is set to `host`. The
mouse reports the press, and `thorx9` tells the **mouse itself** which key to send. The key
therefore arrives from the mouse's own keyboard interface: no uinput, and it works under Wayland,
X11 and in games. `listen` has to keep running for this. A systemd user service is in
`examples/thorx9-listen.service`.

F13 on the lower DPI button, held for as long as the button is held:
```bash
thorx9 listen --map dpi_minus=f13 --set-host
```
`--set-host` switches the mapped buttons to `host` on the mouse and saves that to your profile. You only need it once.
Several at once: `--map back=ctrl+c --map forward=f14`. List every key name with `thorx9 keys`.

For anything more than single keys, use an actions file (see [`examples/actions.json`](examples/actions.json)):
```bash
thorx9 listen --actions examples/actions.json --set-host
```
```json
{
  "dpi_minus": "f13",
  "forward":   {"key": "ctrl+c"},
  "back":      {"consumer": "play_pause"},
  "dpi_plus":  {"macro": "greet", "repeat": 1},
  "macros": {
    "greet": ["type Hello from Thor X9!", "wait 100", "tap enter"]
  }
}
```

| Action | Behaviour |
|---|---|
| `"f13"` or `{"key": "ctrl+shift+f13"}` | Held down while the button is held |
| `{"keys": "ctrl+c"}` | Tapped once on press (`hold_ms`, default 20) |
| `{"consumer": "vol_up"}` | Media key: `browser player mail vol_up vol_down prev next mute play_pause calculator stop` or a number |
| `{"macro": [...] or "name", "repeat": …}` | Macro (below) |
| `{"run": "command"}` | Run a program |

**Macro steps:** `tap KEYS`, `down KEYS`, `up KEYS`, `wait MS`, `type TEXT` (US layout),
`click left|right|middle`, `mdown BTN`, `mup BTN`, `consumer NAME`.
`KEYS` are names joined with `+` (`ctrl+alt+t`, `f13`, `0x68`). Up to 6 keys can be held at once.

**Repeat modes:** these match the vendor app's options.
- a number: play that many times.
- `"while_held"`: loop while the button is held ("Run till Release").
- `"toggle"`: first press starts looping, next press stops.

Optional `"gap_ms"` (default 20) sets the delay between key events. Delays below 15 ms are raised to 15 ms, as in the vendor player.
Interrupted macros release every key, so nothing stays stuck.

`thorx9 listen -v` prints every button event, which is handy for identifying which button is which.

> The `07 15` key codes are standard HID usage IDs. That was inferred, not proven from the vendor code.
> If a key comes out wrong, please open an issue.

### What "fire" does

`fire` is the vendor's "Fire" / 連打 (rapid fire) function. While you hold a button set to `fire`,
the mouse itself clicks repeatedly, presumably left click, without needing the PC. It is the only "macro" that runs in firmware.
The speed is `--fire-ms` (`fire_interval_ms` in profiles). The vendor slider ranges from 0 to 300 ms (default 50)
and the value is sent divided by 8, so the firmware probably works in 8 ms steps (one USB frame at 125 Hz).
```bash
thorx9 apply --button forward=fire --fire-ms 40 --save
```
For other rapid-fire behaviour (right click, a key, a burst), use a macro with `"repeat": "while_held"`,
e.g. `{"macro": ["click right", "wait 30"], "repeat": "while_held"}`.

Raw experiments:
```bash
thorx9 raw 07 13 7f 86
```

Guided exploration of untested firmware values. It restores your profile afterwards; see [docs/HIDDEN_FEATURES.md](docs/HIDDEN_FEATURES.md):
```bash
thorx9 explore led --from 0x88 --to 0xbf
```

`apply` refuses a mapping where no button is left click, the same safety net as the vendor app. Pass `--force` to override.

## Other devices (experimental)

> ⚠️ **May not work.** The tools only speak the Thor X9 protocol. This is useful for rebadged
> siblings that share the same chip or firmware (other `18f8:*` mice, for example). On anything
> else it may do nothing, or may change settings in unexpected ways.

CLI: `--any-device` lifts the VID/PID check, and `--usb-id VID:PID` picks a specific device (it implies `--any-device`):
```bash
thorx9 --any-device list
```
```bash
thorx9 --usb-id 18f8:0fd0 --dry-run apply --led off
```
If several devices match, pass `--device /dev/hidrawN`. You'll still need a udev rule granting access to that device.

Web: tick **Allow any HID device** before clicking Connect, and the browser will list every HID device.
Browsers still hide protected keyboard/mouse collections, so only devices with vendor-defined collections will respond.

## WebHID (browser)

Serve the `web/` directory over https or localhost:
```bash
python3 -m http.server -d web 8000
```
Then open <http://localhost:8000> in Chrome or Edge and click **Connect**.
On Linux, install the udev rule first.
Profiles export and import as the same JSON the CLI uses. You can also host the page on GitHub Pages.

**Why WebHID and not WebUSB?** Browsers refuse to let WebUSB claim HID-class interfaces,
and the mouse only has HID interfaces. WebHID does allow the vendor-defined collections
(usage pages `0xFF00`/`0xFF01`) that the configuration protocol uses. The protected
mouse/keyboard collections are never touched.

## Python API

```python
from thorx9 import protocol as P
from thorx9.device import Mouse

p = P.Profile()
p.dpi_levels[0].dpi = 800
p.led_mode = "static"
with Mouse() as m:
    m.send_all(p.packets())
    m.send(P.inject_consumer(P.CONSUMER["mute"]))
```

## Development

```bash
python3 -m unittest -v
```

The tests check every packet against sequences worked out by hand from the vendor disassembly.

## Legal

This is an independent interoperability project and is not affiliated with FANTECH.
No vendor code or assets are included. MIT licensed.
