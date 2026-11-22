# Hidden features, leftovers and Easter-egg hunt

This is the result of a second pass over the vendor binary, specifically looking for code paths,
values and assets that the UI never exposes.

**TL;DR:** the app has no Easter eggs. It is a re-skinned white-label tool ("IST_GMouse Version 1.0,
Copyright (C) 2015"). The interesting unknowns are **in the firmware**: values that fit the packet
format but that the app never sends. You can test them with `thorx9 explore` (see the end).

## In the vendor app

| Finding | Where | Notes |
|---|---|---|
| **Hidden "launch calc.exe / cmd.exe" functions** | VA `0x408511` | Button function indices 39/40. Not in any language's menu; reachable only by editing `config.ini`. The visible "Calculator" item sends a media key instead. |
| **Left-click safety net** | VA `0x4161c0`, `LBWarning*.ini` | If a remap leaves no button doing left click, the app forces one ("Force the next Key to click"). `thorx9 apply` now refuses such a mapping unless you pass `--force`. |
| **Report-rate UI, commented out** | `skin_advance_en.ini` (`;34=USB_SPEED0` … `;51=Report Rate`), VA `0x40cba0` | The handler, the INI key `USB_SPEED` and its drawing code all survive, but no packet is ever sent. Re-enabling the UI would do nothing to the mouse. |
| **Support for 8–9 buttons** | button table VA `0x5bb018` = `01 02 03 05 04 08 06 09`; default table VA `0x5bb038` has an 8th entry `0x0D`; skin has `USER_BTN8/9` and `BUTTON08/09` | The code shared with a bigger sibling model: hardware button `09` (factory function "Fire"). The X9 code path only loops over 7 buttons. |
| **7th DPI colour** | `DPI6_R/G/B` in `config.ini` | Leftover from a 7-slot model. Never read. |
| **The "Chinese" language is Japanese** | `skins/INI_CN/*` | The code calls it `CHINESE_SEL` and the folder is `INI_CN`, but every string is Japanese, which is why the skin shows 日本語. One Chinese developer string survived: 找不到配置文件 ("config file not found"). |
| **Uninitialised memory in factory presets** | `config.ini`: `K9=16843009` (`0x01010101`), `K8=1684`, `K10=46`, `LED_STATUS`, `[???????]` | Stale keys and garbage written by older builds. The `[???????]` section is a CJK name destroyed by an ANSI write. `[Config3]` also defines `K0` twice; Windows uses the first one. (`thorx9 import-ini` now does the same.) |
| **"Run till release" macro limit** | VA `0x40835c` | A held macro repeats at most 10 000 times. |
| **Macro editor can insert raw mouse clicks** | menu resource 154 | Left/Right/Mid down/up events, played back through `07 16`. The menu order (Left, Right, Mid) matches HID bit order, so bit 0 = left, bit 1 = right, bit 2 = middle is likely, but not verified. |

## In the firmware: values nobody has tried

The app only ever uses part of each field. The firmware might accept more. All of these stay
**inside commands the app already uses**. I deliberately did **not** list unknown command bytes
(`07 00`…`07 08`, `07 0A`…`07 0F`, `07 18`…`07 1F`, `07 21`+): on cheap MCUs these sometimes enter a
bootloader or write flash, and there is no recovery tool for this mouse.

| What | Known values | Unexplored | Why it's interesting |
|---|---|---|---|
| DPI code (`07 09`) | 1–7, 9, B, D, E, F | **0, 8, A, C** | The ladder skips exactly these. They are probably the in-between sensor steps (around 1800/2200/2800 DPI?) |
| Button function (`07 10`) | 00–0C | **0D**, 0E–1F | `0x0D` is wired up in the mapping code (UI index 17) but has no label in any language |
| LED mode byte (`07 13`) | 80–85, 86, 87, 90–95 | **88–8F, 96–9F, A0–BF** | The high nibble looks like a mode number (8 = fixed, 9 = cyclic). `A`/`B` could be breathing or other effects the app never offered |
| Fire packet (`07 12`) | `HH LL 00 00 00 00` | the 4 trailing bytes | The app explicitly zeroes them (`mov dword [..], 0`), which suggests they mean something (burst count?) |
| Wheel (`07 11`) | `WW 00` | byte 3, `WW` ≥ 2 | |

### Try them yourself

`thorx9 explore` steps through one of these ranges. It sends one value at a time, lets you write down
what you observe, and **restores your saved profile when you quit** (also on Ctrl-C).

```bash
thorx9 explore dpi
```
```bash
thorx9 explore led --from 0x88 --to 0xbf
```
```bash
thorx9 explore func --button dpi_minus --from 0x0d --to 0x1f
```

Keys: Enter = next value, `b` = back, `n some text` = record a note, `q` = quit.
For `func`, any host-button events the mouse reports while you test are printed too.
Please post your notes in an issue so the tables above can be filled in.
