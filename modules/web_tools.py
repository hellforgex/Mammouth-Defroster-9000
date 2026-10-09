import re
import ipaddress
import socket
import urllib.parse
import httpx
from typing import Dict, Any


def _resolve_and_validate_ip(hostname: str) -> str:
    """Resolve hostname and strictly validate against private, loopback, link-local, and cloud metadata IPs."""
    blocked_hosts = {"localhost", "metadata.google.internal", "instance-data", "169.254.169.254"}
    if hostname.lower() in blocked_hosts or hostname.endswith(".localhost"):
        raise PermissionError(f"SSRF Shield: Access to '{hostname}' is blocked for security.")

    try:
        addr_info = socket.getaddrinfo(hostname, None)
        if not addr_info:
            raise ValueError(f"Could not resolve hostname '{hostname}'.")
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                raise PermissionError(f"SSRF Shield: Resolved IP address '{ip_str}' for host '{hostname}' belongs to private/restricted IP range.")
        # Return first validated IP
        return addr_info[0][4][0]
    except PermissionError:
        raise
    except Exception as e:
        raise ValueError(f"Could not resolve hostname '{hostname}': {e}")


def _validate_url_ssrf_safe(url: str) -> str:
    """Validate that URL scheme is http/https and resolved IP is public."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme '{parsed.scheme}'. Only http:// and https:// are permitted.")
    
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL: missing hostname.")

    return _resolve_and_validate_ip(hostname)


_MAX_REDIRECTS = 5
_MAX_BODY_BYTES = 5 * 1024 * 1024  # 5 MB: more than enough for any page we turn into text


def _pinned_get(url: str, timeout: float, headers: Dict[str, str], max_bytes: int = _MAX_BODY_BYTES):
    """GET with DNS pinning: connect to the IP that was validated, not to a fresh DNS answer.

    Validating a hostname and then letting httpx resolve it again allows DNS rebinding (a TTL-0
    record that answers 1.2.3.4 for the check and 127.0.0.1 for the request). Here every hop
    (including each redirect) is resolved+validated once, and the request goes to that IP with the
    original Host header and TLS SNI/certificate check against the real hostname.
    Returns (final_url, status_code, response_headers, body_bytes, truncated, elapsed_seconds).
    """
    import time as _time
    current_url = url
    started = _time.monotonic()
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            parsed = urllib.parse.urlparse(current_url)
            pinned_ip = _validate_url_ssrf_safe(current_url)
            host_for_url = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
            netloc = host_for_url + (f":{parsed.port}" if parsed.port else "")
            pinned_url = urllib.parse.urlunparse(parsed._replace(netloc=netloc))
            req_headers = dict(headers)
            req_headers["Host"] = parsed.netloc.split("@")[-1]
            request = client.build_request("GET", pinned_url, headers=req_headers,
                                           extensions={"sni_hostname": parsed.hostname})
            resp = client.send(request, stream=True)
            try:
                if resp.is_redirect and "location" in resp.headers:
                    current_url = urllib.parse.urljoin(current_url, resp.headers["location"])
                    continue
                body = bytearray()
                truncated = False
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        truncated = True
                        break
                return current_url, resp.status_code, resp.headers, bytes(body[:max_bytes]), truncated, _time.monotonic() - started
            finally:
                resp.close()
    raise ValueError(f"Too many redirects (>{_MAX_REDIRECTS}).")


def _check_redirect_ssrf(response: httpx.Response):
    """Event hook to validate every redirect target URL against SSRF and DNS rebinding."""
    if response.is_redirect and "location" in response.headers:
        redir_url = response.headers["location"]
        if not redir_url.startswith("http://") and not redir_url.startswith("https://"):
            redir_url = urllib.parse.urljoin(str(response.url), redir_url)
        _validate_url_ssrf_safe(redir_url)


def web_fetch_url(url: str, max_length: int = 25000) -> str:
    """Fetch content of a public webpage and return readable plain text/markdown (SSRF Protected).
    
    Args:
        url: Full URL to fetch (http:// or https://).
        max_length: Maximum characters to return (default 25,000).
    """
    try:
        _validate_url_ssrf_safe(url)
    except Exception as e:
        return f"Security Error (SSRF Shield): {e}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
    try:
        final_url, status_code, resp_headers, body, truncated_body, _ = _pinned_get(url, 15.0, headers)
        if status_code >= 400:
            return f"Error fetching {url}: HTTP {status_code}"

        content_type = resp_headers.get("content-type", "")
        charset_match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
        try:
            text = body.decode(charset_match.group(1) if charset_match else "utf-8", errors="replace")
        except LookupError:
            text = body.decode("utf-8", errors="replace")
        if "json" in content_type:
            return text[:max_length]

        # Remove script and style tags
        text = re.sub(r'<script.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<nav.*?</nav>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<footer.*?</footer>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # Convert links <a href="url">text</a> -> [text](url)
        text = re.sub(r'<a\s+(?:[^>]*?\s+)?href="([^"]*)"[^>]*>(.*?)</a>', r'[\2](\1)', text, flags=re.DOTALL | re.IGNORECASE)
        
        # Strip other HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        
        # Normalize whitespace
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        text = text.strip()
        
        if len(text) > max_length:
            return text[:max_length] + f"\n\n[... Truncated, total text length is {len(text)} characters ...]"
        return text if text else "Webpage returned empty content."
    except Exception as e:
        return f"Error fetching {url}: {e}"


def web_check_status(url: str) -> Dict[str, Any]:
    """Check HTTP response status, headers, and latency of any public endpoint (SSRF Protected)."""
    try:
        _validate_url_ssrf_safe(url)
    except Exception as e:
        return {"error": f"Security Error (SSRF Shield): {e}", "url": url}

    try:
        final_url, status_code, resp_headers, _, _, elapsed = _pinned_get(url, 10.0, {}, max_bytes=0)
        return {
            "status_code": status_code,
            "url": final_url,
            "is_success": 200 <= status_code < 300,
            "content_type": resp_headers.get("content-type"),
            "elapsed_ms": round(elapsed * 1000, 2)
        }
    except Exception as e:
        return {"error": str(e), "url": url}
