"""The cache: its records and objects, read without a lock and written under one.

fetching.md's §6 governs it. A cache has the snapshot store's layout,
objects, and records, as the store's version 0.2.0 gives them: a log of
records for each feed, `feeds/FEED/versions.jsonl`, and an object for each
distinct body, `objects/AA/SHA256.gz`. A read checks what it needs and no
more (CACHE-10). A fetch writes under the cache's lock (CACHE-6), never into
a snapshot store (CACHE-5), and only adds objects and appends records
(CACHE-3).
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import os
import re
import tempfile
import zlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from edgar_asof._errors import CacheError, SnapshotStoreError
from edgar_asof._feeds import feed

SHA256 = re.compile(r"[0-9a-f]{64}")
# The record's fields that a conditional request sends, with their headers
# (CLIENT-5).
VALIDATORS = {"etag": "If-None-Match", "last_modified": "If-Modified-Since"}


def log_path(directory: Path, url: str) -> Path:
    """The log of the URL's feed (CLIENT-15)."""
    return directory / "feeds" / feed(url) / "versions.jsonl"


def object_name(sha256: str) -> str:
    """The path of a body's object, relative to the cache's directory (the store's OBJ-1)."""
    return f"objects/{sha256[:2]}/{sha256}.gz"


def tool() -> str:
    """The `tool` of each record the library writes (CACHE-4)."""
    return f"edgar-asof@{metadata.version('edgar-asof')}"


def refuse_constant(name: str) -> Any:
    raise ValueError(f"{name} isn't JSON")


def parse(line: bytes) -> dict[str, Any] | None:
    """A log's line as a record, or None if it isn't one that a read can read (CACHE-10)."""
    try:
        record = json.loads(line.decode("utf-8"), parse_constant=refuse_constant)
    except (ValueError, RecursionError):
        return None
    if not isinstance(record, dict) or not isinstance(record.get("url"), str):
        return None
    if "sha256" not in record:
        return None
    sha256 = record["sha256"]
    if sha256 is not None and not (isinstance(sha256, str) and SHA256.fullmatch(sha256)):
        return None
    return record


def records(directory: Path, url: str) -> list[dict[str, Any]]:
    """The URL's records, in the order of its feed's log.

    Every line of the log is read, but an unfinished last one, which a fetch
    may still be appending (CACHE-6), and a line that isn't a record raises
    CacheError, which names the log (CACHE-10). A cache without the log
    holds no record of the URL.
    """
    path = log_path(directory, url)
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return []
    except OSError as err:
        raise CacheError(url, f"can't read the log: {err.strerror}", path=path) from err
    # A log that ends in a newline splits into its lines and an empty piece,
    # and one that doesn't, into its lines and the unfinished one.
    *lines, _ = content.split(b"\n")
    found = []
    for number, line in enumerate(lines, 1):
        record = parse(line)
        if record is None:
            raise CacheError(
                url,
                f"line {number} of the log isn't a JSON object with a url and a sha256",
                path=path,
            )
        if record["url"] == url:
            found.append(record)
    return found


def latest(directory: Path, url: str) -> dict[str, Any] | None:
    """The URL's latest record with a `sha256`, which names its latest version (READ-3)."""
    named = [record for record in records(directory, url) if record["sha256"] is not None]
    return named[-1] if named else None


def versions(directory: Path, url: str) -> list[str]:
    """The URL's versions: the distinct `sha256` values among its records, in order (CACHE-7)."""
    named = (record["sha256"] for record in records(directory, url))
    return [sha256 for sha256 in dict.fromkeys(named) if sha256 is not None]


def validators(record: dict[str, Any]) -> dict[str, str]:
    """The headers of a conditional request, from the record of the latest version (CLIENT-5)."""
    return {
        header: record[field]
        for field, header in VALIDATORS.items()
        if isinstance(record.get(field), str) and record[field]
    }


def read_object(directory: Path, url: str, sha256: str) -> bytes:
    """A version's body: its object's decompressed bytes, which must have its SHA-256.

    Raises CacheError, which names the object, if they don't, or if the
    object is missing or isn't gzip data (CACHE-10).
    """
    path = directory / object_name(sha256)
    try:
        compressed = path.read_bytes()
    except FileNotFoundError as err:
        raise CacheError(url, "the version's object is missing", path=path) from err
    except OSError as err:
        raise CacheError(
            url, f"can't read the version's object: {err.strerror}", path=path
        ) from err
    try:
        body = gzip.decompress(compressed)
    except (OSError, EOFError, zlib.error) as err:
        raise CacheError(url, "the version's object isn't gzip data", path=path) from err
    if hashlib.sha256(body).hexdigest() != sha256:
        raise CacheError(url, "the version's object doesn't hold its SHA-256's body", path=path)
    return body


@dataclass(frozen=True)
class Stored:
    """A body the cache holds: its SHA-256 and its length (the store's REC-3 and REC-8)."""

    sha256: str
    size: int


@contextlib.contextmanager
def writing(directory: Path, url: str) -> Iterator[Writer]:
    """Hold the cache's lock while the URL is fetched into it, and give the fetch its writer.

    Refuses a snapshot store, a directory that holds a `scope.json`, before
    writing anything, the lock's file included (CACHE-5). Makes the
    directory, with its parents (READ-5), and then waits while another
    process holds the lock (CACHE-6).
    """
    if (directory / "scope.json").exists(follow_symlinks=False):
        raise SnapshotStoreError(
            url,
            f"{directory} holds a scope.json, so it's a snapshot store, "
            "which edgar-asof never fetches into",
        )
    directory.mkdir(parents=True, exist_ok=True)
    # fcntl is POSIX's. It's imported where a fetch needs it, so that the
    # package, and a read, work without it.
    import fcntl

    with (directory / ".lock").open("ab") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        writer = Writer(directory, url)
        try:
            yield writer
        finally:
            # Closing the file releases the lock.
            writer.locked = False


class Writer:
    """Writes one fetch of a URL into a cache, while its process holds the cache's lock.

    It only adds objects and appends records (CACHE-3), each as the
    snapshot store writes them (CACHE-1, CACHE-2).
    """

    def __init__(self, directory: Path, url: str) -> None:
        self.directory = directory
        self.url = url
        self.locked = True

    def check_locked(self) -> None:
        if not self.locked:
            raise RuntimeError(f"the lock on {self.directory} is no longer held")

    def write_object(self, body: Iterable[bytes]) -> Stored:
        """Store a body as an object, unless the cache holds it already (CACHE-2).

        `body` gives the body's bytes, after any `Content-Encoding` is
        removed, in chunks. If it raises, nothing is stored, and the
        temporary file is deleted, as the store's OBJ-3 allows.
        """
        self.check_locked()
        objects = self.directory / "objects"
        objects.mkdir(exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        descriptor, name = tempfile.mkstemp(dir=objects, suffix=".tmp")
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as file:
                with gzip.GzipFile(filename="", fileobj=file, mode="wb", mtime=0) as compressed:
                    for chunk in body:
                        digest.update(chunk)
                        size += len(chunk)
                        compressed.write(chunk)
                file.flush()
                os.fsync(file.fileno())
            sha256 = digest.hexdigest()
            path = self.directory / object_name(sha256)
            if path.exists():
                # The same name is the same body.
                temporary.unlink()
            else:
                path.parent.mkdir(exist_ok=True)
                os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return Stored(sha256, size)

    def append(
        self,
        *,
        requested_at: datetime,
        attempts: int,
        status: int | None,
        error: str | None = None,
        final_url: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        content_type: str | None = None,
        stored: Stored | None = None,
    ) -> dict[str, Any]:
        """Append the fetch's record to its feed's log, and return it (CLIENT-14, CLIENT-15).

        `stored` is the body the record names, which is in place already.
        Raises ValueError, and appends nothing, for a record that would
        break the store's REC-1 to REC-7 (CACHE-1).
        """
        self.check_locked()
        if requested_at.tzinfo is None:
            raise ValueError("requested_at needs a time zone (REC-1)")
        if attempts < 1:
            raise ValueError("a fetch makes at least one attempt (REC-1)")
        if stored is not None and not (self.directory / object_name(stored.sha256)).is_file():
            raise ValueError(f"no object for {stored.sha256} is in place (REC-3)")
        problem = self.outcome_problem(status, error, stored)
        if problem:
            raise ValueError(problem)
        record = {
            "feed": feed(self.url),
            "url": self.url,
            "requested_at": requested_at.astimezone(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "attempts": attempts,
            "status": status,
            "error": error,
            "final_url": final_url,
            "etag": etag,
            "last_modified": last_modified,
            "content_type": content_type,
            "sha256": stored.sha256 if stored else None,
            "bytes": stored.size if stored else None,
            "object": object_name(stored.sha256) if stored else None,
            "tool": tool(),
        }
        path = log_path(self.directory, self.url)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
            log.flush()
            os.fsync(log.fileno())
        return record

    def outcome_problem(self, status: int | None, error: str | None, stored: Stored | None) -> str:
        """How a fetch's outcome would break the store's REC-4 to REC-7, or nothing."""
        if status is None and error is None:
            return "a fetch with no response records an error (REC-7)"
        if status == 200 and error is None and stored is None:
            return "a 200 without an error names its body (REC-4)"
        if status == 304 and stored is None and error is None:
            return "a 304 that names no version records an error (REC-5)"
        if status == 304 and stored is not None:
            earlier = latest(self.directory, self.url)
            if earlier is None or earlier["sha256"] != stored.sha256:
                return "a 304 names the URL's latest earlier version (REC-5)"
        if stored is not None and not (status == 304 or (status == 200 and error is None)):
            return f"a {status} with error {error!r} names no body (REC-6)"
        return ""
