# How this was reverse engineered (reproducible)

Everything here is static. Nothing from the vendor was executed. Please don't commit vendor binaries to this repo.

1. **Unpack the bootstrapper.** `Thor_X9_Software_V1.0_19122000.exe` is an InstallShield setup with an
   `ISSetupStream` overlay. `tools/isx_extract.py` documents and decodes that format
   (each byte is nibble-swapped, XORed with a key derived from the filename, inverted, then zlib-inflated):
   ```bash
   pip install pefile
   python3 -I tools/isx_extract.py Thor_X9_Software_V1.0_19122000.exe out/
   ```
2. **Unpack the MSI** with msitools: `msiextract -C files "out/FANTECH X9 Gaming Mouse.msi"`.
   `msidump -t` dumps the tables used for the installer review.
3. **Find the HID code.** The app imports `HID.DLL` (`HidD_SetFeature`, `HidD_GetAttributes`, `HidP_GetCaps`)
   and SetupAPI. Look for callers of the import thunks (`HidD_SetFeature` thunk at VA `0x555786`):
   enumeration is at `0x405ed0`, the Apply routine at `0x408630`, the event reader at `0x406fa0`,
   and the host-side function executor at `0x408230`.
4. **Name the globals.** The INI save routine (around VA `0x412ef0`) writes each global under its key
   (`DPI_SET`, `LED_TYPE`, `FIRE_TIME`, …). That links the memory addresses in the Apply routine to meaning.
   UI labels come from `skins/INI_EN/*.ini`. The DPI ladder is painted on `skins/main_normal.jpg`.

Python with `pefile` and `capstone` was enough for all of this. Ghidra will get you there faster.
