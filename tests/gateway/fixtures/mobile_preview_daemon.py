"""Boot the canonical gateway with its temporary phone listener restricted to loopback."""

import ipaddress
import runpy

import gateway.mobile_preview as mobile

mobile.local_network = lambda: ipaddress.IPv4Interface("127.0.0.1/8")
runpy.run_module("gateway.run", run_name="__main__")
