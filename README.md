# Thor-X9: a free driver for the FANTECH Thor X9 mouse

FANTECH ships the Thor X9 with a Windows-only, admin-only configuration app.
This repository has:

* **`thorx9`**: a dependency-free Python CLI/library for Linux (macOS/Windows via `hidapi`)
* **`web/index.html`**: a WebHID page that configures the mouse from Chrome/Edge on any OS
* **[docs/PROTOCOL.md](docs/PROTOCOL.md)**: the full USB protocol, with the vendor-binary address each fact came from
* **[docs/SECURITY_ANALYSIS.md](docs/SECURITY_ANALYSIS.md)**: what the vendor app actually does (no evidence of spyware, but sloppy and over-privileged)
* **[docs/HIDDEN_FEATURES.md](docs/HIDDEN_FEATURES.md)**: leftovers, hidden functions, and untested firmware values you can probe with `thorx9 explore`
* **[docs/REVERSING.md](docs/REVERSING.md)**: how to reproduce the analysis

> ⚠️ **Status: protocol recovered by static analysis, not yet tested on hardware.**
> The packets match the vendor app's logic byte for byte, but if you own the mouse,
> please report what works (or doesn't) in an issue. Results from `thorx9 list` are especially useful.

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
| Media keys, shortcuts, macros, launching programs | ✅ via `thorx9 listen` (this was host-side in the vendor app too) |
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

### Host-side buttons: media keys, shortcuts, macros, launching programs

Set a button's function to `host`. The mouse then reports its presses instead of acting on them, and
`thorx9 listen` can react. Like the vendor app, it can make the **mouse itself** type keys or media keys,
so this works under Wayland, X11 and in games:

```bash
thorx9 apply --button dpi_minus=host --save
```
```bash
thorx9 listen --actions examples/actions.json
```

Action types in `actions.json`:
* `{"consumer": "vol_up"}`: one of `browser player mail vol_up vol_down prev next mute play_pause calculator stop`, or a raw usage number.
* `{"keys": ["0xE0", "0x06"]}`: press HID key usages together (here Ctrl+C), then release.
* `{"sequence": [[["0x04"], 50], [["0x05"], 50]]}`: a simple macro: a list of `[keys, delay_ms]` steps.
* `{"run": "command"}`: run a program.

`thorx9 listen` with no actions just prints which physical button is which. Use it to identify buttons on your unit.

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
