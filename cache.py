# ./cache.py
"""
cache.py — SHA-256-keyed diskcache wrapper with TTL and hit/miss metrics.
Bug fix: get_cache() singleton creation is now protected by a threading.Lock.
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any, Optional

import diskcache

_MISS = object()


class AtsCache:
    """Thread-safe diskcache wrapper with SHA-256 keying, TTL, and metrics."""

    def __init__(self, cache_dir: str = ".ats_cache", ttl_hours: int = 24) -> None:
        self._cache = diskcache.Cache(str(Path(cache_dir).resolve()))
        self._ttl = ttl_hours * 3600
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._stores = 0

    @staticmethod
    def make_key(*parts: str) -> str:
        combined = "|".join(parts).encode("utf-8")
        return hashlib.sha256(combined).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            value = self._cache.get(key, default=_MISS)
            if value is _MISS:
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._cache.set(key, value, expire=self._ttl if self._ttl > 0 else None)
            self._stores += 1

    def delete(self, key: str) -> None:
        with self._lock:
            self._cache.delete(key)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._stores = 0

    def list_keys(self) -> list[str]:
        """Return all cache keys (for management UI)."""
        with self._lock:
            return list(self._cache.iterkeys())

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def metrics_dict(self) -> dict[str, Any]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "stores": self._stores,
            "hit_rate_pct": round(self.hit_rate * 100, 1),
            "total_entries": len(self._cache),
        }

    def __len__(self) -> int:
        return len(self._cache)

    def close(self) -> None:
        self._cache.close()


# --- Thread-safe singleton ---
_cache_instance: Optional[AtsCache] = None
_cache_init_lock = threading.Lock()


def get_cache(cache_dir: str = ".ats_cache", ttl_hours: int = 24) -> AtsCache:
    """Return (or create) the module-level AtsCache singleton. Thread-safe."""
    global _cache_instance
    if _cache_instance is None:
        with _cache_init_lock:
            if _cache_instance is None:   # double-checked locking
                _cache_instance = AtsCache(cache_dir=cache_dir, ttl_hours=ttl_hours)
    return _cache_instance
