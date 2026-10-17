"""SSRF guard — validate that an outbound URL points at a public host.

Blocks that fetch or POST to caller-supplied URLs (``web``, ``webhook``) use
this so a caller cannot make the server reach loopback, link-local (cloud
metadata at 169.254.169.254), or private-network addresses.

Two entry points:

``validate_public_url(url)``
    The rule for a CALLER-supplied URL: http/https, resolvable, every
    resolved address public. Unchanged.

``validate_outbound_url(url, allow_private_hosts=False)``
    The rule for an OPERATOR-configured URL (an env var such as
    ``NOTIFY_WEBHOOK_URL``). With ``allow_private_hosts=False`` it is the
    caller rule. With ``True`` -- which only an operator env flag may set --
    loopback and RFC-1918 destinations are permitted, because an operator's
    own sink is legitimately on the same host or network. Link-local
    (169.254.0.0/16, fe80::/10: the cloud-metadata range), multicast,
    unspecified and reserved addresses stay refused in every mode; the seam
    widens the guard, it never removes it.
"""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """Raised when a URL is not safe to request (bad scheme or private host)."""


def _parse_ip(ip_str: str):
    """The address, or None when the resolver handed back something that is
    not one (an unparseable address is refused, never trusted)."""
    try:
        return ipaddress.ip_address(ip_str)
    except ValueError:
        ip = None
    return ip


def _is_public_ip(ip_str: str) -> bool:
    ip = _parse_ip(ip_str)
    if ip is None:
        return False
    # is_global is False for private, loopback, link-local and reserved ranges.
    return ip.is_global and not ip.is_multicast


def _is_operator_reachable_ip(ip_str: str) -> bool:
    """Public, loopback or private unicast -- never link-local/metadata."""
    ip = _parse_ip(ip_str)
    if ip is None:
        return False
    if ip.is_multicast or ip.is_link_local or ip.is_unspecified:
        return False
    if ip.is_reserved and not ip.is_private:
        return False
    return ip.is_global or ip.is_loopback or ip.is_private


def validate_outbound_url(url: str, allow_private_hosts: bool = False) -> str:
    """Return the URL stripped if it is safe to request, else raise.

    Safe means: an ``http``/``https`` scheme, a resolvable hostname, and every
    resolved IP address acceptable for the mode (see module docstring).
    """
    if not isinstance(url, str) or not url.strip():
        raise UnsafeURLError("A URL is required")
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(
            f"Only http/https URLs are allowed (got {parsed.scheme or 'none'!r})"
        )
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURLError(f"Cannot resolve host {host!r}: {e}")
    if not infos:
        raise UnsafeURLError(f"Cannot resolve host {host!r}")
    accept = _is_operator_reachable_ip if allow_private_hosts else _is_public_ip
    for info in infos:
        ip_str = info[4][0]
        if not accept(ip_str):
            what = "a link-local/reserved" if allow_private_hosts else "a non-public"
            raise UnsafeURLError(
                f"URL host {host!r} resolves to {what} address ({ip_str})"
            )
    return url


def validate_public_url(url: str) -> str:
    """Return the URL stripped if it is safe to request, else raise.

    Safe means: an ``http``/``https`` scheme, a resolvable hostname, and every
    resolved IP address is a public (global) unicast address.
    """
    return validate_outbound_url(url, allow_private_hosts=False)
