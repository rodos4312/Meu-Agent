"""Permit only the fixture's loopback address in persisted private endpoint checks."""
import ipaddress
from pathlib import Path
import runpy

import gateway.mobile_preview as mobile

mobile.PRIVATE_NETWORKS += (ipaddress.IPv4Network('127.0.0.0/8'),)
runpy.run_path(str(Path(__file__).with_name('mobile_preview_daemon.py')), run_name='__main__')
