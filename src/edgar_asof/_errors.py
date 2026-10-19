"""The errors a read raises (fetching.md's §8)."""

from __future__ import annotations

from pathlib import Path


class ReadError(Exception):
    """A read that fails. `url` is the URL read."""

    def __init__(self, url: str, message: str) -> None:
        super().__init__(f"{url}: {message}")
        self.url = url


class BodyNotGivenError(ReadError):
    """Bodies that hold no body for the URL (READ-2)."""


class CacheError(ReadError):
    """A cache that a read can't read (CACHE-10). `path` is the file it couldn't read."""

    def __init__(self, url: str, message: str, *, path: Path) -> None:
        super().__init__(url, f"{message}: {path}")
        self.path = path


class ForbiddenError(ReadError):
    """A `403`, received by the read's fetch or by an earlier one in the process (CLIENT-9)."""


class SnapshotStoreError(ReadError):
    """A read that would fetch into a snapshot store (CACHE-5)."""


class NoUserAgentError(ReadError):
    """A read that would fetch into a cache without a user agent (CLIENT-2)."""


class FetchError(ReadError):
    """A fetch whose record names no body (READ-6), with the record's `status` and `error`."""

    def __init__(self, url: str, message: str, *, status: int | None, error: str | None) -> None:
        super().__init__(url, message)
        self.status = status
        self.error = error
