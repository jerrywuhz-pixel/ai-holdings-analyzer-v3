from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Literal, Optional
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from fastapi import FastAPI
from pydantic import BaseModel, Field

FetchMode = Literal["auto", "get", "dynamic", "stealthy"]

app = FastAPI(title="Hermes Reference Capture", version="0.1.0")


class ReferenceReadRequest(BaseModel):
    url: str = Field(..., min_length=1)
    tenant_id: Optional[str] = None
    mode: FetchMode = "auto"
    css_selector: Optional[str] = None
    timeout_ms: int = Field(default=30000, ge=1000, le=120000)
    max_chars: int = Field(default=12000, ge=500, le=50000)
    proxy_url: Optional[str] = None


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "runtime": "hermes-reference-capture"}


@app.post("/read")
def read_reference(payload: ReferenceReadRequest) -> dict[str, Any]:
    fetched_at = _now()
    validation_error = _validate_public_url(payload.url)
    if validation_error:
        return _failed(payload.url, "blocked_url", validation_error, fetched_at=fetched_at)

    attempted: list[str] = []
    try:
        response, mode_used = _fetch(payload, attempted)
        extracted = _extract(response, payload.css_selector, payload.max_chars)
        canonical_url = extracted.get("canonical_url") or getattr(response, "url", payload.url) or payload.url
        content_text = extracted.get("content_text") or ""
        content_markdown = extracted.get("content_markdown") or content_text
        content_hash = _sha256_text(
            "\n".join([canonical_url, extracted.get("title") or "", content_text])
        )
        status_code = int(getattr(response, "status", 0) or 0)
        ok = 200 <= status_code < 400 and bool(content_text.strip())
        if not ok:
            return _failed(
                payload.url,
                "empty_content" if 200 <= status_code < 400 else "http_error",
                "Reference capture returned no readable content."
                if 200 <= status_code < 400
                else f"Reference capture returned HTTP {status_code}.",
                fetched_at=fetched_at,
                status_code=status_code,
                attempted_modes=attempted,
                mode_used=mode_used,
                canonical_url=canonical_url,
                content_hash=content_hash,
                title=extracted.get("title"),
            )
        return {
            "ok": True,
            "status": "ok",
            "schema_version": "web_reference_snapshot_v1",
            "reference_only": True,
            "url": payload.url,
            "canonical_url": canonical_url,
            "title": extracted.get("title"),
            "content_text": content_text,
            "content_markdown": content_markdown,
            "content_hash": content_hash,
            "status_code": status_code,
            "mode_requested": payload.mode,
            "mode_used": mode_used,
            "attempted_modes": attempted,
            "fetched_at": fetched_at,
            "source_refs": [{"source": "web", "ref": canonical_url}],
            "audit": {
                "tenant_id": payload.tenant_id,
                "css_selector": payload.css_selector,
                "timeout_ms": payload.timeout_ms,
                "max_chars": payload.max_chars,
                "proxy_configured": bool(payload.proxy_url),
                "sanitization": "visible_text_extraction",
            },
        }
    except Exception as exc:  # noqa: BLE001 - this service returns auditable failures.
        return _failed(
            payload.url,
            "capture_failed",
            str(exc),
            fetched_at=fetched_at,
            attempted_modes=attempted,
        )


def _fetch(payload: ReferenceReadRequest, attempted: list[str]) -> tuple[Any, str]:
    modes = [payload.mode] if payload.mode != "auto" else ["get", "dynamic"]
    last_error: Exception | None = None
    last_response: Any = None
    for mode in modes:
        attempted.append(mode)
        try:
            response = _fetch_once(mode, payload)
            last_response = response
            status = int(getattr(response, "status", 0) or 0)
            text = _plain_text(response, payload.css_selector)
            if mode == "get" and payload.mode == "auto" and (status >= 400 or len(text.strip()) < 200):
                continue
            return response, mode
        except Exception as exc:  # noqa: BLE001 - try fallback mode before failing.
            last_error = exc
            continue
    if last_response is not None:
        return last_response, attempted[-1]
    if last_error:
        raise last_error
    raise RuntimeError("No fetch mode was attempted")


def _fetch_once(mode: str, payload: ReferenceReadRequest) -> Any:
    if mode == "get":
        try:
            from scrapling.fetchers import Fetcher
        except ModuleNotFoundError:
            return _stdlib_get(payload)

        try:
            kwargs = {
                "timeout": max(1, int(payload.timeout_ms / 1000)),
                "follow_redirects": "safe",
                "stealthy_headers": True,
            }
            if payload.proxy_url:
                kwargs["proxy"] = payload.proxy_url
            return Fetcher.get(payload.url, **kwargs)
        except Exception:
            return _stdlib_get(payload)
    if mode == "dynamic":
        from scrapling.fetchers import DynamicFetcher

        kwargs = _browser_fetch_kwargs(payload)
        return DynamicFetcher.fetch(payload.url, **kwargs)
    if mode == "stealthy":
        from scrapling.fetchers import StealthyFetcher

        kwargs = _browser_fetch_kwargs(payload)
        kwargs["block_webrtc"] = True
        return StealthyFetcher.fetch(payload.url, **kwargs)
    raise ValueError(f"Unsupported fetch mode: {mode}")


def _browser_fetch_kwargs(payload: ReferenceReadRequest) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "headless": True,
        "network_idle": True,
        "timeout": payload.timeout_ms,
        "disable_resources": True,
        "block_ads": True,
    }
    if payload.proxy_url:
        kwargs["proxy"] = payload.proxy_url
    return kwargs


def _stdlib_get(payload: ReferenceReadRequest) -> Any:
    request = Request(
        payload.url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; HermesReferenceCapture/0.1; +https://example.invalid/hermes)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    handlers: list[Any] = [_SafeRedirectHandler]
    if payload.proxy_url:
        handlers.insert(0, ProxyHandler({"http": payload.proxy_url, "https": payload.proxy_url}))
    opener = build_opener(*handlers)
    with opener.open(request, timeout=max(1, int(payload.timeout_ms / 1000))) as response:
        final_url = response.geturl() or payload.url
        validation_error = _validate_public_url(final_url)
        if validation_error:
            raise RuntimeError(f"Redirect target blocked: {validation_error}")
        raw = response.read(min(payload.max_chars * 20, 2_000_000))
        content_type = response.headers.get("content-type", "")
        encoding = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(encoding, errors="replace")
        return _StdlibResponse(
            url=final_url,
            status=int(getattr(response, "status", 0) or response.getcode() or 0),
            html=text,
            content_type=content_type,
        )


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        validation_error = _validate_public_url(newurl)
        if validation_error:
            raise RuntimeError(f"Redirect target blocked: {validation_error}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _StdlibResponse:
    def __init__(self, *, url: str, status: int, html: str, content_type: str) -> None:
        self.url = url
        self.status = status
        self.html = html
        self.content_type = content_type
        self._parsed = _ParsedHtml.from_html(html)

    def css(self, selector: str) -> "_StdlibSelection":
        if selector == "title::text":
            return _StdlibSelection(value=self._parsed.title)
        if selector == 'link[rel="canonical"]::attr(href)':
            return _StdlibSelection(value=self._parsed.canonical_url)
        if selector in self._parsed.region_text:
            text = self._parsed.region_text.get(selector) or ""
            return _StdlibSelection(nodes=[_StdlibNode(text)] if text else [])
        return _StdlibSelection(nodes=[])


class _StdlibSelection:
    def __init__(self, *, value: str | None = None, nodes: list["_StdlibNode"] | None = None) -> None:
        self.value = value
        self.nodes = nodes or []

    def get(self) -> str | None:
        return self.value

    def __iter__(self):
        return iter(self.nodes)


class _StdlibNode:
    def __init__(self, text: str) -> None:
        self.text = text

    def get_all_text(self, **_kwargs: Any) -> str:
        return self.text


class _ParsedHtml(HTMLParser):
    block_tags = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
    void_tags = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.canonical_url: str | None = None
        self.region_text: dict[str, str] = {}
        self._title_chunks: list[str] = []
        self._regions: dict[str, list[str]] = {"article": [], "main": [], "body": []}
        self._selector_regions: dict[str, list[str]] = {}
        self._active_regions: list[str] = []
        self._element_region_stack: list[list[str]] = []
        self._skip_depth = 0
        self._in_title = False

    @classmethod
    def from_html(cls, html: str) -> "_ParsedHtml":
        parser = cls()
        parser.feed(html)
        parser.close()
        parser.title = _sanitize_inline(" ".join(parser._title_chunks))
        all_regions = {**parser._regions, **parser._selector_regions}
        parser.region_text = {key: "\n".join(value) for key, value in all_regions.items()}
        return parser

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {key.lower(): value for key, value in attrs if key}
        if tag in {"script", "style", "noscript", "template"}:
            self._skip_depth += 1
            return
        active_for_element: list[str] = []
        if tag == "title":
            self._in_title = True
        if tag == "link":
            rel = str(attrs_dict.get("rel") or "").lower()
            href = attrs_dict.get("href")
            if "canonical" in rel and href:
                self.canonical_url = href
        if tag in self._regions:
            active_for_element.append(tag)
        for selector in _semantic_selectors_from_attrs(attrs_dict):
            self._selector_regions.setdefault(selector, [])
            active_for_element.append(selector)
        self._active_regions.extend(active_for_element)
        if tag not in self.void_tags:
            self._element_region_stack.append(active_for_element)
        if tag in self.block_tags:
            self._append_region_text("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "template"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if self._element_region_stack:
            for region in reversed(self._element_region_stack.pop()):
                for index in range(len(self._active_regions) - 1, -1, -1):
                    if self._active_regions[index] == region:
                        del self._active_regions[index]
                        break
        elif tag in self._regions:
            for index in range(len(self._active_regions) - 1, -1, -1):
                if self._active_regions[index] == tag:
                    del self._active_regions[index]
                    break
        if tag in self.block_tags:
            self._append_region_text("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title_chunks.append(data)
        if data.strip():
            self._append_region_text(data)

    def _append_region_text(self, text: str) -> None:
        if not self._active_regions:
            return
        for region in self._active_regions:
            if region in self._regions:
                self._regions[region].append(text)
            else:
                self._selector_regions.setdefault(region, []).append(text)


def _extract(response: Any, css_selector: str | None, max_chars: int) -> dict[str, str | None]:
    title = _first_css_text(response, "title::text")
    canonical = _first_css_text(response, 'link[rel="canonical"]::attr(href)')
    if canonical:
        canonical = urljoin(getattr(response, "url", "") or "", canonical)
    content_text = _plain_text(response, css_selector)
    content_text = _sanitize_text(content_text)[:max_chars]
    if title:
        content_markdown = f"# {title}\n\n{content_text}".strip()
    else:
        content_markdown = content_text
    return {
        "title": _sanitize_inline(title),
        "canonical_url": canonical,
        "content_text": content_text,
        "content_markdown": content_markdown,
    }


def _plain_text(response: Any, css_selector: str | None) -> str:
    selectors = _content_selectors(getattr(response, "url", "") or "", css_selector)
    chunks: list[str] = []
    for selector in selectors:
        if not selector:
            continue
        try:
            selection = response.css(selector)
        except Exception:
            continue
        try:
            items = list(selection)
        except Exception:
            items = []
        for item in items[:12]:
            text = _node_text(item)
            if text:
                chunks.append(text)
        if chunks:
            break
    if not chunks:
        chunks.append(_node_text(response))
    return "\n\n".join(chunks)


def _content_selectors(url: str, css_selector: str | None) -> list[str]:
    if css_selector:
        return [css_selector]
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("mp.weixin.qq.com"):
        return [
            "#js_content",
            ".rich_media_content",
            "#js_article",
            "article",
            "main",
            "body",
        ]
    if host.endswith("xiaohongshu.com") or host.endswith("xhslink.com"):
        return [
            "#detail-desc",
            ".note-content",
            ".note-text",
            ".content",
            "article",
            "main",
            "body",
        ]
    return ["article", "main", "body"]


def _semantic_selectors_from_attrs(attrs: dict[str, str | None]) -> list[str]:
    selectors: list[str] = []
    element_id = (attrs.get("id") or "").strip()
    classes = [item for item in re.split(r"\s+", attrs.get("class") or "") if item]
    interesting_ids = {"js_content", "js_article", "detail-desc"}
    interesting_classes = {"rich_media_content", "note-content", "note-text", "content"}
    if element_id in interesting_ids:
        selectors.append(f"#{element_id}")
    for class_name in classes:
        if class_name in interesting_classes:
            selectors.append(f".{class_name}")
    return selectors


def _node_text(node: Any) -> str:
    for kwargs in ({"separator": "\n", "strip": True}, {"strip": True}, {}):
        try:
            text = node.get_all_text(**kwargs)
            if isinstance(text, str) and text.strip():
                return text
        except Exception:
            pass
    try:
        raw = node.get()
        if isinstance(raw, str):
            return _strip_tags(raw)
    except Exception:
        pass
    return ""


def _first_css_text(response: Any, selector: str) -> str | None:
    try:
        value = response.css(selector).get()
    except Exception:
        return None
    if value is None:
        return None
    return str(value).strip() or None


def _validate_public_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "Only http and https URLs are supported."
    if not parsed.hostname:
        return "URL host is missing."
    host = parsed.hostname.strip().lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return "Local hostnames are not allowed."
    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror:
        return "URL host could not be resolved."
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            return f"Non-public address is not allowed: {ip}"
    return None


def _failed(
    url: str,
    reason: str,
    message: str,
    *,
    fetched_at: str,
    status_code: int | None = None,
    attempted_modes: list[str] | None = None,
    mode_used: str | None = None,
    canonical_url: str | None = None,
    content_hash: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    ref = canonical_url or url
    return {
        "ok": False,
        "status": reason,
        "schema_version": "web_reference_snapshot_v1",
        "reference_only": True,
        "url": url,
        "canonical_url": canonical_url or url,
        "title": title,
        "content_text": "",
        "content_markdown": "",
        "content_hash": content_hash or _sha256_text(f"{url}\n{reason}\n{message}"),
        "status_code": status_code,
        "mode_used": mode_used,
        "attempted_modes": attempted_modes or [],
        "fetched_at": fetched_at,
        "source_refs": [{"source": "web", "ref": ref}],
        "failed": {"reason": reason, "message": message},
        "audit": {"failure_reason": reason, "failure_message": message},
    }


def _sanitize_text(value: str) -> str:
    value = re.sub(r"[\u200b-\u200f\ufeff]", "", value or "")
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _sanitize_inline(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", value).strip() or None


def _strip_tags(value: str) -> str:
    value = re.sub(r"(?is)<(script|style|noscript|template).*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return _sanitize_text(value)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
