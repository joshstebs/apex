"""Process-level egress guard for offline Python checks."""

import ipaddress
import sys


def install_egress_guard():
    def check(event, args):
        if event in ("socket.connect", "socket.sendto"):
            address = args[1]
            host = address[0] if isinstance(address, tuple) else None
        elif event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"):
            host = args[0]
        else:
            return

        if host in (None, "localhost"):
            return
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise AssertionError("Offline QA blocked a non-loopback network request")

    sys.addaudithook(check)
