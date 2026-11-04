"""``hermes browser`` subcommand parser."""

from __future__ import annotations

import sys


def build_browser_parser(subparsers) -> None:
    """Attach the ``browser`` subcommand to ``subparsers``."""
    browser_parser = subparsers.add_parser(
        "browser", help="Browser utilities, including local PNG export",
        description="Export SVG artwork locally or manage real-profile browsing (browser.use_real_profile). "
            "close-profile terminates the browser process tree holding your "
            "default profile so Hermes can copy it — DESTRUCTIVE (unsaved tabs "
            "in that browser are lost). The agent runs this only after you "
            "approve closing the browser.")
    browser_subparsers = browser_parser.add_subparsers(dest="browser_action")
    browser_close = browser_subparsers.add_parser(
        "close-profile",
        help="Close the browser locking your real profile (asks nothing — "
             "run only with the user's explicit OK; loses unsaved tabs)")
    browser_close.add_argument(
        "--browser",
        help="Override detected default browser (chrome/edge/brave/brave-origin/chromium)")

    render_png = browser_subparsers.add_parser("render-png", help="Render a self-contained SVG to PNG locally")
    render_png.add_argument("source", help="SVG input file")
    render_png.add_argument("output", help="New PNG output file")
    render_png.add_argument("--width", type=int, required=True, help="Output width in pixels")
    render_png.add_argument("--height", type=int, required=True, help="Output height in pixels")

    def _dispatch_render_png(args):
        from hermes_cli.browser_render_png import cmd_render_png

        return cmd_render_png(args)

    render_png.set_defaults(func=_dispatch_render_png)

    def _dispatch_browser(_args):
        from hermes_cli.browser_connect import (
            UNSUPPORTED_CHANNEL, close_browser_holding_profile, detect_default_chromium,
            real_profile_data_dir)

        action = getattr(_args, "browser_action", None)
        if action != "close-profile":
            browser_parser.print_help()
            return 2
        browser = getattr(_args, "browser", None) or detect_default_chromium()
        if not browser or browser == UNSUPPORTED_CHANNEL:
            print("✗ No supported Chromium default browser detected.", file=sys.stderr)
            return 1
        src = real_profile_data_dir(browser)
        if not src:
            print(f"✗ Could not resolve the {browser} profile directory.", file=sys.stderr)
            return 1
        closed, msg = close_browser_holding_profile(src)
        if closed:
            print(f"✓ {msg}")
            return 0
        print(f"✗ {msg}", file=sys.stderr)
        return 1

    browser_parser.set_defaults(func=_dispatch_browser)
