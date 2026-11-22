"""Device discovery and I/O.

Linux: talks to /dev/hidrawN directly with ioctl (no dependencies).
Other OSes: falls back to the `hid` (hidapi) Python package if installed.
"""

from __future__ import annotations

try:
    import fcntl
except ImportError:  # Windows: hidapi path only
    fcntl = None
import glob
import os
import select
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

from . import protocol as P


# --- HID report descriptor parsing --------------------------------------

@dataclass
class DescriptorInfo:
    # report id -> size in bytes INCLUDING the report-id byte
    feature: Dict[int, int] = field(default_factory=dict)
    input: Dict[int, int] = field(default_factory=dict)
    # report id -> usage page of the top-level collection it lives in
    page_of: Dict[Tuple[str, int], int] = field(default_factory=dict)
    top_pages: List[int] = field(default_factory=list)


def parse_report_descriptor(desc: bytes) -> DescriptorInfo:
    info = DescriptorInfo()
    bits: Dict[Tuple[str, int], int] = {}
    usage_page = 0
    report_size = report_count = report_id = 0
    usage = None
    depth = 0
    top_page = 0
    i = 0
    while i < len(desc):
        prefix = desc[i]
        if prefix == 0xFE:  # long item
            i += 3 + desc[i + 1]
            continue
        size = (0, 1, 2, 4)[prefix & 3]
        data = int.from_bytes(desc[i + 1:i + 1 + size], "little")
        tag, typ = prefix & 0xF0, (prefix >> 2) & 3
        i += 1 + size
        if typ == 1:  # global
            if tag == 0x00:
                usage_page = data
            elif tag == 0x70:
                report_size = data
            elif tag == 0x80:
                report_id = data
            elif tag == 0x90:
                report_count = data
        elif typ == 2 and tag == 0x00:  # local usage
            usage = data
        elif typ == 0:  # main
            if tag == 0xA0:  # collection
                if depth == 0:
                    top_page = usage_page
                    info.top_pages.append(usage_page)
                depth += 1
            elif tag == 0xC0:
                depth = max(0, depth - 1)
            elif tag in (0x80, 0xB0):  # input / feature
                kind = "input" if tag == 0x80 else "feature"
                key = (kind, report_id)
                bits[key] = bits.get(key, 0) + report_size * report_count
                info.page_of.setdefault(key, top_page)
            usage = None
    for (kind, rid), b in bits.items():
        nbytes = (b + 7) // 8 + (1 if rid else 0)
        getattr(info, kind)[rid] = nbytes
    return info


# --- hidraw --------------------------------------------------------------

def _ioc(direction: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord("H") << 8) | nr


def HIDIOCSFEATURE(n: int) -> int:
    return _ioc(3, 0x06, n)


def HIDIOCGFEATURE(n: int) -> int:
    return _ioc(3, 0x07, n)


@dataclass
class HidrawNode:
    path: str
    vid: int
    pid: int
    info: DescriptorInfo
    name: str = ""

    @property
    def cmd_len(self) -> Optional[int]:
        return self.info.feature.get(P.REPORT_ID_CMD)

    @property
    def has_events(self) -> bool:
        return P.REPORT_ID_EVENT in self.info.input


ANY_DEVICE_WARNING = (
    "WARNING: any-device mode. This tool only knows the FANTECH Thor X9 protocol; on other\n"
    "devices it may not work at all, may do nothing, or may change settings in unexpected ways.\n"
    "Use at your own risk.")


@dataclass
class Match:
    """Which devices to talk to. Default: only the Thor X9."""
    any_device: bool = False
    vid: Optional[int] = None
    pid: Optional[int] = None

    def __call__(self, vid: int, pid: int) -> bool:
        if self.vid is not None:
            return vid == self.vid and (self.pid is None or pid == self.pid)
        if self.any_device:
            return True
        return vid == P.VENDOR_ID and pid in P.PRODUCT_IDS

    @property
    def is_thor(self) -> bool:
        return not self.any_device and self.vid is None

    @classmethod
    def parse(cls, any_device: bool = False, usb_id: Optional[str] = None) -> "Match":
        if not usb_id:
            return cls(any_device)
        v, _, p = usb_id.partition(":")
        try:
            return cls(True, int(v, 16), int(p, 16) if p else None)
        except ValueError:
            raise SystemExit(f"bad --usb-id {usb_id!r}; expected VID:PID in hex, e.g. 046d:c077")


def _node_from_sysfs(sysdir: str) -> Optional[HidrawNode]:
    try:
        uevent = open(os.path.join(sysdir, "device", "uevent")).read()
    except OSError:
        return None
    hid_id = next((l.split("=", 1)[1] for l in uevent.splitlines() if l.startswith("HID_ID=")), None)
    if not hid_id:
        return None
    _bus, vid, pid = (int(x, 16) for x in hid_id.split(":"))
    name = next((l.split("=", 1)[1] for l in uevent.splitlines() if l.startswith("HID_NAME=")), "")
    try:
        desc = open(os.path.join(sysdir, "device", "report_descriptor"), "rb").read()
    except OSError:
        desc = b""
    return HidrawNode("/dev/" + os.path.basename(sysdir), vid, pid,
                      parse_report_descriptor(desc), name)


def find_hidraw(match: Optional[Match] = None) -> List[HidrawNode]:
    match = match or Match()
    nodes = []
    for sysdir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        n = _node_from_sysfs(sysdir)
        if n and match(n.vid, n.pid):
            nodes.append(n)
    return nodes


class Mouse:
    """Open handle to the Thor X9 vendor interface (or, in any-device mode, any HID device)."""

    def __init__(self, path: Optional[str] = None, report_len: Optional[int] = None,
                 dry_run: bool = False, verbose: bool = False, match: Optional[Match] = None):
        self.match = match = match or Match()
        self.dry_run = dry_run
        self.verbose = verbose
        self.fd = None
        self.event_fd = None
        self._hidapi = None
        self.report_len = report_len or P.DEFAULT_REPORT_LEN
        if dry_run:
            return
        if path:
            node = _node_from_sysfs("/sys/class/hidraw/" + os.path.basename(path)) if fcntl else None
            if node and node.cmd_len and not report_len:
                self.report_len = node.cmd_len
            self.fd = os.open(path, os.O_RDWR)
            self.event_fd = self.fd
            return
        nodes = find_hidraw(match) if fcntl else []
        if nodes and not match.is_thor:
            with_cmd = [n for n in nodes if n.cmd_len]
            if len(with_cmd) == 1:
                nodes = with_cmd
            elif len({n.path for n in nodes}) > 1:
                listing = "\n".join(f"  {n.path}  {n.vid:04x}:{n.pid:04x}  {n.name}" for n in nodes)
                raise SystemExit("several matching devices; pick one with --device or --usb-id:\n"
                                 + listing)
        if nodes:
            cmd = next((n for n in nodes if n.cmd_len), nodes[0])
            ev = next((n for n in nodes if n.has_events), cmd)
            if cmd.cmd_len and not report_len:
                self.report_len = cmd.cmd_len
            self.fd = os.open(cmd.path, os.O_RDWR)
            self.event_fd = self.fd if ev.path == cmd.path else os.open(ev.path, os.O_RDONLY)
            return
        self._open_hidapi()

    def _open_hidapi(self):
        try:
            import hid  # type: ignore
        except ImportError:
            raise SystemExit("No matching device found via hidraw, and the 'hid' (hidapi) "
                             "package is not installed.")
        devs = [d for d in hid.enumerate(0, 0) if self.match(d["vendor_id"], d["product_id"])]
        out = next((d for d in devs if d.get("usage_page") == P.USAGE_PAGE_OUT), None)
        inp = next((d for d in devs if d.get("usage_page") == P.USAGE_PAGE_IN), None)
        if not out and not self.match.is_thor:
            ids = {(d["vendor_id"], d["product_id"]) for d in devs}
            if len(ids) > 1:
                raise SystemExit("several matching devices; pick one with --usb-id VID:PID")
            out = next(iter(devs), None)
        if not out:
            raise SystemExit("Thor X9 not found (VID 18f8, PID 1086/0fc0)." if self.match.is_thor
                             else "no matching HID device found")
        self._hidapi = hid.device()
        self._hidapi.open_path(out["path"])
        self._hidapi_in = None
        if inp:
            self._hidapi_in = hid.device()
            self._hidapi_in.open_path(inp["path"])

    # -- output --
    def send(self, packet: bytes) -> None:
        packet = packet[: self.report_len].ljust(self.report_len, b"\x00")
        if self.verbose or self.dry_run:
            print("->", packet.hex(" "))
        if self.dry_run:
            return
        if self._hidapi is not None:
            self._hidapi.send_feature_report(packet)
            return
        buf = bytearray(packet)
        fcntl.ioctl(self.fd, HIDIOCSFEATURE(len(buf)), buf)

    def send_all(self, packets) -> None:
        for p in packets:
            self.send(p)

    # -- input --
    def events(self, timeout: Optional[float] = None) -> Iterator[P.ButtonEvent]:
        if self.dry_run:
            return
        while True:
            if self._hidapi is not None:
                if not self._hidapi_in:
                    raise SystemExit("event collection (usage page 0xFF00) not found")
                data = bytes(self._hidapi_in.read(64, int((timeout or 0) * 1000)))
                if not data:
                    if timeout is not None:
                        return
                    continue
            else:
                r, _, _ = select.select([self.event_fd], [], [], timeout)
                if not r:
                    return
                data = os.read(self.event_fd, 64)
            ev = P.parse_event(data)
            if self.verbose:
                print("<-", data.hex(" "))
            if ev:
                yield ev

    def close(self):
        for fd in {self.fd, self.event_fd} - {None}:
            os.close(fd)
        self.fd = self.event_fd = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
