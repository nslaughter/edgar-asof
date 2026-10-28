"""Reading a URL's body, from a cache or from bodies the caller gives (fetching.md's §8)."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from edgar_asof import _cache
from edgar_asof._errors import BodyNotGivenError
from edgar_asof._feeds import feed


@dataclass(frozen=True, init=False)
class Cache:
    """A cache, as a source (CACHE-9).

    `directory` is the cache's. `user_agent` is what each fetch into the
    cache sends as its `User-Agent`, and without one, a read that would
    fetch fails (CLIENT-2). The `repr` doesn't show it.
    """

    directory: Path
    user_agent: str | None = field(default=None, repr=False)

    def __init__(self, directory: str | os.PathLike[str], *, user_agent: str | None = None) -> None:
        if user_agent is not None and "@" not in user_agent:
            raise ValueError("a user agent contains an @, as the SEC's name and address do")
        object.__setattr__(self, "directory", Path(directory))
        object.__setattr__(self, "user_agent", user_agent)


@dataclass(frozen=True, init=False)
class Bodies:
    """Bodies the caller gives, as a source.

    `bodies` holds each URL's body, after any `Content-Encoding` is removed.
    A read from them requests nothing and writes nothing (READ-2).
    """

    # Each body can be megabytes.
    bodies: Mapping[str, bytes] = field(repr=False)

    def __init__(self, bodies: Mapping[str, bytes]) -> None:
        copied = dict(bodies)
        for url, body in copied.items():
            feed(url)
            if not isinstance(body, bytes):
                raise TypeError(f"the body given for {url} isn't bytes")
        object.__setattr__(self, "bodies", MappingProxyType(copied))


type Source = Cache | Bodies


@dataclass(frozen=True)
class Body:
    """A URL's body, as a read returns it, with its SHA-256 (READ-3)."""

    url: str
    sha256: str
    # A body can be megabytes.
    content: bytes = field(repr=False)


@dataclass(frozen=True)
class BodyRef:
    """A body's URL and SHA-256, without its content."""

    url: str
    sha256: str


def read_body(url: str, source: Source, *, fresh: bool = False) -> Body:
    """Read a URL's body from its source.

    `fresh` asks for a fresh fetch, which only a cache can make.
    """
    feed(url)
    if isinstance(source, Bodies):
        if fresh:
            raise ValueError("a fresh read fetches, and bodies the caller gives can't be fetched")
        try:
            content = source.bodies[url]
        except KeyError:
            raise BodyNotGivenError(url, "no body was given for this URL") from None
        return Body(url, hashlib.sha256(content).hexdigest(), content)
    return read_cache(url, source, fresh=fresh)


def read_cache(url: str, cache: Cache, *, fresh: bool) -> Body:
    """Read a URL's latest version in a cache (CACHE-8)."""
    record = _cache.latest(cache.directory, url)
    if record is not None and not fresh:
        sha256: str = record["sha256"]
        return Body(url, sha256, _cache.read_object(cache.directory, url, sha256))
    if record is not None and _cache.validators(record):
        # A 304 to the conditional request names this version, so its object
        # is read before anything is requested (CACHE-10).
        _cache.read_object(cache.directory, url, record["sha256"])
    raise NotImplementedError("a read that fetches into a cache is T6's, in docs/plan.md")
