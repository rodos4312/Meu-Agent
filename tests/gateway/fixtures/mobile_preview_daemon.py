"""Boot the canonical gateway with its temporary phone listener restricted to loopback."""

import ipaddress
import runpy

import gateway.mobile_preview as mobile
from tools import web_tools


async def fixture_web_extract(urls, _format, char_limit=None):
    assert urls == ["https://example.com/mobile-weather"]
    return '{"results":[{"url":"https://example.com/mobile-weather","content":"fixture forecast"}]}'

mobile.local_network = lambda: ipaddress.IPv4Interface("127.0.0.1/8")
mobile.tailscale_network = mobile.local_network
web_tools.web_extract_tool = fixture_web_extract
runpy.run_module("gateway.run", run_name="__main__")
