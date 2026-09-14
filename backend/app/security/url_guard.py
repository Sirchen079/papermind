"""Outbound URL guard for user-configured provider base URLs.

Deliberately scheme-only hardening: private/loopback hosts (local Ollama,
LM Studio, vLLM on 127.0.0.1) are legitimate provider targets, so no
IP-range blocking happens here. The fix for the reported SSRF finding is
to restrict base URLs to the http/https schemes and require a host.
"""

from urllib.parse import urlsplit

import httpx

_ALLOWED_SCHEMES = ("http", "https")

_ARXIV_HOST = "arxiv.org"


def ensure_http_url(url: str) -> str:
    """Validate that ``url`` is an http(s) URL with a host and return it as-is.

    Pure function: parses with :func:`urllib.parse.urlsplit` and never
    touches the network.

    Raises:
        ValueError: if ``url`` is not a string, its scheme is not http or
            https, or it has no netloc (host). The message includes the
            parsed scheme.
    """
    if not isinstance(url, str):
        raise ValueError(f"base_url must be a string, got {type(url).__name__}")
    parsed = urlsplit(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"base_url must be an http(s) URL, got scheme {parsed.scheme!r} in {url!r}"
        )
    if not parsed.netloc:
        raise ValueError(
            f"base_url must include a host, got scheme {parsed.scheme!r} without one in {url!r}"
        )
    return url


def ensure_arxiv_url(url: str) -> str:
    """Validate that ``url`` points at arxiv.org (or a subdomain) and return it as-is.

    Hardens the arXiv PDF download against SSRF: the URL ultimately comes from
    the arXiv API response, so it is pinned to http(s) on ``arxiv.org`` or
    ``*.arxiv.org`` (case-insensitive). Pure function, never touches the
    network.

    Raises:
        ValueError: via :func:`ensure_http_url` for non-http(s) schemes or a
            missing host, or when the host is not ``arxiv.org`` / a
            ``*.arxiv.org`` subdomain. The message includes the actual host.
    """
    ensure_http_url(url)
    hostname = (urlsplit(url).hostname or "").lower()
    if hostname != _ARXIV_HOST and not hostname.endswith("." + _ARXIV_HOST):
        raise ValueError(
            f"arxiv url must point at {_ARXIV_HOST} or a *.arxiv.org subdomain, got host {hostname!r} in {url!r}"
        )
    return url


def validated_get(
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = 30.0,
    follow_redirects: bool = False,
) -> httpx.Response:
    """校验与请求同函数，作为应用出站 GET 的唯一收口。

    First line validates ``url`` via :func:`ensure_http_url`, so any
    non-http(s) scheme (ftp://, file://, ...) raises ValueError in-place
    before any bytes leave the process. Only then is the request performed,
    forwarding ``headers`` / ``timeout`` / ``follow_redirects`` verbatim to
    :func:`httpx.get`. The default ``follow_redirects=False`` keeps redirect
    targets from being fetched without a fresh validation at the caller.

    Raises:
        ValueError: via :func:`ensure_http_url` when ``url`` is not an
            http(s) URL with a host.
    """
    ensure_http_url(url)
    return httpx.get(
        url, headers=headers, timeout=timeout, follow_redirects=follow_redirects
    )
