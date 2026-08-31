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
        with httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            headers=headers,
            event_hooks={"response": [_check_redirect_ssrf]}
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            
        content_type = resp.headers.get("content-type", "")
        if "json" in content_type:
            return resp.text[:max_length]
            
        text = resp.text
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
        with httpx.Client(
            timeout=10.0,
            follow_redirects=True,
            event_hooks={"response": [_check_redirect_ssrf]}
        ) as client:
            resp = client.get(url)
            return {
                "status_code": resp.status_code,
                "url": str(resp.url),
                "is_success": resp.is_success,
                "content_type": resp.headers.get("content-type"),
                "elapsed_ms": round(resp.elapsed.total_seconds() * 1000, 2)
            }
    except Exception as e:
        return {"error": str(e), "url": url}
