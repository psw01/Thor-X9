# Is the vendor software spyware?

**Short answer:** I found **no evidence of spying or data exfiltration**.
The software is badly engineered, though, and a few of its behaviours look alarming at first glance.
This is a static review only. Nothing was executed, so runtime behaviour (for example from
another downloaded version) is outside its scope.

## Samples

| File | SHA-256 |
|---|---|
| `Thor_X9_Software_V1.0_19122000.exe` (InstallShield bootstrapper) | `6cba95aedb4512f64fc961543774c6f9cc189d8cf06e1110c57233048cfe93fe` |
| `FANTECH X9 Gaming Mouse.msi` (embedded) | `e2081c8b9c5557a27c316808d26a20b6f83b0f746b1e89a7b1ee149c731d0ab0` |
| `Gaming Mouse 2.0.exe` (the app) | `727d6377b1fbe2221033c52f8f3dafb971c754b3bbd9024cb3bd970749d37154` |

MSI metadata: author "Trends Electronic Co.,Ltd.", built with InstallShield 2015, dated 2019-04-08.
The app is an MFC application built with Visual Studio 2013.

## Findings

### 1. Global keyboard hook: present, but only while recording a macro
`SetWindowsHookExW(WH_KEYBOARD_LL, …)` at VA `0x40c86b`. This is the classic keylogger API, and it is
probably where the "spy vibes" come from. In this app:

* It is installed **only when you press "Record"** in the macro editor and removed (`UnhookWindowsHookEx`, VA `0x40c9bb`) when you press it again.
* The hook procedure (VA `0x406ed0`) sends each key event with `PostMessageW` to the app's **own** window ("FANTECH X9 MACRO Gaming Mouse"). The macro editor stores it there.
* Bug: the procedure returns 1 and never calls `CallNextHookEx`. While recording, **every keystroke in the whole system is swallowed**: other apps receive nothing.

### 2. Requires administrator rights for no reason
The manifest sets `requestedExecutionLevel level="requireAdministrator"`. Talking to a HID device does
not need admin on Windows, so every launch runs a 2019 MFC app with full privileges.

### 3. Launches programs: `calc.exe` and `cmd.exe`
`WinExec("calc.exe")` / `WinExec("cmd.exe")` at VA `0x40851d`/`0x408534`. They run when a host-handled
button is pressed and its function index is 39 or 40. The English UI offers neither index; its "Calculator"
entry (index 30) sends the Consumer usage `0x192` instead. These look like leftover features. The
program names are hard-coded and nothing is downloaded, but an app that runs as admin and can spawn `cmd.exe`
from a profile setting is poor design.

### 4. Network
* No networking DLLs are imported (no ws2_32, wininet, winhttp or urlmon), either statically or by name for dynamic loading.
* The only URL is `http://www.fantechworld.com`, opened in your default browser with `ShellExecuteW("open")` when you click the logo (VA `0x40d392`).
* The bootstrapper imports `HttpSendRequestW` and similar functions. These are standard in the InstallShield setup stub (for downloading prerequisites); this installer has none to download.

### 5. Installer
* No services, scheduled tasks, drivers or `Run` keys. The MSI has no `Registry` table, and the app contains no `CurrentVersion\Run` string.
* Custom actions are stock InstallShield ones (`ISPrint`, `ISSelfReg`, "launch program after install").
* The MFC framework writes its normal settings to `HKCU\Software\Local AppWizard-Generated Applications`.

### 6. Other behaviours
* It polls `GetAsyncKeyState`, both in MFC internals and in the macro player.
* It writes keyboard events *to the mouse* (`07 15`) so the mouse can type macros. This is how the vendor implements macros, not an exploit.
* It reads only from the mouse's vendor HID collection, not from other devices.

## Verdict
The software is sloppy and over-privileged, and it has a keystroke-eating bug while recording,
but nothing in it collects or transmits data. You still don't need it: everything it does is reproduced in this repository.
