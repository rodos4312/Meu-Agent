"""Render a self-contained SVG as a PNG using an isolated local Chromium."""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

MAX_SVG_BYTES = 8 * 1024 * 1024
MAX_SIDE = 4096
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


async def _capture(cdp_url: str, svg: bytes, width: int, height: int) -> bytes:
    from tools.browser_cdp_tool import _WS_AVAILABLE, _cdp_call

    if not _WS_AVAILABLE:
        raise RuntimeError("The local Chromium connection requires the Meu runtime's WebSocket support.")

    target = await _cdp_call(cdp_url, "Target.createTarget", {"url": "about:blank"}, None, 10)
    target_id = target["targetId"]

    async def call(method, **params):
        return await _cdp_call(cdp_url, method, params, target_id, 10)

    await call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
    frame = await call("Page.getFrameTree")
    encoded_svg = base64.b64encode(svg).decode("ascii")
    # Chromium's SVG image mode disables script and external resources in the
    # artwork. Never navigate directly to the SVG as an active document.
    html = (
        '<!doctype html><meta http-equiv="Content-Security-Policy" '
        'content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'">'
        '<style>body{margin:0} img{display:block;width:100vw;height:100vh;object-fit:contain}</style>'
        f'<img src="data:image/svg+xml;base64,{encoded_svg}">'
    )
    await call("Page.setDocumentContent", frameId=frame["frameTree"]["frame"]["id"], html=html)
    decoded = await call(
        "Runtime.evaluate",
        expression="document.images[0].decode().then(() => true)",
        awaitPromise=True,
        returnByValue=True,
    )
    if decoded.get("result", {}).get("value") is not True:
        raise ValueError("Chromium could not decode the SVG.")
    shot = await call("Page.captureScreenshot", format="png", captureBeyondViewport=False)
    return base64.b64decode(shot["data"], validate=True)


def render_png(source: Path, output: Path, width: int, height: int) -> Path:
    if source.suffix.lower() != ".svg" or output.suffix.lower() != ".png":
        raise ValueError("Provide a .svg source and a .png output path.")
    if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
        raise ValueError(f"Width and height must each be between 1 and {MAX_SIDE} pixels.")
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    if not source.is_file():
        raise ValueError("The SVG source must be a regular file.")
    with source.open("rb") as stream:
        svg = stream.read(MAX_SVG_BYTES + 1)
    if len(svg) > MAX_SVG_BYTES:
        raise ValueError("The SVG source must be at most 8 MiB.")

    from hermes_cli.browser_runtime import chromium_executable
    from tools.browser_launcher import launch_chromium, stop_browser

    executable = chromium_executable(allow_override=False)
    if executable is None:
        raise RuntimeError("Local Chromium is required. Run `hermes pm install chromium` to install it.")
    # This CLI invocation owns one fresh, headless profile. Supplying the
    # resolved executable also avoids the launcher's auto-install path.
    key = "render-png"
    browser, error = launch_chromium(key, executable=executable, headed=False, timeout=15)
    if browser is None:
        raise RuntimeError(error or "Could not start local Chromium.")
    try:
        png = asyncio.run(_capture(browser.cdp_url, svg, width, height))
    finally:
        stop_browser(key)
    if not png.startswith(PNG_SIGNATURE):
        raise RuntimeError("Chromium did not return a PNG.")

    stream = output.open("xb")
    try:
        with stream:
            stream.write(png)
    except OSError:
        output.unlink()
        raise
    return output.resolve()


def cmd_render_png(args) -> int:
    try:
        output = render_png(Path(args.source), Path(args.output), args.width, args.height)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"PNG export failed: {error}", file=sys.stderr)
        return 1
    print(f"MEDIA:{output}")
    return 0
