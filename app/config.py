"""Runtime configuration, read from environment variables."""
import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    # --- SET upstream -------------------------------------------------------
    # The paths below are the JSON endpoints the set.or.th quote pages call.
    # They are NOT an official, contractually stable API. They are configurable
    # so a change on SET's side is an env-var fix, not a code change.
    set_base_url: str = field(default_factory=lambda: os.getenv("SET_BASE_URL", "https://www.set.or.th"))
    corporate_action_path: str = field(
        default_factory=lambda: os.getenv("SET_CORPORATE_ACTION_PATH", "/api/set/stock/{symbol}/corporate-action")
    )
    profile_path: str = field(
        default_factory=lambda: os.getenv("SET_PROFILE_PATH", "/api/set/stock/{symbol}/profile")
    )
    # curl_cffi browser fingerprint (e.g. chrome, safari, firefox). Empty = no impersonation.
    impersonate: str = field(default_factory=lambda: os.getenv("SET_IMPERSONATE", "chrome"))
    # Force protocol: v1 (HTTP/1.1) or v2. Empty = library default. Try v1 if you see HTTP2 framing errors.
    http_version: str = field(default_factory=lambda: os.getenv("SET_HTTP_VERSION", ""))
    timeout_seconds: float = field(default_factory=lambda: _float("SET_TIMEOUT_SECONDS", 10))
    max_retries: int = field(default_factory=lambda: _int("SET_MAX_RETRIES", 2))
    max_concurrency: int = field(default_factory=lambda: _int("SET_MAX_CONCURRENCY", 4))
    cache_ttl_seconds: int = field(default_factory=lambda: _int("CACHE_TTL_SECONDS", 600))

    # --- API ----------------------------------------------------------------
    # Enables GET /v1/debug/probe (raw SET status/body snippet). Off by default.
    enable_debug: bool = field(
        default_factory=lambda: os.getenv("ENABLE_DEBUG", "").lower() in ("1", "true", "yes")
    )
    max_symbols: int = field(default_factory=lambda: _int("MAX_SYMBOLS", 50))
    # Comma-separated keys. Empty = auth disabled (fine for local dev only).
    api_keys: frozenset[str] = field(
        default_factory=lambda: frozenset(k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip())
    )


def get_settings() -> Settings:
    return Settings()
