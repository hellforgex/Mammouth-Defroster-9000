import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from modules.desktop_input import (
    desktop_get_screen_info,
    mouse_get_position,
    mouse_move,
    mouse_click,
    mouse_drag,
    mouse_scroll,
    keyboard_type,
    keyboard_press,
    keyboard_hotkey
)


class TestDesktopInput(unittest.TestCase):
    def test_screen_info_and_cursor(self):
        info = desktop_get_screen_info()
        self.assertIn("width", info)
        self.assertIn("height", info)
        self.assertGreater(info["width"], 0)
        self.assertGreater(info["height"], 0)
        
        pos = mouse_get_position()
        self.assertIn("x", pos)
        self.assertIn("y", pos)

    def test_mouse_move_bounds(self):
        info = desktop_get_screen_info()
        res = mouse_move(100, 100, duration=0.0)
        self.assertEqual(res["status"], "success")
        self.assertLessEqual(res["cursor_x"], info["width"])
        self.assertLessEqual(res["cursor_y"], info["height"])

        # Test zero coordinate (0, 0) without failsafe crash
        res_zero = mouse_move(0, 0, duration=0.0)
        self.assertEqual(res_zero["status"], "success")
        self.assertEqual(res_zero["cursor_x"], 0)
        self.assertEqual(res_zero["cursor_y"], 0)

    def test_mouse_click(self):
        res = mouse_click(button="left", clicks=1)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["button"], "left")

    def test_mouse_drag(self):
        # Drag from 50, 50 to 100, 100
        res = mouse_drag(start_x=50, start_y=50, end_x=100, end_y=100, button="left", duration=0.05)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["start_x"], 50)
        self.assertEqual(res["start_y"], 50)
        self.assertEqual(res["end_x"], 100)
        self.assertEqual(res["end_y"], 100)
        self.assertEqual(res["button"], "left")

        # Drag with x, y aliases
        res_alias = mouse_drag(start_x=0, start_y=0, x=50, y=50, duration=0.05)
        self.assertEqual(res_alias["status"], "success")
        self.assertEqual(res_alias["start_x"], 0)
        self.assertEqual(res_alias["start_y"], 0)
        self.assertEqual(res_alias["end_x"], 50)
        self.assertEqual(res_alias["end_y"], 50)

    def test_mouse_scroll(self):
        res = mouse_scroll(5)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["scroll_amount"], 5)
        self.assertEqual(res["direction"], "up")

        res_down = mouse_scroll(-5)
        self.assertEqual(res_down["status"], "success")
        self.assertEqual(res_down["scroll_amount"], -5)
        self.assertEqual(res_down["direction"], "down")

    def test_keyboard_hotkey(self):
        # Empty hotkey should return error
        res_empty = keyboard_hotkey("")
        self.assertEqual(res_empty["status"], "error")

        # Valid hotkey should succeed
        res_valid = keyboard_hotkey("ctrl+shift+f12")
        self.assertEqual(res_valid["status"], "success")
        self.assertEqual(res_valid["hotkey"], "ctrl+shift+f12")

    def test_keyboard_press_and_type(self):
        res_press = keyboard_press("esc")
        self.assertEqual(res_press["status"], "success")
        self.assertEqual(res_press["key"], "esc")

        res_alias = keyboard_press("return")
        self.assertEqual(res_alias["status"], "success")
        self.assertEqual(res_alias["key"], "enter")

        res_type = keyboard_type("hello\nworld", delay=0.0)
        self.assertEqual(res_type["status"], "success")
        self.assertEqual(res_type["typed_characters"], len("hello\nworld"))


if __name__ == "__main__":
    unittest.main()
