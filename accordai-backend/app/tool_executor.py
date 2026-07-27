"""Validation and execution of client-defined external tools.

Clients supply arbitrary endpoint URLs that this server will request, so every
URL is SSRF-validated both when the tool is created and again right before each
execution (DNS records can change between the two).

Known residual risk: TOCTOU DNS rebinding — a hostile DNS server could return a
public IP to our check and a private IP to httpx's own lookup moments later.
The full defense (pin the validated IP and connect to it with a Host header) is
out of scope for now; redirects are disabled so a redirect can't bypass us.
"""
import ipaddress
import socket
from typing import Tuple
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.models import ClientTool
from app.security import decrypt_credential
import logging

logger = logging.getLogger(__name__)
settings = get_settings()

ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    """Raised when a tool endpoint URL fails SSRF validation."""


def validate_endpoint_url(url: str) -> None:
    """Reject URLs that could reach internal/private infrastructure.

    Raises UnsafeURLError with a caller-safe message; passes silently if OK.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"URL scheme must be http or https, got '{parsed.scheme or 'none'}'")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no hostname")
    if parsed.username or parsed.password:
        raise UnsafeURLError("URLs with embedded credentials are not allowed")

    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeURLError("localhost endpoints are not allowed")

    if settings.ALLOW_PRIVATE_TOOL_URLS:
        # Dev/test escape hatch — never enable in production.
        return

    try:
        addr_infos = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise UnsafeURLError(f"Could not resolve hostname '{hostname}'")

    # Every resolved address (IPv4 and IPv6) must be globally routable.
    # `not is_global` covers 10/8, 172.16/12, 192.168/16, 127/8, 169.254/16
    # (cloud metadata), 100.64/10, 0.0.0.0, ::1, fc00::/7, fe80::/10, etc.
    for info in addr_infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise UnsafeURLError(
                f"Endpoint resolves to a private/reserved address ({ip}); not allowed"
            )


def _build_auth_headers(tool: ClientTool) -> dict:
    if tool.auth_type == "none" or not tool.auth_credential:
        return {}
    credential = decrypt_credential(tool.auth_credential)
    if tool.auth_type == "bearer":
        return {"Authorization": f"Bearer {credential}"}
    if tool.auth_type == "api_key_header":
        return {tool.auth_header_name or "X-API-Key": credential}
    logger.warning(f"Unknown auth_type '{tool.auth_type}' on tool {tool.id}; sending no auth")
    return {}


async def execute_client_tool(tool: ClientTool, arguments: dict) -> Tuple[bool, dict]:
    """Call the client's external API. Returns (success, result_dict).

    Never raises — failures come back as (False, {"error": ...}) so a live
    phone call is never crashed by a client's flaky endpoint.
    """
    try:
        validate_endpoint_url(tool.endpoint_url)
    except UnsafeURLError as e:
        logger.error(f"Tool {tool.name} (id={tool.id}) URL failed validation at call time: {e}")
        return False, {"error": f"Endpoint URL rejected: {e}"}

    method = (tool.http_method or "POST").upper()
    headers = _build_auth_headers(tool)

    logger.info(f"Executing tool '{tool.name}' (id={tool.id}) {method} {tool.endpoint_url} args={arguments}")

    try:
        async with httpx.AsyncClient(
            timeout=settings.TOOL_HTTP_TIMEOUT,
            follow_redirects=False
        ) as http:
            if method == "GET":
                resp = await http.request(method, tool.endpoint_url, params=arguments, headers=headers)
            else:
                resp = await http.request(method, tool.endpoint_url, json=arguments, headers=headers)
    except httpx.TimeoutException:
        logger.warning(f"Tool '{tool.name}' timed out after {settings.TOOL_HTTP_TIMEOUT}s")
        return False, {"error": "The service did not respond in time."}
    except httpx.HTTPError as e:
        logger.warning(f"Tool '{tool.name}' request failed: {type(e).__name__}: {e}")
        return False, {"error": "Could not reach the service."}

    if resp.status_code >= 300:
        logger.warning(f"Tool '{tool.name}' returned HTTP {resp.status_code}: {resp.text[:500]}")
        return False, {"error": f"The service returned an error (HTTP {resp.status_code})."}

    try:
        return True, resp.json()
    except ValueError:
        # Non-JSON 2xx response — still a success, pass the text through.
        return True, {"result": resp.text[:1000]}
