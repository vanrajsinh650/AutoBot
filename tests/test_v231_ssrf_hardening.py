"""
Unit and Integration Tests for Phase 4: SSRF Hardening & Stream Protection.
Validates:
1. DNS-rebinding and connected peer address validation.
2. HTTP redirect destination and scheme validation.
3. Complete RFC 6052 / RFC 8215 NAT64 prefix extraction and rejection of embedded private IPs.
4. Streaming decompressed byte limit enforcement against decompression bombs and oversized JSON.
5. Content-Length pre-check enforcement.
"""

import asyncio
import ipaddress
import json
from unittest.mock import AsyncMock, MagicMock
import pytest

from src.discovery.models import SourceType
from src.discovery.security import (
    MAX_RESPONSE_BYTES,
    SSRFValidationError,
    extract_rfc6052_ipv4,
    is_ip_safe_for_egress,
    safe_read_json,
    validate_ats_url,
    validate_connected_peer,
    validate_redirect_target,
)


def test_rfc6052_and_rfc8215_nat64_extraction_and_safety():
    """Verify RFC 6052 & RFC 8215 NAT64 prefixes extract embedded IPv4 and reject private targets."""
    # 1. Well-known prefix /96 (64:ff9b::/96)
    # Embedded public IP (8.8.8.8) -> Safe
    safe_v6_96 = "64:ff9b::8.8.8.8"
    assert is_ip_safe_for_egress(safe_v6_96) is True

    # Embedded private IP (10.0.0.1) -> REJECTED
    priv_v6_96 = "64:ff9b::10.0.0.1"
    assert is_ip_safe_for_egress(priv_v6_96) is False

    # Embedded loopback (127.0.0.1) -> REJECTED
    loop_v6_96 = "64:ff9b::127.0.0.1"
    assert is_ip_safe_for_egress(loop_v6_96) is False

    # Embedded AWS/GCP metadata (169.254.169.254) -> REJECTED
    meta_v6_96 = "64:ff9b::169.254.169.254"
    assert is_ip_safe_for_egress(meta_v6_96) is False

    # 2. RFC 8215 Local-Use Well-Known Prefix /48 (64:ff9b:1::/48)
    # 64:ff9b:1 = bytes [0x00, 0x64, 0xff, 0x9b, 0x00, 0x01]
    # Embedded 192.168.1.1 (private)
    raw_priv_48 = bytes([0x00, 0x64, 0xff, 0x9b, 0x00, 0x01, 192, 168, 0, 1, 1, 0, 0, 0, 0, 0])
    v6_priv_48 = str(ipaddress.IPv6Address(raw_priv_48))
    assert is_ip_safe_for_egress(v6_priv_48) is False

    # Embedded 1.1.1.1 (public)
    raw_pub_48 = bytes([0x00, 0x64, 0xff, 0x9b, 0x00, 0x01, 1, 1, 0, 1, 1, 0, 0, 0, 0, 0])
    v6_pub_48 = str(ipaddress.IPv6Address(raw_pub_48))
    assert is_ip_safe_for_egress(v6_pub_48) is True

    # 3. Test extraction for all supported prefix lengths (32, 40, 48, 56, 64, 96)
    target_v4 = ipaddress.IPv4Address("198.51.100.2")  # TEST-NET-2
    # /32: raw[4:8]
    raw_32 = bytearray(16)
    raw_32[4:8] = target_v4.packed
    assert extract_rfc6052_ipv4(ipaddress.IPv6Address(bytes(raw_32)), 32) == target_v4

    # /40: raw[5:8] + raw[9:10]
    raw_40 = bytearray(16)
    raw_40[5:8] = target_v4.packed[:3]
    raw_40[9] = target_v4.packed[3]
    assert extract_rfc6052_ipv4(ipaddress.IPv6Address(bytes(raw_40)), 40) == target_v4

    # /56: raw[7:8] + raw[9:12]
    raw_56 = bytearray(16)
    raw_56[7] = target_v4.packed[0]
    raw_56[9:12] = target_v4.packed[1:]
    assert extract_rfc6052_ipv4(ipaddress.IPv6Address(bytes(raw_56)), 56) == target_v4

    # /64: raw[9:13]
    raw_64 = bytearray(16)
    raw_64[9:13] = target_v4.packed
    assert extract_rfc6052_ipv4(ipaddress.IPv6Address(bytes(raw_64)), 64) == target_v4


def test_connected_peer_validation():
    """Verify connected socket peer IP is checked, catching DNS rebinding TOCTOU attacks."""
    # Mock response with safe connected peer (e.g. Cloudflare public IP 104.16.1.1)
    mock_safe_resp = MagicMock()
    mock_safe_resp.connection.transport.get_extra_info.return_value = ("104.16.1.1", 443)
    # Should pass without exception
    validate_connected_peer(mock_safe_resp)

    # Mock response with re-bound loopback peer (127.0.0.1)
    mock_loop_resp = MagicMock()
    mock_loop_resp.connection.transport.get_extra_info.return_value = ("127.0.0.1", 443)
    with pytest.raises(SSRFValidationError, match="Connected peer IP address '127.0.0.1' is prohibited"):
        validate_connected_peer(mock_loop_resp)

    # Mock response with re-bound metadata service peer (169.254.169.254)
    mock_meta_resp = MagicMock()
    mock_meta_resp.connection.transport.get_extra_info.return_value = ("169.254.169.254", 443)
    with pytest.raises(SSRFValidationError, match="Connected peer IP address '169.254.169.254' is prohibited"):
        validate_connected_peer(mock_meta_resp)


def test_redirect_validation_blocks_unsafe_destinations():
    """Verify validate_redirect_target rejects non-HTTPS, unapproved domains, and internal destinations."""
    orig = "https://boards-api.greenhouse.io/v1/boards/stripe/jobs"

    # Relative redirect to valid path on same domain -> PASS
    valid_redirect = validate_redirect_target(orig, "/v1/boards/stripe/jobs?page=2", expected_source_type=SourceType.GREENHOUSE)
    assert valid_redirect == "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?page=2"

    # Redirect to internal metadata service -> REJECT
    with pytest.raises(SSRFValidationError):
        validate_redirect_target(orig, "http://169.254.169.254/latest/meta-data/", expected_source_type=SourceType.GREENHOUSE)

    # Redirect to non-HTTPS scheme -> REJECT
    with pytest.raises(SSRFValidationError, match="Insecure scheme 'http'"):
        validate_redirect_target(orig, "http://boards-api.greenhouse.io/test", expected_source_type=SourceType.GREENHOUSE)

    # Redirect to external unapproved domain -> REJECT
    with pytest.raises(SSRFValidationError, match="not a permitted public ATS endpoint"):
        validate_redirect_target(orig, "https://attacker.com/steal-creds", expected_source_type=SourceType.GREENHOUSE)


@pytest.mark.asyncio
async def test_streaming_decompressed_bytes_limit_prevents_bombs():
    """Verify safe_read_json enforces limit on decompressed bytes as chunks arrive without RAM exhaustion."""
    # Simulated decompression bomb: small compressed chunk expands into infinite/oversized stream
    mock_stream = AsyncMock()
    chunk_100kb = b"A" * (100 * 1024)

    # Yields 15 chunks of 100 KB = 1.5 MB with a max limit set to 500 KB
    mock_stream.read.side_effect = [chunk_100kb] * 15

    mock_resp = MagicMock()
    mock_resp.headers = {}
    mock_resp.connection = None
    mock_resp.content = mock_stream

    # Reading with max_bytes = 500 KB should abort on chunk 6 and raise SSRFValidationError
    with pytest.raises(SSRFValidationError, match="Decompressed response stream exceeded maximum allowed size"):
        await safe_read_json(mock_resp, max_bytes=500 * 1024)


@pytest.mark.asyncio
async def test_content_length_pre_check():
    """Verify safe_read_json aborts before streaming if Content-Length header is oversized."""
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": str(20 * 1024 * 1024)}  # 20 MB
    mock_resp.connection = None

    with pytest.raises(SSRFValidationError, match="Response Content-Length"):
        await safe_read_json(mock_resp, max_bytes=10 * 1024 * 1024)
