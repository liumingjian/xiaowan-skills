#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import support  # noqa: F401  # adds scripts/ to sys.path

import wechat_auth


class QrTerminalRenderTests(unittest.TestCase):
    def test_compute_resize_scale_uses_ceil(self) -> None:
        # 230/58 = 3.96 -> ceil => 4; floor would cause wrapped output in 120-col terminals.
        scale = wechat_auth._compute_resize_scale(230, 58)
        self.assertEqual(scale, 4)

    def test_terminal_max_pixels_caps_width(self) -> None:
        # Large terminals should still render a reasonably sized QR code.
        max_pixels = wechat_auth._compute_terminal_max_pixels(200)
        self.assertEqual(max_pixels, wechat_auth.QR_TERMINAL_MAX_PIXELS)

    def test_rendered_width_never_exceeds_terminal_columns(self) -> None:
        # Ensure our plan won't wrap lines, which makes QR unscannable.
        terminal_columns = 120
        image_width = 230
        max_pixels = wechat_auth._compute_terminal_max_pixels(terminal_columns)
        scale = wechat_auth._compute_resize_scale(image_width, max_pixels)
        resized_width = image_width // scale
        printed_columns = int(resized_width) * int(wechat_auth.QR_TERMINAL_CHAR_WIDTH_PER_PIXEL)
        self.assertLessEqual(printed_columns, terminal_columns)

    def test_terminal_too_narrow_raises(self) -> None:
        with self.assertRaises(wechat_auth.LoginError):
            wechat_auth._compute_terminal_max_pixels(40)

    def test_display_qr_code_saves_png_before_terminal_render(self) -> None:
        with patch.object(wechat_auth, "_save_qr_png", return_value=Path("/tmp/qrcode.png")) as save_png:
            with patch.object(wechat_auth, "_render_qr_to_terminal") as render_terminal:
                wechat_auth._display_qr_code(b"pngdata")
        save_png.assert_called_once_with(b"pngdata")
        render_terminal.assert_called_once_with(b"pngdata")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
