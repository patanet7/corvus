"""Ollama model discovery — probe a running Ollama instance for available models.

Supports multiple candidate URLs with fallback: probe in order, cache the
first reachable one so subsequent calls are fast.
"""

import threading
import time

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Cached resolved URL + expiry.  Re-probed after TTL or on failure.
_resolved_url: str | None = None
_resolved_at: float = 0.0
_URL_TTL_SECONDS: float = 300.0  # 5 minutes
_lock = threading.Lock()


def probe_ollama_models(base_url: str, timeout: float = 5.0) -> list[str]:
    """Query Ollama's /api/tags endpoint for available model names.

    Returns an empty list if Ollama is unreachable or returns an error.
    Never raises — errors are logged and swallowed for graceful degradation.
    """
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        resp = httpx.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        models = [m["name"] for m in data.get("models", [])]
        logger.info("ollama_models_found", base_url=base_url, count=len(models), models=models)
        return models
    except Exception:
        logger.warning("ollama_probe_failed", base_url=base_url, exc_info=True)
        return []


def _is_reachable(url: str, timeout: float = 3.0) -> bool:
    """Quick health check — hit /api/version which is lightweight."""
    try:
        resp = httpx.get(f"{url.rstrip('/')}/api/version", timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def resolve_ollama_url(
    candidate_urls: list[str],
    timeout: float = 3.0,
    force: bool = False,
) -> str | None:
    """Probe candidate URLs in order and return the first reachable one.

    Results are cached for ``_URL_TTL_SECONDS`` (5 min).  Pass *force=True*
    to bypass the cache (e.g. after a connection failure).

    Returns ``None`` if no candidate is reachable.
    """
    global _resolved_url, _resolved_at

    with _lock:
        now = time.monotonic()
        if not force and _resolved_url and (now - _resolved_at) < _URL_TTL_SECONDS:
            return _resolved_url

        for url in candidate_urls:
            if _is_reachable(url, timeout=timeout):
                logger.info("ollama_resolved", url=url)
                _resolved_url = url
                _resolved_at = now
                return url

        logger.warning("ollama_unreachable", candidate_urls=candidate_urls)
        _resolved_url = None
        _resolved_at = now  # cache the miss too, re-probe after TTL
        return None


def invalidate_cache() -> None:
    """Force the next ``resolve_ollama_url`` call to re-probe."""
    global _resolved_url, _resolved_at
    with _lock:
        _resolved_url = None
        _resolved_at = 0.0
