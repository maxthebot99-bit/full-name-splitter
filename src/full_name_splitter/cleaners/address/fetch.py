"""Async HTML fetcher with TLS-fingerprint impersonation + multi-location discovery.

Uses curl_cffi (Chrome 124 TLS fingerprint) to bypass Cloudflare's JA3 checks.
Cascades through candidate base URLs (apex / www / http / verify=False) and
falls through to ScrapingBee if SCRAPINGBEE_API_KEY is set and the curl_cffi
tier ends in cloudflare / broken / tls_error / empty_render — i.e. anything
likely to be unblocked by a residential JS-rendering proxy.

Returns (text, status) where status is one of:
  - ok            : got content with extractable signal
  - cloudflare    : 403/CF challenge body
  - broken        : 5xx, Wix-error pages, etc.
  - dead          : DNS dead, 404
  - tls_error     : cert problems we couldn't bypass
  - no_response   : timeouts, generic failure
  - empty_render  : 200 OK but cleaned text < 500 chars or no digits — SPA shell
                    that needs JS rendering before it has any content
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import socket
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

_log = logging.getLogger("full_name_splitter.address.fetch")


IMPERSONATE = "chrome124"
TIMEOUT = 15

# Order matters: contact pages first so they survive the per-domain budget cap.
PATHS = (
    "/contact-us", "/contact",
    "/locations", "/find-us", "/our-locations",
    "/about-us", "/about",
    "/",
)

CF_FINGERPRINTS = (
    "cloudflare", "attention required", "ray id",
    "error 1000", "checking your browser", "cf-mitigated",
)

SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"

# Multi-location link discovery scoring.
LOCATION_KEYWORDS = (
    "location", "office", "branch", "store", "shop", "visit",
    "find-us", "find_us", "find us", "directions",
    "all-locations", "headquart", "corporate", "hq",
)
HQ_KEYWORDS = ("headquart", "main office", "corporate hq", "global hq", "world hq")
SKIP_PATTERNS = (
    "/wp-", "/tag/", "/category/", "/feed", "/rss",
    "/cart", "/checkout", "/account", "/login", "/admin",
    "/blog", "/news/", "/post/", "/article/", "/podcast",
    "/privacy", "/terms", "/legal", "/sitemap", "/api/",
    ".pdf", ".jpg", ".png", ".svg", ".gif", ".css", ".js",
    "mailto:", "tel:", "javascript:", "#",
)
MAX_LOCATION_FETCHES = 3


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _bare_host(host: str) -> str:
    """Last two dotted segments, www-stripped, lowercased."""
    if not host:
        return ""
    host = host.lower().strip("/")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _clean_html(html: str, url: str, per_page_chars: int) -> str:
    """Strip nav/scripts; keep visible text + JSON-LD + footer-prepended.

    Footer/contact-class divs are extracted explicitly because addresses
    cluster there and BeautifulSoup's flat get_text() can bury them.
    """
    soup = BeautifulSoup(html, "lxml")

    jsonld_blobs: list[str] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        if tag.string:
            jsonld_blobs.append(tag.string.strip())

    address_zones: list[str] = []
    for footer in soup.find_all("footer"):
        t = footer.get_text(separator=" ", strip=True)
        if t:
            address_zones.append(t)
    for elem in soup.find_all(
        class_=lambda c: c
        and any(k in c.lower() for k in ("contact", "address", "location", "office"))
    ):
        t = elem.get_text(separator=" ", strip=True)
        if t and len(t) < 2000:
            address_zones.append(t)
    for elem in soup.find_all(
        attrs={"itemtype": re.compile(r"PostalAddress|LocalBusiness", re.I)}
    ):
        t = elem.get_text(separator=" ", strip=True)
        if t:
            address_zones.append(t)

    for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
        tag.decompose()

    body_text = soup.get_text(separator=" ", strip=True)
    body_text = re.sub(r"\s+", " ", body_text)

    parts = [f"--- URL: {url} ---"]
    if address_zones:
        parts.append("--- ADDRESS-LIKELY ZONES ---")
        parts.append("\n".join(dict.fromkeys(address_zones)))
    if jsonld_blobs:
        parts.append("--- JSON-LD ---")
        parts.extend(jsonld_blobs)
    parts.append("--- BODY ---")
    parts.append(body_text)

    out = "\n".join(parts)
    if len(out) > per_page_chars:
        out = out[:per_page_chars]
    return out


def _looks_empty(text: str) -> bool:
    """True when curl_cffi got 200 OK but the cleaned text has no usable signal.

    `_clean_html` always emits ~150 chars of structural markers (URL header,
    section dividers) even on a blank page. So the threshold is on the
    combined post-clean output, not the raw HTML.

    Heuristics — both cheap, hit the same SPA-shell case from different angles:
      - len < 500 chars: nav stripped, body empty → typical for unrendered SPAs
      - no digit anywhere: addresses, ZIPs, phones, JSON-LD all contain digits;
        a digit-free page cannot contain an extractable address regardless
    """
    if len(text) < 500:
        return True
    if not any(c.isdigit() for c in text):
        return True
    return False


def _classify_error(exc: Exception | None, status_code: int | None, body: str) -> str:
    if exc is not None:
        msg = str(exc).lower()
        cls = type(exc).__name__
        if "dns" in cls.lower() or "could not resolve" in msg:
            return "dead"
        if "certificate" in msg or "ssl" in msg or "tls" in msg:
            return "tls_error"
        if "timeout" in cls.lower() or "timeout" in msg or "timed out" in msg:
            return "no_response"
        return "no_response"
    if status_code is None:
        return "no_response"
    body_lower = (body or "").lower()
    if status_code in (403, 503) or any(s in body_lower for s in CF_FINGERPRINTS):
        return "cloudflare"
    if status_code == 404:
        return "dead"
    if 500 <= status_code < 600:
        return "broken"
    if 400 <= status_code < 500:
        return "broken"
    return "no_response"


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Return (True, "") if the URL resolves to public IPs only.

    Otherwise (False, reason) with reason in {"private_host", "no_host",
    "resolve_failed", "non_http"}. Used to defend against SSRF when the
    URL comes from user-supplied CSV cells (address-tab `website_url`).

    Defense in depth on top of the systemd-level `IPAddressDeny` rules
    that block RFC1918, link-local + cloud metadata (169.254.0.0/16),
    Tailscale CGNAT, and IPv6 ULA at the network layer. This function
    also closes the loopback path (127.0.0.0/8, ::1) which is left open
    at the systemd layer to preserve unit-internal health checks.

    Does NOT defend against DNS rebinding mid-fetch (where the host
    resolves to a public IP at safety-check time but to a private IP
    at request time). curl_cffi doesn't expose an easy way to pin the
    resolved IP into the request; the residual risk is mitigated by
    the systemd egress deny list for most internal destinations and
    by the short request timeout (15s).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, "non_http"
    host = parsed.hostname
    if not host:
        return False, "no_host"
    try:
        addr_info = socket.getaddrinfo(host, None)
    except (socket.gaierror, socket.herror, UnicodeError):
        return False, "resolve_failed"
    for family, _type, _proto, _canon, sockaddr in addr_info:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return False, "private_host"
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, "private_host"
        if isinstance(ip, ipaddress.IPv4Address):
            # 100.64.0.0/10 — RFC 6598 CGNAT, used by Tailscale. Not
            # `is_private` per ipaddress, but never legitimate for
            # third-party scraping from this app.
            if ipaddress.ip_address("100.64.0.0") <= ip <= ipaddress.ip_address("100.127.255.255"):
                return False, "private_host"
    return True, ""


async def _fetch_url(
    session: AsyncSession,
    url: str,
    *,
    verify: bool = True,
    expected_host: str | None = None,
    per_page_chars: int = 5_000,
) -> tuple[str | None, str]:
    # CSO 2026-05-14 (SSRF defense in depth): reject URLs that resolve to
    # private/loopback/link-local IPs before issuing the request. The
    # systemd unit (see deploy/full-name-splitter.service) blocks most internal
    # destinations at the network layer; this closes loopback explicitly
    # (left open at the systemd layer for unit-internal health checks).
    safe, reason = _is_safe_url(url)
    if not safe:
        _log.warning(
            "ssrf_blocked",
            extra={"url_host": urlparse(url).hostname, "reason": reason},
        )
        return None, "ssrf_blocked"
    try:
        r = await session.get(
            url, timeout=TIMEOUT, allow_redirects=True, verify=verify
        )
        # Post-fetch: if redirect carried us to a private host, drop the
        # response. The fetch already happened (residual risk for GET-side-
        # effecting internal services), but at least the response body
        # doesn't reach the LLM prompt downstream.
        final_url = str(r.url)
        if final_url != url:
            safe_final, reason_final = _is_safe_url(final_url)
            if not safe_final:
                _log.warning(
                    "ssrf_blocked_after_redirect",
                    extra={
                        "url_host": urlparse(url).hostname,
                        "final_host": urlparse(final_url).hostname,
                        "reason": reason_final,
                    },
                )
                return None, "ssrf_blocked"
        if r.status_code == 200 and r.text and not any(
            s in r.text.lower()[:4000] for s in CF_FINGERPRINTS
        ):
            return _clean_html(r.text, str(r.url), per_page_chars), "ok"
        return None, _classify_error(None, r.status_code, r.text or "")
    except Exception as e:
        return None, _classify_error(e, None, "")


def _candidate_bases(website_url: str) -> list[str]:
    if "://" in website_url:
        parsed = urlparse(website_url)
        scheme = parsed.scheme or "https"
        host = parsed.netloc
    else:
        scheme = "https"
        host = website_url
    host = host.strip("/").lower()
    bare = host[4:] if host.startswith("www.") else host
    www = f"www.{bare}"
    return [
        f"{scheme}://{bare}",
        f"{scheme}://{www}",
        f"http://{bare}",
        f"http://{www}",
    ]


async def _try_base(
    session: AsyncSession,
    base: str,
    *,
    verify: bool,
    expected_host: str | None,
    per_page_chars: int,
) -> tuple[list[str], list[str]]:
    tasks = [
        _fetch_url(
            session, urljoin(base, p),
            verify=verify, expected_host=expected_host,
            per_page_chars=per_page_chars,
        )
        for p in PATHS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    chunks, errors = [], []
    for r in results:
        if isinstance(r, tuple):
            text, status = r
            if text:
                chunks.append(text)
            else:
                errors.append(status)
    return chunks, errors


def _discover_location_links(
    html: str, base_url: str, expected_host: str
) -> list[tuple[str, str, int]]:
    """Find internal links that look like location/branch subpages.

    Used for multi-location patterns where the homepage links to per-location
    subpages (Bacari → /north-park, /culver-city; Friendly Dental → /locations/charlotte; etc.).
    """
    soup = BeautifulSoup(html, "lxml")
    candidates: list[tuple[str, str, int]] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(href.startswith(p) for p in ("mailto:", "tel:", "javascript:", "#")):
            continue
        anchor = a.get_text(separator=" ", strip=True)
        if not anchor or len(anchor) > 60:
            continue
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if _bare_host(parsed.netloc) != _bare_host(expected_host):
            continue
        path = parsed.path.lower().rstrip("/")
        if not path or path == "/":
            continue
        if any(skip in path for skip in SKIP_PATTERNS):
            continue
        if full in seen:
            continue
        seen.add(full)

        anchor_lower = anchor.lower()
        slug = path.strip("/").split("/")[-1]
        score = 0
        if any(hq in anchor_lower for hq in HQ_KEYWORDS):
            score += 10
        if any(kw in path for kw in LOCATION_KEYWORDS):
            score += 4
        if any(kw in anchor_lower for kw in LOCATION_KEYWORDS):
            score += 3
        if slug and _slugify(anchor) == slug:
            score += 3
        if path.count("/") == 1:
            score += 1
        if path.count("/") > 3:
            score -= 2
        if score >= 3:
            candidates.append((full, anchor, score))

    candidates.sort(key=lambda x: -x[2])
    return candidates[: MAX_LOCATION_FETCHES * 2]


async def _discover_and_fetch_locations(
    session: AsyncSession,
    working_base: str,
    expected_host: str,
    per_page_chars: int,
) -> list[str]:
    extra: list[str] = []
    try:
        r = await session.get(
            working_base + "/", timeout=TIMEOUT, allow_redirects=True
        )
        if r.status_code != 200 or not r.text:
            return extra
        if any(s in r.text.lower()[:4000] for s in CF_FINGERPRINTS):
            return extra
        candidates = _discover_location_links(
            r.text, working_base + "/", expected_host
        )
        if not candidates:
            return extra
        top = candidates[:MAX_LOCATION_FETCHES]
        tasks = [
            _fetch_url(
                session, url,
                expected_host=expected_host, per_page_chars=per_page_chars,
            )
            for url, _, _ in top
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, tuple) and r[0]:
                extra.append(r[0])
    except Exception:
        pass
    return extra


async def _scrapingbee_fetch(
    url: str, api_key: str, per_page_chars: int
) -> tuple[str | None, str]:
    """ScrapingBee fallback for Cloudflare-blocked / JS-required / soft-blocked rows.

    premium_proxy=true uses residential IPs that bypass Cloudflare bot detection.
    render_js=true executes the page's JS so we can read content that only
    materializes after hydration — the dominant failure mode behind the
    `empty_render` tier. Costs ~25 credits/call (vs. 5 without render_js)
    so this only fires on the broader fallback set, not on every row.
    """
    params = {
        "api_key": api_key,
        "url": url,
        "premium_proxy": "true",
        "country_code": "us",
        "render_js": "true",
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.get(SCRAPINGBEE_URL, params=params)
            if r.status_code == 200 and r.text:
                if any(s in r.text.lower()[:4000] for s in CF_FINGERPRINTS):
                    return None, "cloudflare"
                return _clean_html(r.text, url, per_page_chars), "ok"
            return None, _classify_error(None, r.status_code, r.text or "")
    except Exception as e:
        return None, _classify_error(e, None, "")


async def _scrapingbee_try_base(
    base: str, api_key: str, per_page_chars: int
) -> tuple[list[str], list[str]]:
    chunks, errors = [], []
    for p in PATHS[:5]:  # only top 5 paths via ScrapingBee to control credit cost
        text, status = await _scrapingbee_fetch(
            urljoin(base, p), api_key, per_page_chars
        )
        if text:
            chunks.append(text)
        else:
            errors.append(status)
    return chunks, errors


def _summarize_errors(error_list: list[str]) -> str:
    if not error_list:
        return "no_response"
    counts: dict[str, int] = {}
    for e in error_list:
        counts[e] = counts.get(e, 0) + 1
    priority = ["cloudflare", "tls_error", "broken", "dead", "no_response"]
    for p in priority:
        if p in counts:
            return p
    return "no_response"


async def fetch_pages(
    website_url: str,
    *,
    per_page_chars: int = 5_000,
    max_html_chars: int = 40_000,
    sem: asyncio.Semaphore | None = None,
) -> tuple[str, str]:
    """Fetch /, /contact-us, /about, etc. for a domain.

    Returns (concatenated_text, status). Empty text + 'cloudflare' status will
    have already attempted the ScrapingBee fallback if SCRAPINGBEE_API_KEY is set.
    """
    parsed_input = urlparse(
        website_url if "://" in website_url else f"https://{website_url}"
    )
    expected_host = parsed_input.netloc or parsed_input.path
    bases = _candidate_bases(website_url)
    all_errors: list[str] = []

    async def _do_fetch() -> tuple[str, str]:
        async with AsyncSession(impersonate=IMPERSONATE) as session:
            chunks: list[str] = []
            working_base: str | None = None
            for base in bases:
                got, errs = await _try_base(
                    session, base,
                    verify=True, expected_host=expected_host,
                    per_page_chars=per_page_chars,
                )
                all_errors.extend(errs)
                if got:
                    chunks = got
                    working_base = base
                    break
            if not chunks:
                for base in bases:
                    got, errs = await _try_base(
                        session, base,
                        verify=False, expected_host=expected_host,
                        per_page_chars=per_page_chars,
                    )
                    all_errors.extend(errs)
                    if got:
                        chunks = got
                        working_base = base
                        break
            if chunks and working_base:
                extra = await _discover_and_fetch_locations(
                    session, working_base, expected_host, per_page_chars
                )
                chunks.extend(extra)

        # Decide the curl_cffi-tier outcome before any fallback.
        # If we got chunks, combine and check for empty-shell — a 200 OK that
        # nonetheless yields no extractable content is treated as its own tier
        # so it (a) shows up in stats as a distinct bucket and (b) triggers
        # the ScrapingBee JS-rendering fallback alongside cloudflare/broken/tls.
        if chunks:
            combined = "\n\n".join(chunks)
            if len(combined) > max_html_chars:
                combined = combined[:max_html_chars]
            if _looks_empty(combined):
                curl_cffi_status = "empty_render"
                chunks = []
            else:
                return combined, "ok"
        else:
            curl_cffi_status = _summarize_errors(all_errors)

        # ScrapingBee fallback fires whenever the failure is plausibly an
        # anti-bot or JS-rendering issue. Skips dead (DNS gone, 404 — proxy
        # won't help) and no_response (network/timeout — also won't help).
        if curl_cffi_status in ("cloudflare", "broken", "tls_error", "empty_render"):
            sb_key = os.environ.get("SCRAPINGBEE_API_KEY")
            if sb_key:
                for base in bases[:2]:
                    got, errs = await _scrapingbee_try_base(
                        base, sb_key, per_page_chars
                    )
                    if got:
                        chunks = got
                        break

        if not chunks:
            return "", curl_cffi_status

        combined = "\n\n".join(chunks)
        if len(combined) > max_html_chars:
            combined = combined[:max_html_chars]
        # ScrapingBee with render_js=true can still return a near-empty body
        # for genuinely contentless sites. Preserve the empty_render signal
        # rather than collapsing to "ok" with empty extraction downstream.
        if _looks_empty(combined):
            return "", "empty_render"
        return combined, "ok"

    if sem is None:
        return await _do_fetch()
    async with sem:
        return await _do_fetch()
