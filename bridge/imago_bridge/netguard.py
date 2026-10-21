"""Network guard (D-19, B-06): the bridge only talks to literal private IPv4 printer hosts."""
import ipaddress
from typing import Optional
from urllib.parse import urlsplit


def is_allowed_host(host: object) -> bool:
    """True only for a literal private IPv4 address that is a real unicast LAN host.

    DNS names are refused on purpose: a name can be re-pointed (DNS rebinding) after
    Odoo validated it. Loopback, link-local, multicast, unspecified, reserved and the
    limited broadcast address are refused even though ``is_private`` covers some of them.
    """
    if not isinstance(host, str) or host != host.strip() or not host:
        return False
    try:
        address = ipaddress.IPv4Address(host)
    except ValueError:
        return False
    if not address.is_private:
        return False
    return not (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or address == ipaddress.IPv4Address("255.255.255.255")
    )


def camera_host(camera_url: object, printer_host: str) -> Optional[str]:
    """The camera host when ``camera_url`` is plain http on the printer's own allowed host."""
    if not isinstance(camera_url, str) or not camera_url:
        return None
    try:
        parts = urlsplit(camera_url)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on an invalid port
    except ValueError:
        return None
    if parts.scheme != "http" or parts.username or parts.password:
        return None
    if host != printer_host or not is_allowed_host(host):
        return None
    return host
