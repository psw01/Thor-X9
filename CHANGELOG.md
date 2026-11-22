# Changelog

## v0.1.0 (2026-11-22): first release

* Full Thor X9 configuration protocol, recovered statically from the vendor app ([docs/PROTOCOL.md](docs/PROTOCOL.md)).
* `thorx9` Python CLI/library with no dependencies: `list`, `apply`, `show`, `import-ini`, `raw`, `explore`, `listen`, `keys`, `detach`.
* Host-side actions via `thorx9 listen`: any key (F13–F24, combos), media keys, macros (repeat N / while held / toggle), launching programs.
* WebHID configurator (`web/index.html`) for Chrome/Edge.
* Experimental `--any-device` / **Allow any HID device** mode.
* udev rule, systemd user service example, vendor INI import.
* Security analysis of the vendor app: no evidence of spyware ([docs/SECURITY_ANALYSIS.md](docs/SECURITY_ANALYSIS.md)).
* Hidden features and leftovers write-up ([docs/HIDDEN_FEATURES.md](docs/HIDDEN_FEATURES.md)).

Vibe-coded with an AI assistant; confirmed working on the author's mouse. See the README disclaimer.
