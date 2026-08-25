import re
import ipaddress
import socket
from urllib.parse import urlparse
import httpx
from typing import Dict, Any, Optional

# ==========================================
# SSRF PROTECTION
# ==========================================

# Blocked IP ranges (private networks, link-local, loopback, cloud metadata)
BLOCKED_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),      # Link-local / AWS metadata
    ipaddress.ip_network("100.64.0.0/10"),        # Tailscale CGNAT range
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),              # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),             # IPv6 private
    ipaddress.ip_network("fe80::/10"),            # IPv6 link-local
]

BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata.google.com",
}

def _validate_url_safety(url: str) -> Optional[str]:
    """Validate URL against SSRF attacks. Returns error string or None if safe."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "Error: Invalid URL format."
    
    # Only allow http and https schemes
    if parsed.scheme not in ("http", "https"):
        return f"Security Error: URL scheme '{parsed.scheme}' is not allowed. Only http:// and https:// are permitted."
    
    hostname = parsed.hostname or ""
    
    # Block known dangerous hostnames
    if hostname.lower() in BLOCKED_HOSTNAMES:
        return f"Security Error: Access to '{hostname}' is blocked (SSRF protection)."
    
    # Resolve hostname and check against blocked IP ranges
    try:
        resolved_ips = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _, _, _, _, sockaddr in resolved_ips:
            ip = ipaddress.ip_address(sockaddr[0])
            for blocked in BLOCKED_IP_RANGES:
                if ip in blocked:
                    return f"Security Error: URL resolves to private/internal IP {ip} — blocked by SSRF protection."
    except socket.gaierror:
        pass  # Let httpx handle DNS resolution failures
    except Exception:
        pass
    
    return None

def web_fetch_url(url: str, max_length: int = 25000) -> str:
    """Fetch content of a webpage and return readable plain text/markdown.
    
    Args:
        url: Full URL to fetch (http:// or https://).
        max_length: Maximum characters to return (default 25,000).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
    # SSRF protection: validate URL before fetching
    ssrf_err = _validate_url_safety(url)
    if ssrf_err:
        return ssrf_err
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True, headers=headers) as client:
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
    except httpx.HTTPStatusError as e:
        return f"HTTP error {e.response.status_code} fetching URL."
    except httpx.TimeoutException:
        return "Request timed out while connecting to URL."
    except Exception as e:
        return f"Error fetching URL: {type(e).__name__}"

def web_check_status(url: str) -> Dict[str, Any]:
    """Check HTTP response status, headers, and latency of any URL or API endpoint."""
    # SSRF protection: validate URL before fetching
    ssrf_err = _validate_url_safety(url)
    if ssrf_err:
        return {"error": ssrf_err, "url": url}
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(url)
            return {
                "status_code": resp.status_code,
                "url": str(resp.url),
                "is_success": resp.is_success,
                "content_type": resp.headers.get("content-type"),
                "elapsed_ms": round(resp.elapsed.total_seconds() * 1000, 2)
            }
    except httpx.TimeoutException:
        return {"error": "Connection timed out", "url": url}
    except Exception as e:
        return {"error": f"Request failed: {type(e).__name__}", "url": url}
