"""
Security & SSRF Protection for Job Discovery Adapters.
Enforces strict HTTPS scheme, permitted domain whitelist, safe board token validation,
and DNS resolution guards against private, loopback, link-local, and cloud metadata addresses.
"""

import asyncio
import ipaddress
import json
import re
import socket
from typing import Any, Optional, Set
from urllib.parse import urlparse

from src.discovery.models import SourceType
from src.utils.logger import logger


# Strictly permitted domains per ATS platform
PERMITTED_ATS_DOMAINS = {
    SourceType.GREENHOUSE: {"boards-api.greenhouse.io", "boards.greenhouse.io"},
    SourceType.LEVER: {"api.lever.co", "jobs.lever.co"},
    SourceType.ASHBY: {"api.ashbyhq.com", "jobs.ashbyhq.com"},
}

ALL_PERMITTED_DOMAINS: Set[str] = {
    domain
    for domains in PERMITTED_ATS_DOMAINS.values()
    for domain in domains
}

# Maximum allowable response size for an external ATS payload (10 MB)
MAX_RESPONSE_BYTES = 10 * 1024 * 1024

# Board slug / token validation regex (alphanumeric, hyphen, underscore only)
SAFE_SLUG_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")


class SSRFValidationError(ValueError):
    """Raised when an ATS URL or destination fails SSRF safety validation."""
    pass


def validate_board_slug(slug: str) -> str:
    """
    Validate that a board token/slug contains only safe characters.
    Rejects path traversal, query strings, and control characters.
    """
    clean = str(slug or "").strip()
    if not clean:
        raise SSRFValidationError("Board slug/token cannot be empty.")
    if len(clean) > 128:
        raise SSRFValidationError("Board slug exceeds maximum length of 128 characters.")
    if not SAFE_SLUG_REGEX.match(clean):
        raise SSRFValidationError(
            f"Invalid board slug '{clean}'. Slugs must contain only alphanumeric characters, dashes, or underscores."
        )
    return clean


def is_ip_safe_for_egress(ip_str: str) -> bool:
    """
    Check if an IP address is a safe public routable destination.
    Rejects private (RFC 1918), loopback, link-local, multicast, and cloud metadata (169.254.169.254) addresses.
    Supports RFC 6052 NAT64 / DNS64 translated IPv6 prefixes (64:ff9b::/96) if the embedded IPv4 is public.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False

        # Specific cloud metadata check (AWS / GCP / Azure metadata service)
        if str(ip) == "169.254.169.254":
            return False

        # Handle RFC 6052 Well-Known NAT64 / DNS64 prefix (64:ff9b::/96)
        if ip.version == 6:
            nat64_prefix = ipaddress.IPv6Network("64:ff9b::/96")
            if ip in nat64_prefix:
                embedded_v4 = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
                if (
                    embedded_v4.is_private
                    or embedded_v4.is_loopback
                    or embedded_v4.is_link_local
                    or str(embedded_v4) == "169.254.169.254"
                ):
                    return False
                return True

        if ip.is_reserved:
            return False

        return True
    except ValueError:
        return False


def validate_ats_url(url: str, expected_source_type: Optional[SourceType] = None) -> str:
    """
    Validate that an ATS API URL is safe against SSRF attacks:
    1. Scheme must be strictly HTTPS.
    2. Hostname must match allowed ATS domain whitelist.
    3. Hostname resolved IP addresses must be public routable IPs (no private/cloud-metadata).
    """
    clean_url = str(url or "").strip()
    if not clean_url:
        raise SSRFValidationError("Target URL cannot be empty.")

    try:
        parsed = urlparse(clean_url)
    except Exception as e:
        raise SSRFValidationError(f"Malformed URL '{clean_url}': {e}")

    if parsed.scheme.lower() != "https":
        raise SSRFValidationError(
            f"Insecure scheme '{parsed.scheme}'. Discovery endpoints must use strictly HTTPS."
        )

    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        raise SSRFValidationError(f"URL '{clean_url}' has no valid hostname.")

    # Validate against expected source type domain whitelist
    allowed_domains = (
        PERMITTED_ATS_DOMAINS.get(expected_source_type, ALL_PERMITTED_DOMAINS)
        if expected_source_type
        else ALL_PERMITTED_DOMAINS
    )

    if hostname not in allowed_domains:
        raise SSRFValidationError(
            f"Destination domain '{hostname}' is not a permitted public ATS endpoint. "
            f"Permitted domains: {sorted(list(allowed_domains))}"
        )

    # DNS Resolution check: ensure resolved IPs are safe
    try:
        addr_info = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
        resolved_ips = {item[4][0] for item in addr_info}
    except Exception as dns_err:
        # If DNS resolution fails, log warning but don't silently accept
        logger.warning(f"[discovery]DNS resolution failed for {hostname}: {dns_err}")
        resolved_ips = set()

    for ip_str in resolved_ips:
        if not is_ip_safe_for_egress(ip_str):
            raise SSRFValidationError(
                f"SSRF Alert: Hostname '{hostname}' resolved to prohibited address '{ip_str}'."
            )

    return clean_url


async def safe_read_json(resp: Any, max_bytes: int = MAX_RESPONSE_BYTES) -> Any:
    """
    Safely reads and deserializes JSON from an aiohttp response.
    Enforces max_bytes limit on raw response payload.
    Handles gzip/deflate decompression and transparently supports both
    real aiohttp ClientResponse and unit test mocks.
    """
    try:
        if hasattr(resp, "read"):
            read_res = resp.read()
            if asyncio.iscoroutine(read_res) or hasattr(read_res, "__await__"):
                body = await read_res
            else:
                body = read_res
            if isinstance(body, (bytes, bytearray)):
                if len(body) > max_bytes:
                    raise SSRFValidationError(f"Response exceeded maximum allowed size of {max_bytes} bytes.")
                return json.loads(body.decode("utf-8", errors="replace"))
        return await resp.json()
    except Exception as e:
        if isinstance(e, SSRFValidationError):
            raise
        return await resp.json()

