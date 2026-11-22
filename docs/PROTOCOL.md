# FANTECH Thor X9 USB protocol

I recovered this protocol by **static analysis** of the vendor software (`Gaming Mouse 2.0.exe`,
SHA-256 `727d6377…d37154`, from the installer `Thor_X9_Software_V1.0_19122000.exe`).
The vendor software was never run. Addresses (VA) refer to that executable, image base `0x400000`,
so anyone can check them in a disassembler.

**Confidence labels:**
✅ read directly from the code; 🟡 inferred from naming or context; ❓ not yet tested on hardware.
Core settings (DPI, LED, button remapping) have been confirmed on a real mouse; items marked ❓ are still untested. Please open an issue with your results.

## Device

| | |
|---|---|
| Vendor ID | `0x18F8` ✅ (VA `0x5bb004`) |
| Product ID | `0x1086` or `0x0FC0` ✅ (VA `0x5bb008`, `0x5bb00c`) |
| Command collection | usage page `0xFF01`, usage `0x01`, opened write-only ✅ |
| Event collection | usage page `0xFF00`, usage `0x01`, opened read-only ✅ |

The app enumerates HID interfaces with SetupAPI and checks VID/PID with `HidD_GetAttributes`.
It then uses `HidP_GetCaps` to find the two vendor collections (VA `0x405ed0`).

* **Host → mouse:** every command is a **feature report** (`HidD_SetFeature`) with
  **report ID `0x07`**. The buffer length is the collection's `FeatureReportByteLength`.
  This is probably 8 bytes including the ID, but the tools read the real value from the
  report descriptor. Unused bytes are zero. The app never reads a feature report back,
  so as far as we know the device cannot be queried.
* **Mouse → host:** **input reports** with **report ID `0x06`** on the `0xFF00` collection
  (a `ReadFile` loop at VA `0x406fa0`).

## Commands (feature report `07 CC …`)

| CC | Bytes | Meaning |
|---|---|---|
| `10` | `07 10 BB FF` | Assign function `FF` to hardware button `BB` ✅ |
| `11` | `07 11 WW 00` | Wheel mode: `00` = scroll, `01` = volume ✅ (field), 🟡 (value names) |
| `13` | `07 13 MM TT` | LED: `MM` = 7-bit mask of colours used in the cycle, `TT` = mode byte ✅ |
| `09` | `07 09 AA DD EE` | DPI slot ✅: `AA = 0x40 \| active_slot`, `DD = (dpi_code<<4) \| 0x08 \| slot`, `EE` = 6-bit mask of enabled slots |
| `14` | `07 14 SG RB` | DPI slot colour ✅: `SG = (slot<<5) \| G`, `RB = (R<<4) \| B`, 4 bits per channel |
| `12` | `07 12 HH LL 00 00 00 00` | Rapid-fire interval: `FIRE_TIME/8` as big-endian u16 ✅. UI range 0–300 ms, default 50 (VA `0x40cc0f`); probably 8 ms frames |
| `15` | `07 15 k1 k2 k3 k4 k5 k6` | Mouse sends a keyboard report with these 6 key codes. All zero = release ✅ (structure), ❓ (code set; probably HID usage IDs, so modifiers would be `E0`–`E7`) |
| `16` | `07 16 00 MM` | Mouse sends a mouse-button report. `MM` is **active-low** (bit clear = pressed), bits 0–2 ✅. Bit order 🟡 (probably HID order: left, right, middle). The vendor app leaves byte 2 uninitialised. |
| `17` | `07 17 HH LL` | Mouse sends a Consumer Control usage `HHLL` ✅. The app never sends a release. |
| `20` | `07 20 00 00` | Sent when the vendor app exits or its tray icon is removed ✅. Effect ❓ (probably "host software detached"). |

### Apply sequence

The vendor **Apply** button (VA `0x408630`) sends these reports in this order, with no delays:

1. `07 10` ×7 (one per button)
2. `07 11` (wheel)
3. `07 13` (LED)
4. For each slot 0..5: `07 09`, then `07 14`
5. `07 12` (fire interval)

### Buttons (`07 10 BB FF`)

Hardware button IDs, in the order the UI lists them (table at VA `0x5bb018`).
The names come from the factory default function of each slot ✅.
The physical location of the two DPI buttons is 🟡: the skin image labels them the other way round.
Use `thorx9 listen` to check on your own unit.

| UI row | name | `BB` | factory function |
|---|---|---|---|
| 1 | left | `01` | left |
| 2 | middle | `02` | middle |
| 3 | right | `03` | right |
| 4 | forward (upper side) | `05` | forward |
| 5 | back (lower side) | `04` | back |
| 6 | dpi_plus | `08` | DPI+ |
| 7 | dpi_minus | `06` | DPI− |

Function codes `FF` (mapping code at VA `0x408750`):

| `FF` | function | | `FF` | function |
|---|---|---|---|---|
| `00` | **host-handled**: firmware reports the press via input report `06` | | `07` | show desktop |
| `01` | left click | | `08` | double click |
| `02` | middle click | | `09` | rapid fire ("Fire") |
| `03` | right click | | `0A` | off / disabled |
| `04` | back | | `0B` | DPI + |
| `05` | forward | | `0C` | DPI − |
| `06` | DPI loop | | `0D` | unlabeled in UI ❓ |

Some UI functions are implemented **on the PC**, not in the firmware. These include media keys,
"Copy/Paste/…", Calculator, "My computer", Lock PC and all macros. For these the app sends `FF = 00`.
When the button is pressed, the mouse sends an event (below) and the app answers with `07 15`, `07 16`
or `07 17` reports, or, for hidden function indices 39/40, launches `calc.exe`/`cmd.exe` (VA `0x408230`). **The mouse has no on-board macro storage.**

### DPI (`07 09`)

DPI ladder (the labels are painted on the vendor skin; the code table is at VA `0x5bb044`):

| DPI | 200 | 400 | 600 | 800 | 1000 | 1200 | 1600 | 2000 | 2400 | 3200 | 4000 | 4800 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| code | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 9 | B | D | E | F |

Six slots. Each `07 09` packet repeats the active slot and the enabled-slot mask.

### LED (`07 13 MM TT`)

| UI mode (`LED_TYPE`) | `TT` |
|---|---|
| 0 "Fixed" (🟡 shows the colour of the current DPI slot) | `0x80 \| speed` |
| 1 "Cyclic" | `0x90 \| speed` |
| 2 "Static" | `0x86` |
| 3 "OFF" | `0x87` |

`speed = 6 − seconds`: the UI options 1 s … 6 s become 5 … 0 (VA `0x40c1dc`).
Bit *n* of `MM` enables cycle colour *n* (n = 0..6). The colour order is not known 🟡.

### Not in the protocol

* **Polling rate:** the vendor app stores `USB_SPEED` but never sends it, and its UI for it is commented out.
* **"Pointer precision" / "wheel speed":** these are Windows settings (`SystemParametersInfo`), not mouse settings.
* **Profiles:** the 5 profiles (Cfg1–3, Media, Game) exist only in the app's INI file.
  The mouse keeps only what was last applied.

## Events (input report `06`)

```
06 <F0 + hw_button_id> <state>
```
`state = 0x80` means released. Any other value means pressed, and the value is the current DPI slot ✅ (VA `0x406fa0`, `0x408230`).
Events arrive only for buttons whose function is `00` (host-handled).

## Worked example

Factory profile `[Config1]`. This exact sequence is a golden test in `tests/test_protocol.py`:

```
07 10 01 01   07 10 02 02   07 10 03 03   07 10 05 05   07 10 04 04   07 10 08 0b   07 10 06 0c
07 11 00 00
07 13 7f 92
07 09 41 38 3f   07 14 00 0f
07 09 41 59 3f   07 14 2f f0
07 09 41 6a 3f   07 14 4f 00
07 09 41 9b 3f   07 14 60 ff
07 09 41 dc 3f   07 14 8f 0f
07 09 41 fd 3f   07 14 a0 00
07 12 00 06
```
