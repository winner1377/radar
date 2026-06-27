"""
Proxy helpers shared by requests and httpx/OpenAI clients.
"""

import os
from urllib.parse import urlsplit, urlunsplit


PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def normalize_proxy_url(proxy_url):
    """Return an httpx/requests-compatible proxy URL."""
    if not proxy_url:
        return proxy_url

    parts = urlsplit(proxy_url)
    if parts.scheme.lower() == "socks":
        return urlunsplit(("socks5", parts.netloc, parts.path, parts.query, parts.fragment))

    return proxy_url


def normalize_proxy_environment():
    """Normalize proxy URLs from the process environment in place."""
    for key in PROXY_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            os.environ[key] = normalize_proxy_url(value)
