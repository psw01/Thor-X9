import time
import unittest

from thorx9.actions import Action, Injector, load_actions, parse_macro
from thorx9.keys import char_keys, combo


class FakeMouse:
    def __init__(self):
        self.sent = []

    def send(self, p):
        self.sent.append(p[:8].hex(" "))


class KeysTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(combo("f13"), [0x68])
        self.assertEqual(combo("F24"), [0x73])
        self.assertEqual(combo("ctrl+shift+a"), [0xE0, 0xE1, 0x04])
        self.assertEqual(combo("0x68"), [0x68])
        self.assertEqual(combo(["ctrl", "c"]), [0xE0, 0x06])
        self.assertEqual(char_keys("A"), (0x04, True))
        self.assertEqual(char_keys("!"), (0x1E, True))
        with self.assertRaises(ValueError):
            combo("hyper")


class ActionsTest(unittest.TestCase):
    def setUp(self):
        self.m = FakeMouse()
        self.inj = Injector(self.m)

    def test_held_key(self):
        a = Action("f13", {})
        a.press(self.inj)
        a.release(self.inj)
        self.assertEqual(self.m.sent, ["07 15 68 00 00 00 00 00", "07 15 00 00 00 00 00 00"])

    def test_two_held_keys_overlap(self):
        a, b = Action("f13", {}), Action("f14", {})
        a.press(self.inj); b.press(self.inj); a.release(self.inj); b.release(self.inj)
        self.assertEqual([s[:11] for s in self.m.sent],
                         ["07 15 68 00", "07 15 68 69", "07 15 69 00", "07 15 00 00"])

    def test_macro_once(self):
        a = Action({"macro": ["tap ctrl+c", "click right"]}, {})
        a.press(self.inj)
        a._thread.join(2)
        self.assertEqual([s[:11] for s in self.m.sent],
                         ["07 15 e0 06", "07 15 00 00", "07 16 00 fd", "07 16 00 ff"])

    def test_while_held_stops(self):
        a = Action({"macro": ["click left"], "repeat": "while_held"}, {})
        a.press(self.inj)
        time.sleep(0.15)
        a.release(self.inj)
        a._thread.join(2)
        self.assertFalse(a.running())
        self.assertGreater(len(self.m.sent), 2)
        self.assertEqual(self.m.sent[-1][:11], "07 16 00 ff")  # nothing left pressed

    def test_toggle(self):
        a = Action({"macro": ["wait 20"], "repeat": "toggle"}, {})
        a.press(self.inj); a.release(self.inj)
        time.sleep(0.05)
        self.assertTrue(a.running())
        a.press(self.inj)
        a._thread.join(2)
        self.assertFalse(a.running())

    def test_config_validation(self):
        load_actions({"back": {"macro": "m"}, "macros": {"m": ["type hi"]}})
        with self.assertRaises(ValueError):
            load_actions({"back": {"macro": "missing"}})
        with self.assertRaises(ValueError):
            load_actions({"thumb": "f13"})
        with self.assertRaises(ValueError):
            parse_macro(["jump 3"])


if __name__ == "__main__":
    unittest.main()
