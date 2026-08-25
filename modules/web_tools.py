import re
import httpx
from typing import Dict, Any

def web_fetch_url(url: str, max_length: int = 25000) -> str:
    """Fetch content of a webpage and return readable plain text/markdown.
    
    Args:
        url: Full URL to fetch (http:// or https://).
        max_length: Maximum characters to return (default 25,000).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
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
    except Exception as e:
        return f"Error fetching {url}: {e}"

def web_check_status(url: str) -> Dict[str, Any]:
    """Check HTTP response status, headers, and latency of any URL or API endpoint."""
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
    except Exception as e:
        return {"error": str(e), "url": url}
