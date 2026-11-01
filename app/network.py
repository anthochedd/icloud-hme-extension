"""Discover server addresses and validate the URL used by browser clients."""
import ipaddress
import json
import os
import socket
import subprocess
from urllib.parse import urlsplit

import psutil

PORT = int(os.getenv("IHME_PORT", "8001"))


def validate_server_url(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path or any(c.isspace() for c in value)):
            raise ValueError
        parsed.port
    except ValueError:
        raise ValueError("Enter an http(s) server URL without a path, credentials or query.") from None
    return value


def network_info():
    candidates = [{"label": "This computer (localhost)", "url": f"http://127.0.0.1:{PORT}"}]
    tailscale_ip = None
    try:
        result = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            tailscale_ip = str(ipaddress.IPv4Address(result.stdout.strip().splitlines()[0]))
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        pass
    local_ip = "127.0.0.1"
    host_addresses = []
    try:
        supplied = json.loads(os.getenv("IHME_HOST_ADDRESSES") or "[]")
        if isinstance(supplied, list):
            host_addresses = supplied
    except (ValueError, TypeError):
        pass
    interfaces = []
    for item in host_addresses:
        if not isinstance(item, dict):
            continue
        try:
            ip = ipaddress.IPv4Address(item.get("address", ""))
        except (ValueError, TypeError):
            continue
        interfaces.append((str(item.get("name") or "Host interface"), ip))
    using_host_addresses = bool(interfaces)
    # Container interfaces are not useful extension endpoints when host addresses are supplied.
    if not using_host_addresses:
        for name, addresses in psutil.net_if_addrs().items():
            for address in addresses:
                if address.family == socket.AF_INET:
                    interfaces.append((name, ipaddress.IPv4Address(address.address)))
    for name, ip in interfaces:
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            continue
        is_tail = "tailscale" in name.lower() or str(ip) == tailscale_ip
        if is_tail:
            tailscale_ip = str(ip)
        elif local_ip == "127.0.0.1":
            local_ip = str(ip)
        candidates.append({"label": f"{'Tailscale' if is_tail else 'LAN / interface'}: {name} ({ip})",
                           "url": f"http://{ip}:{PORT}"})
    if tailscale_ip:
        candidates.append({"label": "Tailscale", "url": f"http://{tailscale_ip}:{PORT}"})
    unique = {item["url"]: item for item in candidates}
    return {"candidates": list(unique.values()), "local_ip": local_ip,
            "host_addresses_supplied": using_host_addresses,
            "container": os.path.exists("/.dockerenv"),
            "tailscale_ip": tailscale_ip, "port": PORT,
            "local_url": f"http://127.0.0.1:{PORT}",
            "lan_url": f"http://{local_ip}:{PORT}",
            "tailscale_url": f"http://{tailscale_ip}:{PORT}" if tailscale_ip else None}
