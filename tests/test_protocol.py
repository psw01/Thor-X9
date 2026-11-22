"""Packet golden tests.

Expected bytes were worked out by hand from the vendor Apply routine
(VA 0x408630) using the factory [Config1] section of skins/config/config.ini.
"""

import unittest

from thorx9 import protocol as P
from thorx9.device import parse_report_descriptor

CONFIG1 = """
[Config1]
K0=1
K1=2
K2=3
K3=5
K4=4
K5=15
K6=16
DPI_SET0=2
DPI_SET1=4
DPI_SET2=5
DPI_SET3=7
DPI_SET4=9
DPI_SET5=11
DPI_LEVEL=1
DPI_SET_EN0=1
DPI_SET_EN1=1
DPI_SET_EN2=1
DPI_SET_EN3=1
DPI_SET_EN4=1
DPI_SET_EN5=1
DPI0_R=0
DPI0_G=0
DPI0_B=15
DPI1_R=15
DPI1_G=15
DPI1_B=0
DPI2_R=0
DPI2_G=15
DPI2_B=0
DPI3_R=15
DPI3_G=0
DPI3_B=15
DPI4_R=0
DPI4_G=15
DPI4_B=15
DPI5_R=0
DPI5_G=0
DPI5_B=0
LED_STATUS=0
WHEEL_STATUS=0
CYC_7COL_EN=127
LED_TYPE=1
LED_CYC_TIME=2
FIRE_TIME=50
"""

EXPECTED = """
07 10 01 01
07 10 02 02
07 10 03 03
07 10 05 05
07 10 04 04
07 10 08 0b
07 10 06 0c
07 11 00 00
07 13 7f 92
07 09 41 38 3f
07 14 00 0f
07 09 41 59 3f
07 14 2f f0
07 09 41 6a 3f
07 14 4f 00
07 09 41 9b 3f
07 14 60 ff
07 09 41 dc 3f
07 14 8f 0f
07 09 41 fd 3f
07 14 a0 00
07 12 00 06
"""


class ProtocolTest(unittest.TestCase):
    def test_vendor_config1_sequence(self):
        p = P.profile_from_vendor_ini(CONFIG1, "Config1")
        got = [pkt.hex(" ") for pkt in p.packets(8)]
        want = [bytes.fromhex(l).ljust(8, b"\0").hex(" ") for l in EXPECTED.split("\n") if l.strip()]
        self.assertEqual(got, want)

    def test_profile_roundtrip(self):
        p = P.profile_from_vendor_ini(CONFIG1)
        q = P.Profile.from_dict(p.to_dict())
        self.assertEqual(p.packets(), q.packets())

    def test_ini_first_occurrence_wins(self):
        # like the vendor [Config3]: K0 appears twice, Windows uses the first one
        p = P.profile_from_vendor_ini(CONFIG1 + "K0=0\n", "Config1")
        self.assertEqual(p.buttons["left"], "left")

    def test_device_match(self):
        from thorx9.device import Match
        thor = Match()
        self.assertTrue(thor(0x18F8, 0x1086) and thor(0x18F8, 0x0FC0))
        self.assertFalse(thor(0x046D, 0xC077))
        self.assertTrue(Match.parse(any_device=True)(0x046D, 0xC077))
        m = Match.parse(usb_id="046d:c077")
        self.assertTrue(m(0x046D, 0xC077) and not m(0x046D, 0xC078) and not m.is_thor)
        self.assertTrue(Match.parse(usb_id="046d")(0x046D, 0x1234))
        with self.assertRaises(SystemExit):
            Match.parse(usb_id="zz")

    def test_left_click_guard(self):
        p = P.Profile()
        self.assertTrue(p.has_left_click())
        p.buttons["left"] = "fire"
        self.assertFalse(p.has_left_click())
        p.buttons["back"] = "left"
        self.assertTrue(p.has_left_click())

    def test_led_modes(self):
        self.assertEqual(P.led("static")[:3], bytes([7, 0x13, 0x7F]) )
        self.assertEqual(P.led("static")[3], 0x86)
        self.assertEqual(P.led("off")[3], 0x87)
        self.assertEqual(P.led("fixed", 1)[3], 0x85)
        self.assertEqual(P.led("cyclic", 6)[3], 0x90)

    def test_colors(self):
        self.assertEqual(P._parse_color("#ff8000"), (15, 8, 0))
        self.assertEqual(P._parse_color("#0f0"), (0, 15, 0))
        self.assertEqual(P._parse_color([1, 2, 3]), (1, 2, 3))

    def test_injection(self):
        self.assertEqual(P.inject_consumer(P.CONSUMER["vol_up"])[:4], bytes([7, 0x17, 0x00, 0xE9]))
        self.assertEqual(P.inject_keys([0xE0, 0x06])[:8], bytes([7, 0x15, 0xE0, 6, 0, 0, 0, 0]))
        self.assertEqual(P.inject_mouse(0b001)[3], 0xFE)
        self.assertEqual(P.host_detach()[:2], bytes([7, 0x20]))

    def test_event_parse(self):
        ev = P.parse_event(bytes([6, 0xF5, 2]))
        self.assertEqual((ev.name, ev.pressed, ev.dpi_slot), ("forward", True, 2))
        ev = P.parse_event(bytes([6, 0xF5, 0x80]))
        self.assertFalse(ev.pressed)
        self.assertIsNone(P.parse_event(bytes([1, 0, 0])))

    def test_bad_values(self):
        with self.assertRaises(ValueError):
            P.dpi_to_code(1500)
        with self.assertRaises(ValueError):
            P.dpi_color(0, 16, 0, 0)

    def test_descriptor_parser(self):
        desc = bytes([
            0x06, 0x01, 0xFF, 0x09, 0x01, 0xA1, 0x01,   # usage page FF01, collection
            0x85, 0x07, 0x75, 0x08, 0x95, 0x07,          # report id 7, 8 bits x 7
            0x09, 0x01, 0xB1, 0x02, 0xC0,                # feature
            0x06, 0x00, 0xFF, 0x09, 0x01, 0xA1, 0x01,   # usage page FF00
            0x85, 0x06, 0x75, 0x08, 0x95, 0x02,
            0x09, 0x01, 0x81, 0x02, 0xC0,                # input
        ])
        info = parse_report_descriptor(desc)
        self.assertEqual(info.feature, {7: 8})
        self.assertEqual(info.input, {6: 3})
        self.assertEqual(info.top_pages, [0xFF01, 0xFF00])


if __name__ == "__main__":
    unittest.main()
