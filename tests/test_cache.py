"""The cache, and reading a body from a cache or from bodies the caller gives.

fetching.md's §6 and §8 govern them. Each test lays out a cache in a
temporary directory, through the library's writer or as the snapshot store
lays out its versions (the store's §4 to §6), with bodies made up for the
test. Nothing here fetches: the reads that fetch are tested with the
client.
"""

from __future__ import annotations

import dataclasses
import gzip
import hashlib
import inspect
import json
import os
import re
import select
import socket
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest

import edgar_asof
from edgar_asof import (
    Bodies,
    Body,
    BodyNotGivenError,
    BodyRef,
    Cache,
    CacheError,
    FetchError,
    ForbiddenError,
    NoUserAgentError,
    ReadError,
    SnapshotStoreError,
    _cache,
    _feeds,
    read_body,
)

SUBMISSIONS = "https://data.sec.gov/submissions/CIK0000320193.json"
FURTHER = "https://data.sec.gov/submissions/CIK0000320193-submissions-001.json"
COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
# A filing's header, whose accession number begins with a filing agent's CIK.
HEADER = (
    "https://www.sec.gov/Archives/edgar/data/1018724/000110465925012345/"
    "0001104659-25-012345-index-headers.html"
)
# A placeholder, at a domain reserved for examples (RFC 2606).
USER_AGENT = "Test Runner test@example.com"
REQUESTED_AT = datetime(2026, 10, 19, 12, 0, 0, 123000, tzinfo=UTC)
A = b'{"cik": "0000320193", "version": "A"}'
B = b'{"cik": "0000320193", "version": "B"}'


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def object_path(directory: Path, body: bytes) -> Path:
    return directory / "objects" / sha(body)[:2] / f"{sha(body)}.gz"


def files(directory: Path) -> dict[str, bytes]:
    """Every file under a directory, hidden ones included, with its bytes."""
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def stored_record(url: str, body: bytes | None, **fields: Any) -> dict[str, Any]:
    """A record as the snapshot store's writer writes one, naming `body` or nothing."""
    named = body is not None
    return {
        "feed": _feeds.feed(url),
        "url": url,
        "requested_at": "2026-10-07T17:40:13.617Z",
        "attempts": 1,
        "status": 200 if named else 404,
        "error": None,
        "final_url": None,
        "etag": None,
        "last_modified": None,
        "content_type": "application/json",
        "sha256": sha(body) if body is not None else None,
        "bytes": len(body) if body is not None else None,
        "object": f"objects/{sha(body)[:2]}/{sha(body)}.gz" if body is not None else None,
        "tool": "scripts/snapshot.py@70ab28b957802789240cf69ca0670eb0122705cb",
    } | fields


def put_lines(directory: Path, url: str, *lines: str) -> Path:
    """Append text to the log of a URL's feed, and return the log."""
    log = directory / "feeds" / _feeds.feed(url) / "versions.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as file:
        file.write("".join(lines))
    return log


def put_version(directory: Path, url: str, body: bytes | None, **fields: Any) -> None:
    """Lay out a fetch of a URL as the store does: the object of its body, then its record."""
    if body is not None:
        path = object_path(directory, body)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(body))
    put_lines(directory, url, json.dumps(stored_record(url, body, **fields)) + "\n")


def fetch(
    directory: Path,
    url: str,
    status: int | None,
    *,
    body: bytes | None = None,
    names: bytes | None = None,
    attempts: int = 1,
    **fields: Any,
) -> dict[str, Any]:
    """Write a fetch into a cache, as the client does: the body it received, then its record.

    `names` is the earlier body that a `304` names.
    """
    with _cache.writing(directory, url) as writer:
        stored = writer.write_object([body]) if body is not None else None
        if names is not None:
            stored = _cache.Stored(sha(names), len(names))
        return writer.append(
            requested_at=REQUESTED_AT, attempts=attempts, status=status, stored=stored, **fields
        )


# CACHE-1's invariants: the store's REC-1 to REC-8, and OBJ-1 and OBJ-3.

SHA256 = re.compile(r"[0-9a-f]{64}")
TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z")
TOOL = re.compile(r"edgar-asof@\S+")


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def optional(check: Callable[[Any], bool]) -> Callable[[Any], bool]:
    return lambda value: value is None or check(value)


def matches(pattern: re.Pattern[str]) -> Callable[[Any], bool]:
    return lambda value: isinstance(value, str) and pattern.fullmatch(value) is not None


def is_str(value: Any) -> bool:
    return isinstance(value, str)


# Every field of the store's §6, in its table's order, with its type and form.
FIELDS: dict[str, Callable[[Any], bool]] = {
    "feed": lambda value: value in _feeds.FEEDS,
    "url": is_str,
    "requested_at": matches(TIMESTAMP),
    "attempts": lambda value: is_int(value) and value >= 1,
    "status": optional(is_int),
    "error": optional(is_str),
    "final_url": optional(is_str),
    "etag": optional(is_str),
    "last_modified": optional(is_str),
    "content_type": optional(is_str),
    "sha256": optional(matches(SHA256)),
    "bytes": optional(lambda value: is_int(value) and value >= 0),
    "object": optional(is_str),
    "tool": matches(TOOL),
}


def problems(directory: Path) -> list[str]:
    """How a cache breaks CACHE-1, each problem with the store's statement it breaks."""
    found: list[str] = []
    bodies: dict[str, bytes] = {}
    for name in files(directory):
        parts = name.split("/")
        sha256 = parts[-1].removesuffix(".gz")
        if name == ".lock" or (
            len(parts) == 3
            and parts[0] == "feeds"
            and parts[1] in _feeds.FEEDS
            and parts[2] == "versions.jsonl"
        ):
            continue
        if len(parts) == 2 and parts[0] == "objects" and name.endswith(".tmp"):
            found.append(f"OBJ-3 {name}: an unfinished write")
        elif (
            len(parts) == 3
            and parts[0] == "objects"
            and name.endswith(".gz")
            and SHA256.fullmatch(sha256)
            and parts[1] == sha256[:2]
        ):
            bodies[name] = gzip.decompress((directory / name).read_bytes())
            if sha(bodies[name]) != sha256:
                found.append(f"OBJ-1 {name}: holds another body")
        else:
            found.append(f"CACHE-1 {name}: not part of a cache's layout")
    named: set[str] = set()
    for log in sorted(directory.glob("feeds/*/versions.jsonl")):
        latest: dict[str, dict[str, Any]] = {}
        for number, line in enumerate(log.read_text(encoding="utf-8").splitlines(), 1):
            where = f"{log.relative_to(directory).as_posix()}:{number}"
            record = json.loads(line)
            if list(record) != list(FIELDS):
                found.append(f"REC-1 {where}: fields {list(record)}")
                continue
            for field, check in FIELDS.items():
                if not check(record[field]):
                    found.append(f"REC-1 {where}: {field} {record[field]!r}")
            if record["feed"] != log.parent.name:
                found.append(f"REC-2 {where}: in the log of {log.parent.name}")
            found += [f"{id} {where}" for id in outcome(record, latest.get(record["url"]))]
            if record["sha256"]:
                named.add(record["object"])
                body = bodies.get(record["object"])
                if body is None:
                    found.append(f"REC-3 {where}: no object {record['object']}")
                elif record["bytes"] != len(body):
                    found.append(f"REC-8 {where}: bytes {record['bytes']}")
                latest[record["url"]] = record
    found += [f"OBJ-3 {name}: named by no record" for name in sorted(set(bodies) - named)]
    return found


def outcome(record: dict[str, Any], latest: dict[str, Any] | None) -> list[str]:
    """The store's REC-3 to REC-7 that a record breaks.

    `latest` is the URL's latest earlier record with a `sha256`, whose
    validators a conditional request sends (CLIENT-5).
    """
    broken = []
    status, error, sha256 = record["status"], record["error"], record["sha256"]
    stored = [record[field] is not None for field in ("sha256", "bytes", "object")]
    if (any(stored) and not all(stored)) or (
        sha256 and record["object"] != f"objects/{sha256[:2]}/{sha256}.gz"
    ):
        broken.append("REC-3")
    if status == 200 and error is None and not sha256:
        broken.append("REC-4")
    names_latest = latest is not None and sha256 == latest["sha256"]
    sent_validators = latest is not None and bool(latest["etag"] or latest["last_modified"])
    if status == 304 and (
        (sha256 and not (names_latest and sent_validators)) or (not sha256 and error is None)
    ):
        broken.append("REC-5")
    if sha256 and (status not in (200, 304) or (status == 200 and error is not None)):
        broken.append("REC-6")
    if status is None and error is None:
        broken.append("REC-7")
    return broken


# Writing a cache


@pytest.mark.spec("CACHE-1")
def test_a_cache_the_library_writes_has_the_stores_layout_objects_and_records(
    tmp_path: Path,
) -> None:
    fetch(tmp_path, SUBMISSIONS, 200, body=A, etag='"a"', content_type="application/json")
    fetch(tmp_path, SUBMISSIONS, 304, names=A, etag='"a"')
    fetch(tmp_path, SUBMISSIONS, 304, error="a 304 to a request that sent no validators")
    fetch(tmp_path, SUBMISSIONS, 503, attempts=4)
    fetch(tmp_path, SUBMISSIONS, None, attempts=4, error="no response: TimeoutError()")
    fetch(tmp_path, SUBMISSIONS, 200, error="unsupported Content-Encoding: br")
    fetch(tmp_path, SUBMISSIONS, 200, body=B, final_url=FURTHER)
    # The same body from another URL is one object, and a version of each.
    fetch(tmp_path, COMPANYFACTS, 200, body=B)
    fetch(tmp_path, HEADER, 404)

    assert problems(tmp_path) == []
    assert sorted(files(tmp_path)) == sorted(
        [
            ".lock",
            "feeds/companyfacts/versions.jsonl",
            "feeds/filings/versions.jsonl",
            "feeds/submissions/versions.jsonl",
            object_path(tmp_path, A).relative_to(tmp_path).as_posix(),
            object_path(tmp_path, B).relative_to(tmp_path).as_posix(),
        ]
    )


def test_the_checker_finds_what_breaks_a_cache(tmp_path: Path) -> None:
    tool = "edgar-asof@0.1.0"
    put_version(tmp_path, SUBMISSIONS, A, tool=tool)
    put_version(tmp_path, SUBMISSIONS, A, status=304, tool=tool)
    put_version(tmp_path, SUBMISSIONS, None, status=None, tool=tool)
    put_version(tmp_path, SUBMISSIONS, None, status=200, tool=tool)
    put_version(tmp_path, SUBMISSIONS, B, status=304, tool=tool)
    put_version(tmp_path, SUBMISSIONS, None, attempts=0, tool=tool)
    put_version(tmp_path, COMPANYFACTS, A, bytes=1, feed="submissions", tool=tool)
    put_version(tmp_path, HEADER, A, status=404, tool=tool)
    put_version(tmp_path, HEADER, None, object="objects/00/0.gz", tool=tool)
    put_version(tmp_path, FURTHER, A)
    unnamed = tmp_path / "objects" / "00" / f"{'0' * 64}.gz"
    unnamed.parent.mkdir()
    unnamed.write_bytes(gzip.compress(b"another body"))
    (tmp_path / "objects" / "unfinished.tmp").write_bytes(b"")
    (tmp_path / "scope.json").write_text("{}", encoding="utf-8")

    assert [problem.split(":")[0] for problem in problems(tmp_path)] == [
        f"OBJ-1 {unnamed.relative_to(tmp_path).as_posix()}",
        "OBJ-3 objects/unfinished.tmp",
        "CACHE-1 scope.json",
        "REC-2 feeds/companyfacts/versions.jsonl",
        "REC-8 feeds/companyfacts/versions.jsonl",
        "REC-6 feeds/filings/versions.jsonl",
        "REC-3 feeds/filings/versions.jsonl",
        # A 304 names a version whose record has no validators.
        "REC-5 feeds/submissions/versions.jsonl",
        "REC-7 feeds/submissions/versions.jsonl",
        "REC-4 feeds/submissions/versions.jsonl",
        "REC-5 feeds/submissions/versions.jsonl",
        "REC-1 feeds/submissions/versions.jsonl",
        # The store's own tool.
        "REC-1 feeds/submissions/versions.jsonl",
        f"OBJ-3 {unnamed.relative_to(tmp_path).as_posix()}",
    ]


@pytest.mark.spec("CACHE-1")
@pytest.mark.parametrize(
    ("status", "error", "names"),
    [
        pytest.param(200, None, None, id="REC-4 a 200 without an error names no body"),
        pytest.param(304, None, None, id="REC-5 a 304 names nothing without an error"),
        pytest.param(304, None, B, id="REC-5 a 304 names another version than the latest"),
        pytest.param(304, None, A, id="REC-5 a 304 names a version whose record has no validators"),
        pytest.param(404, None, A, id="REC-6 a 404 names a body"),
        pytest.param(200, "body cut short", A, id="REC-6 a 200 with an error names a body"),
        pytest.param(None, None, None, id="REC-7 no response without an error"),
    ],
)
def test_the_writer_refuses_a_record_that_would_break_the_stores(
    tmp_path: Path, status: int | None, error: str | None, names: bytes | None
) -> None:
    fetch(tmp_path, SUBMISSIONS, 200, body=A)
    fetch(tmp_path, SUBMISSIONS, 200, body=B)
    fetch(tmp_path, SUBMISSIONS, 200, body=A)
    log = files(tmp_path)["feeds/submissions/versions.jsonl"]

    with _cache.writing(tmp_path, SUBMISSIONS) as writer:
        stored = _cache.Stored(sha(names), len(names)) if names is not None else None
        with pytest.raises(ValueError, match=r"\(REC-[4-7]\)"):
            writer.append(
                requested_at=REQUESTED_AT, attempts=1, status=status, error=error, stored=stored
            )

    assert files(tmp_path)["feeds/submissions/versions.jsonl"] == log


@pytest.mark.spec("CACHE-1")
def test_the_writer_refuses_a_record_whose_fields_would_break_the_stores(tmp_path: Path) -> None:
    with _cache.writing(tmp_path, SUBMISSIONS) as writer:
        stored = writer.write_object([A])
        with pytest.raises(ValueError, match=r"\(REC-1\)"):
            writer.append(
                requested_at=datetime(2026, 10, 19), attempts=1, status=200, stored=stored
            )
        with pytest.raises(ValueError, match=r"\(REC-1\)"):
            writer.append(requested_at=REQUESTED_AT, attempts=0, status=200, stored=stored)
        missing = _cache.Stored(sha(B), len(B))
        with pytest.raises(ValueError, match=r"\(REC-3\)"):
            writer.append(requested_at=REQUESTED_AT, attempts=1, status=200, stored=missing)

    assert not (tmp_path / "feeds").exists()


def test_the_writer_writes_only_while_the_lock_is_held(tmp_path: Path) -> None:
    with _cache.writing(tmp_path, SUBMISSIONS) as writer:
        pass

    with pytest.raises(RuntimeError, match="no longer held"):
        writer.write_object([A])
    with pytest.raises(RuntimeError, match="no longer held"):
        writer.append(requested_at=REQUESTED_AT, attempts=1, status=404)
    assert sorted(files(tmp_path)) == [".lock"]


@pytest.mark.spec("CACHE-2")
def test_an_object_is_written_to_a_tmp_file_flushed_then_renamed_into_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = bytes(range(256)) * 1000
    events: list[Any] = []
    fsync, replace = os.fsync, os.replace

    def recording_fsync(descriptor: int) -> None:
        events.append("fsync")
        fsync(descriptor)

    def recording_replace(source: Path, destination: Path) -> None:
        temporary = Path(source)
        events.append(("replace", temporary.parent, temporary.suffix, destination))
        assert gzip.decompress(temporary.read_bytes()) == body
        replace(source, destination)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    monkeypatch.setattr(os, "replace", recording_replace)

    with _cache.writing(tmp_path, SUBMISSIONS) as writer:
        stored = writer.write_object([body[:100_000], body[100_000:]])

    assert events == [
        "fsync",
        ("replace", tmp_path / "objects", ".tmp", object_path(tmp_path, body)),
    ]
    assert stored == _cache.Stored(sha(body), len(body))
    assert gzip.decompress(object_path(tmp_path, body).read_bytes()) == body
    assert list((tmp_path / "objects").glob("*.tmp")) == []


@pytest.mark.spec("CACHE-2")
def test_an_object_the_cache_holds_is_never_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetch(tmp_path, SUBMISSIONS, 200, body=A)
    path = object_path(tmp_path, A)
    before = path.stat()
    replaced: list[Any] = []
    monkeypatch.setattr(os, "replace", lambda *paths: replaced.append(paths))

    with _cache.writing(tmp_path, COMPANYFACTS) as writer:
        stored = writer.write_object([A])

    assert stored == _cache.Stored(sha(A), len(A))
    assert replaced == []
    assert (path.stat().st_ino, path.stat().st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert list((tmp_path / "objects").glob("*.tmp")) == []


@pytest.mark.spec("CACHE-2")
def test_a_body_that_fails_midway_stores_nothing(tmp_path: Path) -> None:
    def cut_short() -> Iterator[bytes]:
        yield A
        raise ConnectionResetError("the connection failed mid-stream")

    with _cache.writing(tmp_path, SUBMISSIONS) as writer, pytest.raises(ConnectionResetError):
        writer.write_object(cut_short())

    assert list((tmp_path / "objects").rglob("*")) == []


@pytest.mark.spec("CACHE-3")
def test_records_are_only_appended_and_objects_only_added(tmp_path: Path) -> None:
    steps: list[Callable[[], object]] = [
        lambda: fetch(tmp_path, SUBMISSIONS, 200, body=A),
        lambda: fetch(tmp_path, SUBMISSIONS, 200, body=B),
        lambda: fetch(tmp_path, SUBMISSIONS, 200, body=A, etag='"a"'),
        lambda: fetch(tmp_path, SUBMISSIONS, 304, names=A, etag='"a"'),
        lambda: fetch(tmp_path, SUBMISSIONS, 404),
        lambda: fetch(tmp_path, COMPANYFACTS, 200, body=B),
        lambda: read_body(SUBMISSIONS, Cache(tmp_path)),
        lambda: read_body(COMPANYFACTS, Cache(tmp_path)),
    ]
    earlier: dict[str, bytes] = {}

    for step in steps:
        step()
        now = files(tmp_path)
        for name, content in earlier.items():
            assert name in now
            if name.endswith(".jsonl"):
                assert now[name].startswith(content)
            else:
                assert now[name] == content
        earlier = now

    log = earlier["feeds/submissions/versions.jsonl"].decode("utf-8").splitlines()
    assert [json.loads(line)["status"] for line in log] == [200, 200, 200, 304, 404]


@pytest.mark.spec("CACHE-4")
def test_a_records_tool_is_the_library_and_its_version(tmp_path: Path) -> None:
    record = fetch(tmp_path, SUBMISSIONS, 200, body=A)

    [line] = files(tmp_path)["feeds/submissions/versions.jsonl"].decode("utf-8").splitlines()
    tool = f"edgar-asof@{metadata.version('edgar-asof')}"
    assert record["tool"] == json.loads(line)["tool"] == tool


# A snapshot store


def snapshot_store(directory: Path) -> Path:
    """A snapshot store's `data/` directory, laid out as the store's §4 gives it.

    Its records have the fields the store's version 1.0.0 added to the
    table, which a reader ignores (the store's REC-9).
    """
    data = directory / "data"
    (data / "imports").mkdir(parents=True)
    (data / "README.md").write_text("The snapshot store: spec/snapshots.md.\n", encoding="utf-8")
    scope = {"urls": [{"url": "https://data.sec.gov/", "reason": "A test's scope."}]}
    (data / "scope.json").write_text(json.dumps(scope), encoding="utf-8")
    manifest = {
        "import": "companyfacts-2026-10-06",
        "started_at": "2026-10-06T18:04:12.345Z",
        "tool": "pipeline/import.py@0123456789abcdef0123456789abcdef01234567",
        "inputs": [{"feed": "submissions", "url": SUBMISSIONS, "sha256": sha(A)}],
    }
    (data / "imports" / "companyfacts-2026-10-06.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    later = {"received_at": "2026-10-07T17:40:13.702Z", "date": "Wed, 07 Oct 2026 17:40:13 GMT"}
    put_version(data, SUBMISSIONS, A, **later)
    put_version(data, COMPANYFACTS, B, **later)
    put_version(data, HEADER, A, last_modified="Wed, 07 Oct 2026 17:40:13 GMT", **later)
    return data


@pytest.mark.spec("CACHE-5")
def test_a_snapshot_store_is_read_as_a_cache(tmp_path: Path) -> None:
    data = snapshot_store(tmp_path)
    before = files(data)
    cache = Cache(data)

    assert [read_body(url, cache).content for url in (SUBMISSIONS, COMPANYFACTS, HEADER)] == [
        A,
        B,
        A,
    ]
    assert files(data) == before


@pytest.mark.spec("CACHE-5")
def test_the_library_never_writes_into_a_snapshot_store(tmp_path: Path) -> None:
    data = snapshot_store(tmp_path)
    before = files(data)

    with pytest.raises(SnapshotStoreError) as raised, _cache.writing(data, SUBMISSIONS):
        pytest.fail("The library wrote into a snapshot store.")

    assert raised.value.url == SUBMISSIONS
    assert files(data) == before


@pytest.mark.spec("CACHE-5")
def test_any_directory_that_holds_a_scope_json_is_never_written_into(tmp_path: Path) -> None:
    (tmp_path / "scope.json").write_text("{}", encoding="utf-8")

    with pytest.raises(SnapshotStoreError), _cache.writing(tmp_path, SUBMISSIONS):
        pytest.fail("The library wrote into a directory that holds a scope.json.")

    assert sorted(files(tmp_path)) == ["scope.json"]


# The lock

LOCKING = """
import sys
from pathlib import Path

from edgar_asof import _cache

print("locking", flush=True)
with _cache.writing(Path(sys.argv[1]), sys.argv[2]):
    print("locked", flush=True)
"""


@pytest.mark.spec("CACHE-6")
def test_one_process_writes_into_a_cache_at_a_time(tmp_path: Path) -> None:
    with _cache.writing(tmp_path, SUBMISSIONS):
        other = subprocess.Popen(
            [sys.executable, "-c", LOCKING, str(tmp_path), COMPANYFACTS],
            stdout=subprocess.PIPE,
            text=True,
        )
        assert other.stdout is not None
        try:
            assert other.stdout.readline() == "locking\n"
            # The other process waits while this one holds the lock.
            ready, _, _ = select.select([other.stdout], [], [], 1)
            assert ready == []
        except BaseException:
            other.kill()
            raise

    output, _ = other.communicate(timeout=30)
    assert (output, other.returncode) == ("locked\n", 0)


@pytest.mark.spec("CACHE-6")
def test_a_read_takes_no_lock(tmp_path: Path) -> None:
    put_version(tmp_path, SUBMISSIONS, A)
    read: list[Body] = []

    with _cache.writing(tmp_path, COMPANYFACTS):
        reader = threading.Thread(
            target=lambda: read.append(read_body(SUBMISSIONS, Cache(tmp_path)))
        )
        reader.start()
        reader.join(timeout=10)
        alive = reader.is_alive()

    reader.join()
    assert not alive
    assert [body.content for body in read] == [A]


@pytest.mark.spec("CACHE-6")
@pytest.mark.parametrize(
    "unfinished",
    [
        pytest.param('{"feed": "submissions", "url": "https://data.sec.gov/sub', id="cut short"),
        pytest.param(json.dumps(stored_record(SUBMISSIONS, B)), id="a whole record"),
    ],
)
def test_a_reader_ignores_a_last_line_that_doesnt_end_in_a_newline(
    tmp_path: Path, unfinished: str
) -> None:
    put_version(tmp_path, SUBMISSIONS, A)
    put_version(tmp_path, SUBMISSIONS, B)
    put_version(tmp_path, SUBMISSIONS, A)
    put_lines(tmp_path, SUBMISSIONS, unfinished)

    assert read_body(SUBMISSIONS, Cache(tmp_path)).content == A


# Versions


@pytest.mark.spec("CACHE-7")
def test_versions_are_the_distinct_bodies_of_a_url_numbered_by_first_appearance(
    tmp_path: Path,
) -> None:
    put_version(tmp_path, SUBMISSIONS, A)
    put_version(tmp_path, SUBMISSIONS, B)
    put_version(tmp_path, SUBMISSIONS, None)
    put_version(tmp_path, SUBMISSIONS, A)
    put_version(tmp_path, COMPANYFACTS, B)

    assert _cache.versions(tmp_path, SUBMISSIONS) == [sha(A), sha(B)]
    assert _cache.versions(tmp_path, COMPANYFACTS) == [sha(B)]
    assert _cache.versions(tmp_path, FURTHER) == []


@pytest.mark.spec("CACHE-9")
def test_the_caller_names_the_caches_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_version(tmp_path / "one", SUBMISSIONS, A)
    put_version(tmp_path / "two", SUBMISSIONS, B)
    monkeypatch.chdir(tmp_path)

    parameters = inspect.signature(Cache).parameters
    assert parameters["directory"].default is inspect.Parameter.empty
    assert inspect.signature(read_body).parameters["source"].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        Cache()  # type: ignore[call-arg]
    assert read_body(SUBMISSIONS, Cache("one")).content == A
    assert read_body(SUBMISSIONS, Cache(tmp_path / "two")).content == B


# A cache that a read can't read


@pytest.mark.spec("CACHE-10")
@pytest.mark.parametrize(
    "line",
    [
        pytest.param("not JSON", id="not JSON"),
        pytest.param("", id="blank"),
        pytest.param(json.dumps([SUBMISSIONS, sha(A)]), id="an array"),
        pytest.param(json.dumps({"sha256": sha(A)}), id="no url"),
        pytest.param(json.dumps({"url": 5, "sha256": sha(A)}), id="a url that isn't a string"),
        pytest.param(json.dumps({"url": SUBMISSIONS}), id="no sha256"),
        pytest.param(json.dumps({"url": SUBMISSIONS, "sha256": sha(A).upper()}), id="upper case"),
        pytest.param(json.dumps({"url": SUBMISSIONS, "sha256": sha(A)[:63]}), id="63 digits"),
        pytest.param(json.dumps({"url": SUBMISSIONS, "sha256": 5}), id="a number"),
        pytest.param(f'{{"url": "{SUBMISSIONS}", "sha256": null, "bytes": NaN}}', id="NaN"),
        pytest.param(json.dumps(stored_record(FURTHER, None) | {"sha256": "x"}), id="another url"),
    ],
)
def test_a_log_line_a_read_cant_read_raises_cache_error(tmp_path: Path, line: str) -> None:
    put_version(tmp_path, SUBMISSIONS, A)
    log = put_lines(tmp_path, SUBMISSIONS, line + "\n")
    put_version(tmp_path, SUBMISSIONS, A)
    before = files(tmp_path)

    with pytest.raises(CacheError) as raised:
        read_body(SUBMISSIONS, Cache(tmp_path, user_agent=USER_AGENT))

    assert (raised.value.url, raised.value.path) == (SUBMISSIONS, log)
    assert "line 2" in str(raised.value)
    assert files(tmp_path) == before


@pytest.mark.spec("CACHE-10")
def test_a_log_line_that_isnt_utf_8_raises_cache_error(tmp_path: Path) -> None:
    put_version(tmp_path, SUBMISSIONS, A)
    log = tmp_path / "feeds" / "submissions" / "versions.jsonl"
    with log.open("ab") as file:
        file.write(b'{"url": "\xff", "sha256": null}\n')

    with pytest.raises(CacheError) as raised:
        read_body(SUBMISSIONS, Cache(tmp_path))

    assert raised.value.path == log


@pytest.mark.spec("CACHE-10")
def test_a_log_that_cant_be_read_raises_cache_error(tmp_path: Path) -> None:
    log = tmp_path / "feeds" / "submissions" / "versions.jsonl"
    log.mkdir(parents=True)

    with pytest.raises(CacheError) as raised:
        read_body(SUBMISSIONS, Cache(tmp_path))

    assert raised.value.path == log


@pytest.mark.spec("CACHE-10")
def test_a_read_reads_only_the_log_of_its_urls_feed(tmp_path: Path) -> None:
    put_version(tmp_path, SUBMISSIONS, A)
    put_lines(tmp_path, COMPANYFACTS, "not JSON\n")

    assert read_body(SUBMISSIONS, Cache(tmp_path)).content == A


def gzip_of_another_body(body: bytes) -> bytes:
    return gzip.compress(body + b" and more")


@pytest.mark.spec("CACHE-10")
@pytest.mark.parametrize(
    "spoil",
    [
        pytest.param(lambda path: path.unlink(), id="missing"),
        pytest.param(lambda path: path.write_bytes(A), id="not gzip"),
        pytest.param(lambda path: path.write_bytes(path.read_bytes()[:-9]), id="cut short"),
        pytest.param(lambda path: path.write_bytes(gzip_of_another_body(A)), id="another body"),
        pytest.param(lambda path: (path.unlink(), path.mkdir()), id="unreadable"),
    ],
)
def test_an_object_a_read_cant_read_raises_cache_error(
    tmp_path: Path, spoil: Callable[[Path], object]
) -> None:
    put_version(tmp_path, SUBMISSIONS, B)
    put_version(tmp_path, SUBMISSIONS, A)
    path = object_path(tmp_path, A)
    spoil(path)
    before = files(tmp_path)

    with pytest.raises(CacheError) as raised:
        read_body(SUBMISSIONS, Cache(tmp_path, user_agent=USER_AGENT))

    assert (raised.value.url, raised.value.path) == (SUBMISSIONS, path)
    assert files(tmp_path) == before


@pytest.mark.spec("CACHE-10")
def test_an_empty_object_isnt_gzip_data_even_for_the_empty_body(tmp_path: Path) -> None:
    put_version(tmp_path, SUBMISSIONS, b"")
    # The empty body's gzip data is read.
    assert read_body(SUBMISSIONS, Cache(tmp_path)).content == b""
    path = object_path(tmp_path, b"")
    path.write_bytes(b"")

    with pytest.raises(CacheError) as raised:
        read_body(SUBMISSIONS, Cache(tmp_path))

    assert (raised.value.url, raised.value.path) == (SUBMISSIONS, path)
    assert "isn't gzip data" in str(raised.value)


@pytest.mark.spec("CACHE-10")
@pytest.mark.parametrize(
    "validators",
    [
        pytest.param({"etag": '"a"'}, id="etag"),
        pytest.param({"last_modified": "Wed, 07 Oct 2026 17:40:13 GMT"}, id="last_modified"),
    ],
)
def test_a_read_that_would_send_validators_first_reads_their_versions_object(
    tmp_path: Path, validators: dict[str, str]
) -> None:
    put_version(tmp_path, HEADER, A, **validators)
    put_version(tmp_path, HEADER, None)
    path = object_path(tmp_path, A)
    path.write_bytes(A)
    before = files(tmp_path)

    with pytest.raises(CacheError) as raised:
        read_body(HEADER, Cache(tmp_path, user_agent=USER_AGENT), fresh=True)

    assert (raised.value.url, raised.value.path) == (HEADER, path)
    assert files(tmp_path) == before


# The function and types of reading


@pytest.mark.spec("READ-1")
def test_the_package_gives_the_function_and_types_of_reading() -> None:
    def parameters(function: Callable[..., object]) -> list[tuple[str, str, object]]:
        return [
            (name, parameter.kind.name, parameter.default)
            for name, parameter in inspect.signature(function).parameters.items()
        ]

    def fields(kind: type) -> list[str]:
        return [field.name for field in dataclasses.fields(kind)]

    empty = inspect.Parameter.empty
    assert parameters(read_body) == [
        ("url", "POSITIONAL_OR_KEYWORD", empty),
        ("source", "POSITIONAL_OR_KEYWORD", empty),
        ("fresh", "KEYWORD_ONLY", False),
    ]
    assert parameters(Cache) == [
        ("directory", "POSITIONAL_OR_KEYWORD", empty),
        ("user_agent", "KEYWORD_ONLY", None),
    ]
    assert parameters(Bodies) == [("bodies", "POSITIONAL_OR_KEYWORD", empty)]
    assert fields(Cache) == ["directory", "user_agent"]
    assert fields(Bodies) == ["bodies"]
    assert fields(Body) == ["url", "sha256", "content"]
    assert fields(BodyRef) == ["url", "sha256"]
    assert edgar_asof.Source.__value__ == Cache | Bodies
    for error in (
        BodyNotGivenError,
        CacheError,
        ForbiddenError,
        SnapshotStoreError,
        NoUserAgentError,
        FetchError,
    ):
        assert issubclass(error, ReadError)
    assert issubclass(ReadError, Exception)
    assert set(edgar_asof.__all__) >= {
        "read_body",
        "Source",
        "Cache",
        "Bodies",
        "Body",
        "BodyRef",
        "ReadError",
        "BodyNotGivenError",
        "CacheError",
        "ForbiddenError",
        "SnapshotStoreError",
        "NoUserAgentError",
        "FetchError",
    }


@pytest.mark.spec("READ-1")
def test_each_error_names_the_url_read(tmp_path: Path) -> None:
    errors = [
        ReadError(SUBMISSIONS, "a read failed"),
        BodyNotGivenError(SUBMISSIONS, "no body was given"),
        CacheError(SUBMISSIONS, "the object is missing", path=tmp_path / "x.gz"),
        ForbiddenError(SUBMISSIONS, "a 403"),
        SnapshotStoreError(SUBMISSIONS, "a snapshot store"),
        NoUserAgentError(SUBMISSIONS, "no user agent"),
        FetchError(SUBMISSIONS, "a 404", status=404, error=None),
    ]

    assert [(error.url, SUBMISSIONS in str(error)) for error in errors] == [(SUBMISSIONS, True)] * 7
    cache_error = errors[2]
    fetch_error = errors[6]
    assert isinstance(cache_error, CacheError)
    assert isinstance(fetch_error, FetchError)
    assert cache_error.path == tmp_path / "x.gz"
    assert str(tmp_path / "x.gz") in str(cache_error)
    assert (fetch_error.status, fetch_error.error) == (404, None)


@pytest.mark.spec("READ-1")
def test_each_type_but_the_errors_is_immutable(tmp_path: Path) -> None:
    given = {SUBMISSIONS: A}
    bodies = Bodies(given)
    instances: list[Any] = [
        Cache(tmp_path, user_agent=USER_AGENT),
        bodies,
        Body(SUBMISSIONS, sha(A), A),
        BodyRef(SUBMISSIONS, sha(A)),
    ]

    for instance in instances:
        for field in dataclasses.fields(instance):
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(instance, field.name, None)
    with pytest.raises(TypeError):
        bodies.bodies[COMPANYFACTS] = B  # type: ignore[index]
    given[COMPANYFACTS] = B
    given[SUBMISSIONS] = B
    assert dict(bodies.bodies) == {SUBMISSIONS: A}


@pytest.mark.spec("READ-1")
def test_a_body_ref_is_hashable_and_equal_to_another_with_the_same_fields() -> None:
    ref = BodyRef(SUBMISSIONS, sha(A))

    assert ref == BodyRef(SUBMISSIONS, sha(A))
    assert ref != BodyRef(SUBMISSIONS, sha(B))
    assert ref != BodyRef(COMPANYFACTS, sha(A))
    assert {ref, BodyRef(SUBMISSIONS, sha(A))} == {ref}


@pytest.mark.spec("READ-1")
def test_a_caches_directory_is_a_path_and_its_repr_doesnt_show_its_user_agent(
    tmp_path: Path,
) -> None:
    cache = Cache(str(tmp_path), user_agent=USER_AGENT)

    assert cache.directory == tmp_path
    assert isinstance(cache.directory, Path)
    assert Cache(tmp_path).directory == tmp_path
    assert cache.user_agent == USER_AGENT
    assert USER_AGENT not in repr(cache)
    assert "test@example.com" not in repr(cache)


def test_the_repr_of_a_body_and_of_bodies_leaves_out_the_bodies() -> None:
    # A body can be megabytes.
    body = b"a body of the test " * 1000

    assert "a body of the test" not in repr(Body(SUBMISSIONS, sha(body), body))
    assert "a body of the test" not in repr(Bodies({SUBMISSIONS: body, COMPANYFACTS: body}))


# Reading bodies the caller gives


@pytest.fixture
def requests(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What a test sends or looks up on any host, this one included."""
    sent: list[str] = []

    def recording(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
        def record(*args: Any, **kwargs: Any) -> Any:
            sent.append(name)
            return function(*args, **kwargs)

        return record

    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, recording(name, getattr(socket.socket, name)))
    monkeypatch.setattr(socket, "getaddrinfo", recording("getaddrinfo", socket.getaddrinfo))
    return sent


@pytest.mark.spec("READ-2")
def test_a_read_from_given_bodies_requests_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, requests: list[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    body = read_body(HEADER, Bodies({HEADER: A, SUBMISSIONS: B}))

    assert body == Body(HEADER, sha(A), A)
    assert requests == []
    assert files(tmp_path) == {}


@pytest.mark.spec("READ-2")
def test_a_read_from_given_bodies_without_the_urls_body_raises_body_not_given_error(
    requests: list[str],
) -> None:
    with pytest.raises(BodyNotGivenError) as raised:
        read_body(COMPANYFACTS, Bodies({SUBMISSIONS: A}))

    assert raised.value.url == COMPANYFACTS
    assert requests == []


@pytest.mark.spec("READ-3")
def test_a_read_returns_the_url_the_body_and_its_sha256(tmp_path: Path) -> None:
    put_version(tmp_path, COMPANYFACTS, B)

    assert read_body(COMPANYFACTS, Cache(tmp_path)) == Body(COMPANYFACTS, sha(B), B)
    assert read_body(COMPANYFACTS, Bodies({COMPANYFACTS: A})) == Body(COMPANYFACTS, sha(A), A)


@pytest.mark.spec("READ-3")
@pytest.mark.parametrize(
    ("bodies", "latest"),
    [
        pytest.param([A], A, id="one version"),
        pytest.param([A, B], B, id="a new version"),
        pytest.param([A, B, None], B, id="a record that names nothing"),
        pytest.param([A, B, A], A, id="a return to an earlier version"),
        pytest.param([B, A, None, None], A, id="records that name nothing"),
    ],
)
def test_a_read_from_a_cache_returns_the_version_its_urls_latest_record_with_a_sha256_names(
    tmp_path: Path, bodies: list[bytes | None], latest: bytes
) -> None:
    for body in bodies:
        put_version(tmp_path, SUBMISSIONS, body)
    # Another URL's later record names another body.
    put_version(tmp_path, FURTHER, b"another URL's")

    assert read_body(SUBMISSIONS, Cache(tmp_path)) == Body(SUBMISSIONS, sha(latest), latest)


@pytest.mark.spec("READ-3")
def test_a_read_from_given_bodies_returns_the_body_given_unchanged() -> None:
    # Bytes that look gzip-encoded are given after any encoding is removed.
    given = gzip.compress(A)

    body = read_body(FURTHER, Bodies({FURTHER: given}))

    assert body.content == given
    assert body.sha256 == sha(given)


REFUSED = [
    "http://data.sec.gov/submissions/CIK0000320193.json",
    "https://data.sec.gov:443/submissions/CIK0000320193.json",
    "https://user@data.sec.gov/submissions/CIK0000320193.json",
    "https://efts.sec.gov/LATEST/search-index?q=CIK0000320193",
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193",
    "https://data.sec.gov/submissions/",
    "https://data.sec.gov/submissions/.",
    "https://data.sec.gov/submissions/..",
    "https://data.sec.gov/submissions/CIK0000320193/filings.json",
    "https://data.sec.gov/submissions/CIK0000320193.json?q=1",
    "https://data.sec.gov/submissions/CIK0000320193.json#filings",
    "https://data.sec.gov/api/xbrl/companyfacts/CIK320193.json",
    "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000000.json",
    "https://data.sec.gov/api/xbrl/companyfacts/CIK00003201930.json",
    "https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/Assets.json",
    "https://www.sec.gov/Archives/edgar/data/0001018724/000110465925012345/"
    "0001104659-25-012345-index-headers.html",
    "https://www.sec.gov/Archives/edgar/data/1018724/000110465925012345/"
    "0001104659-25-012346-index-headers.html",
    "https://www.sec.gov/Archives/edgar/data/1018724/000110465925012345/index.json",
    "https://www.sec.gov/Archives/edgar/data/1018724/000110465925012345/"
    "0001104659-25-012345-index.html",
    "https://data.sec.gov/Archives/edgar/data/1018724/000110465925012345/"
    "0001104659-25-012345-index-headers.html",
]
ALLOWED = [
    SUBMISSIONS,
    FURTHER,
    "https://data.sec.gov/submissions/CIK0000000001.json",
    "https://data.sec.gov/submissions/..json",
    COMPANYFACTS,
    "https://data.sec.gov/api/xbrl/companyfacts/CIK9999999999.json",
    HEADER,
    "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/0000000001-26-000001-index-headers.html",
]


@pytest.mark.spec("READ-4")
@pytest.mark.parametrize("url", REFUSED)
def test_a_url_of_no_feed_raises_value_error_before_anything_is_read(
    tmp_path: Path, url: str
) -> None:
    for feed in _feeds.FEEDS:
        log = tmp_path / "feeds" / feed / "versions.jsonl"
        log.parent.mkdir(parents=True)
        log.write_text("not JSON\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not a URL of a feed"):
        read_body(url, Cache(tmp_path))
    with pytest.raises(ValueError, match="not a URL of a feed"):
        read_body(url, Bodies({}))
    with pytest.raises(ValueError, match="not a URL of a feed"):
        Bodies({SUBMISSIONS: A, url: B})


@pytest.mark.spec("READ-4")
@pytest.mark.parametrize("url", ALLOWED)
def test_a_url_of_a_feed_is_read(url: str) -> None:
    assert read_body(url, Bodies({url: A})).content == A


@pytest.mark.spec("READ-4")
@pytest.mark.parametrize("user_agent", ["Test Runner", "", "test at example.com"])
def test_a_user_agent_without_an_at_sign_raises_value_error(
    tmp_path: Path, user_agent: str
) -> None:
    with pytest.raises(ValueError, match="contains an @"):
        Cache(tmp_path, user_agent=user_agent)


@pytest.mark.spec("READ-4")
def test_a_fresh_read_from_given_bodies_raises_value_error(requests: list[str]) -> None:
    with pytest.raises(ValueError, match="can't be fetched"):
        read_body(SUBMISSIONS, Bodies({SUBMISSIONS: A}), fresh=True)

    assert requests == []
