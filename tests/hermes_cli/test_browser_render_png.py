from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from hermes_cli import browser_render_png, browser_runtime
from tools import browser_launcher


@pytest.fixture
def local_capture(monkeypatch):
    capture = AsyncMock(return_value=browser_render_png.PNG_SIGNATURE + b"fixture")
    browser = SimpleNamespace(cdp_url="ws://127.0.0.1:12345")
    stop = Mock()
    monkeypatch.setattr(browser_runtime, "chromium_executable", lambda *, allow_override: "chromium")
    monkeypatch.setattr(browser_launcher, "launch_chromium", lambda *args, **kwargs: (browser, None))
    monkeypatch.setattr(browser_launcher, "stop_browser", stop)
    monkeypatch.setattr(browser_render_png, "_capture", capture)
    return capture, stop


def test_render_delivers_media_path_and_preserves_an_existing_file(tmp_path, capsys, local_capture):
    source = tmp_path / "card source.svg"
    source.write_bytes(b"<svg/>")
    output = tmp_path / "birthday card.png"
    args = SimpleNamespace(source=source, output=output, width=600, height=320)
    capture, stop = local_capture

    assert browser_render_png.cmd_render_png(args) == 0
    assert capsys.readouterr().out.strip() == f"MEDIA:{output.resolve()}"
    assert output.read_bytes() == capture.return_value
    capture.assert_awaited_once_with("ws://127.0.0.1:12345", b"<svg/>", 600, 320)
    stop.assert_called_once_with("render-png")

    assert browser_render_png.cmd_render_png(args) == 1
    assert capsys.readouterr().out == ""
    assert output.read_bytes() == capture.return_value
    capture.assert_awaited_once()


def test_failed_capture_closes_chromium_and_does_not_publish_media(tmp_path, capsys, local_capture):
    source = tmp_path / "broken.svg"
    source.write_bytes(b"broken")
    output = tmp_path / "broken.png"
    args = SimpleNamespace(source=source, output=output, width=600, height=320)
    capture, stop = local_capture
    capture.side_effect = ValueError("Could not decode the SVG")

    assert browser_render_png.cmd_render_png(args) == 1
    assert capsys.readouterr().out == ""
    assert not output.exists()
    stop.assert_called_once_with("render-png")
