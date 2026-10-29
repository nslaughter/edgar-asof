"""The client, and the reads that fetch into a cache, against a local server.

fetching.md's §4 governs the client, and its §6 and §8 the reads that
fetch. The server stands in for EDGAR: the client connects to it in place
of each URL's host, over http in place of https, and sends it the URL's
host and path, which it answers as EDGAR's hosts would. The process's pacer
runs on a clock of the test's, whose waits pass at once and are recorded,
but in the test of its real clock. The bodies are made up for the tests.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import http.client
import itertools
import json
import re
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import edgar_asof
from edgar_asof import (
    Body,
    Cache,
    CacheError,
    FetchError,
    ForbiddenError,
    NoUserAgentError,
    SnapshotStoreError,
    _cache,
    _client,
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
A = b'{"cik": "0000320193", "version": "A"}'
B = b'{"cik": "0000320193", "version": "B"}'
ETAG = '"a"'
LAST_MODIFIED = "Wed, 07 Oct 2026 17:40:13 GMT"
LATER = "Fri, 16 Oct 2026 13:30:15 GMT"
# The process's pacer, before the tests' fixture replaces it.
PACER = _client.PACER


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def object_name(body: bytes) -> str:
    return f"objects/{sha(body)[:2]}/{sha(body)}.gz"


def files(directory: Path) -> dict[str, bytes]:
    """Every file under a directory, hidden ones included, with its bytes."""
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def objects(directory: Path) -> list[str]:
    return [name for name in files(directory) if name.startswith("objects/")]


def log(directory: Path, url: str) -> list[dict[str, Any]]:
    """The URL's records, in its feed's log."""
    path = directory / "feeds" / _feeds.feed(url) / "versions.jsonl"
    if not path.exists():
        return []
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [record for record in records if record["url"] == url]


def stamp(when: datetime) -> str:
    """A time as a record's `requested_at` gives it."""
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# The local server


@dataclass
class Reply:
    """What the server sends for one request."""

    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    # Content-Length gives the whole body's length, unless `headers` give
    # one, the body is chunked, or `length` is False.
    length: bool = True
    chunked: bool = False
    # How many of the body's bytes, as sent, to send, or None for all of them.
    sent: int | None = None
    # Whether the connection is then reset, rather than closed.
    reset: bool = False
    # Whether the connection is closed without a response.
    drop: bool = False
    # Seconds to wait before the response, and before each quarter of the body.
    delay: float = 0.0
    pause: float = 0.0


@dataclass
class Request:
    """A request the server received."""

    url: str
    # Each header's name in lower case.
    headers: dict[str, str]
    # When it arrived, by the server's clock, and by the wall clock.
    at: float
    received_at: datetime


Route = Reply | Callable[[Request], Reply]


@dataclass
class Edgar:
    """The server: the replies for each URL, in turn, and what it received."""

    clock: Callable[[], float]
    replies: dict[str, list[Route]] = field(default_factory=dict)
    requests: list[Request] = field(default_factory=list)
    # Each connection's host and timeout, as the client asked for them.
    connections: list[tuple[str, float]] = field(default_factory=list)

    def serve(self, url: str, *replies: Route) -> None:
        """Answer the URL's requests with these replies, in turn, and the last one after them."""
        self.replies[url] = list(replies)

    def reply(self, request: Request) -> Reply:
        queue = self.replies.get(request.url)
        if not queue:
            return Reply(404)
        route = queue.pop(0) if len(queue) > 1 else queue[0]
        return route(request) if callable(route) else route

    def urls(self) -> list[str]:
        return [request.url for request in self.requests]


def quarters(body: bytes) -> list[bytes]:
    size = max(1, -(-len(body) // 4))
    return [body[start : start + size] for start in range(0, len(body), size)]


def chunked(body: bytes) -> bytes:
    """A body in the chunked transfer coding, in four chunks."""
    pieces = [f"{len(piece):x}\r\n".encode() + piece + b"\r\n" for piece in quarters(body)]
    return b"".join(pieces) + b"0\r\n\r\n"


class Clock:
    """The pacer's clock in a test: each wait passes at once, and is recorded."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """A pacer of the test's own, so that no test's 403 stops another's requests.

    It runs on the test's clock, with no interval between requests, but in
    the tests of CLIENT-7.
    """
    clock = Clock()
    pacer = _client.Pacer(interval=0, clock=clock.time, sleep=clock.sleep)
    monkeypatch.setattr(_client, "PACER", pacer)
    return clock


@pytest.fixture
def edgar(monkeypatch: pytest.MonkeyPatch, clock: Clock) -> Iterator[Edgar]:
    state = Edgar(clock.time)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request = Request(
                f"https://{self.headers['Host']}{self.path}",
                {name.lower(): value for name, value in self.headers.items()},
                state.clock(),
                datetime.now(UTC),
            )
            state.requests.append(request)
            reply = state.reply(request)
            time.sleep(reply.delay)
            self.close_connection = True
            if reply.drop:
                return
            headers = dict(reply.headers)
            body = reply.body
            if reply.chunked:
                headers["Transfer-Encoding"] = "chunked"
                body = chunked(body)
            elif reply.length:
                headers.setdefault("Content-Length", str(len(body)))
            try:
                self.send_response(reply.status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                for piece in quarters(body[: reply.sent]):
                    time.sleep(reply.pause)
                    self.wfile.write(piece)
                if reply.reset:
                    linger = struct.pack("ii", 1, 0)
                    self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
                    self.connection.close()
            except (BrokenPipeError, ConnectionResetError):
                # The client gave up first, as a test of its timeout intends.
                pass

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()

    def connect(host: str, timeout: float) -> http.client.HTTPConnection:
        state.connections.append((host, timeout))
        return http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)

    monkeypatch.setattr(_client, "connect", connect)
    yield state
    server.shutdown()
    server.server_close()


def conditional(body: bytes, **validators: str) -> Callable[[Request], Reply]:
    """A URL whose body doesn't change: a 304 to a request with its validators, else a 200.

    `validators` are an `etag`, a `last_modified`, or both.
    """
    headers = {
        header: validators[name]
        for name, header in (("etag", "ETag"), ("last_modified", "Last-Modified"))
        if name in validators
    }

    def reply(request: Request) -> Reply:
        sent = {
            "etag": request.headers.get("if-none-match"),
            "last_modified": request.headers.get("if-modified-since"),
        }
        if any(sent[name] == value for name, value in validators.items()):
            return Reply(304, headers)
        return Reply(200, headers | {"Content-Type": "application/json"}, body)

    return reply


def cache(directory: Path) -> Cache:
    return Cache(directory, user_agent=USER_AGENT)


@dataclass
class SlowToOpen:
    """Connections to a host that open only when the test lets them."""

    # Set when a connection begins to open, and set by the test to let it.
    begun: threading.Event = field(default_factory=threading.Event)
    let: threading.Event = field(default_factory=threading.Event)


def slow_to_open(monkeypatch: pytest.MonkeyPatch, host: str) -> SlowToOpen:
    """Make the client's connections to a host wait to open until the test lets them."""
    slow = SlowToOpen()
    local = _client.connect

    def connect(to: str, timeout: float) -> http.client.HTTPConnection:
        connection = local(to, timeout)
        if to == host:
            opens = connection.connect

            def opening() -> None:
                slow.begun.set()
                slow.let.wait(timeout=30)
                opens()

            monkeypatch.setattr(connection, "connect", opening)
        return connection

    monkeypatch.setattr(_client, "connect", connect)
    return slow


def reading(url: str, source: Cache) -> tuple[threading.Thread, list[Body | Exception]]:
    """A thread that reads a URL, and what the read returns or raises, once it has."""
    outcome: list[Body | Exception] = []

    def read() -> None:
        try:
            outcome.append(read_body(url, source))
        except Exception as err:
            outcome.append(err)

    return threading.Thread(target=read), outcome


# Requests


@pytest.mark.spec("CLIENT-1")
def test_a_fetch_requests_its_url_from_the_urls_own_host(tmp_path: Path, edgar: Edgar) -> None:
    for url in (SUBMISSIONS, FURTHER, COMPANYFACTS, HEADER):
        edgar.serve(url, Reply(body=A))
        read_body(url, cache(tmp_path))

    assert edgar.urls() == [SUBMISSIONS, FURTHER, COMPANYFACTS, HEADER]
    hosts = [host for host, _ in edgar.connections]
    assert hosts == ["data.sec.gov", "data.sec.gov", "data.sec.gov", "www.sec.gov"]


@pytest.mark.spec("CLIENT-1", "CLIENT-6")
def test_a_connection_is_https_with_the_hosts_certificate_checked() -> None:
    connection = _client.connect("data.sec.gov", _client.TIMEOUT)

    assert isinstance(connection, http.client.HTTPSConnection)
    assert (connection.host, connection.port, connection.timeout) == ("data.sec.gov", 443, 60)
    context = vars(connection)["_context"]
    assert context is _client.context()
    assert (context.verify_mode, context.check_hostname) == (ssl.CERT_REQUIRED, True)


@pytest.mark.spec("CLIENT-1", "CLIENT-10")
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("location", [COMPANYFACTS, "https://example.com/"])
def test_a_redirect_isnt_followed(tmp_path: Path, edgar: Edgar, status: int, location: str) -> None:
    edgar.serve(SUBMISSIONS, Reply(status, {"Location": location}))
    edgar.serve(location, Reply(body=B))

    with pytest.raises(FetchError) as raised:
        read_body(SUBMISSIONS, cache(tmp_path))

    assert (raised.value.status, raised.value.error) == (status, None)
    assert edgar.urls() == [SUBMISSIONS]
    [record] = log(tmp_path, SUBMISSIONS)
    assert (record["status"], record["final_url"], record["sha256"]) == (status, None, None)


@pytest.mark.spec("CLIENT-2")
def test_every_request_carries_the_callers_user_agent(tmp_path: Path, edgar: Edgar) -> None:
    edgar.serve(SUBMISSIONS, Reply(503), Reply(body=A))

    read_body(SUBMISSIONS, cache(tmp_path))

    assert [request.headers["user-agent"] for request in edgar.requests] == [USER_AGENT] * 2


@pytest.mark.spec("CLIENT-2", "READ-6")
def test_without_the_callers_user_agent_nothing_is_requested(
    tmp_path: Path, edgar: Edgar, monkeypatch: pytest.MonkeyPatch
) -> None:
    # None is read from the environment or from a file.
    for name in ("SEC_USER_AGENT", "USER_AGENT", "EDGAR_USER_AGENT", "EDGAR_IDENTITY"):
        monkeypatch.setenv(name, USER_AGENT)
    for name in (".env", ".env.dev"):
        (tmp_path / name).write_text(f'SEC_USER_AGENT="{USER_AGENT}"\n')
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "cache"
    edgar.serve(SUBMISSIONS, Reply(body=A))

    with pytest.raises(NoUserAgentError) as raised:
        read_body(SUBMISSIONS, Cache(directory))

    assert raised.value.url == SUBMISSIONS
    assert edgar.requests == []
    assert not directory.exists()


@pytest.mark.spec("CLIENT-2")
def test_the_library_ships_no_user_agent() -> None:
    address = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    package = Path(edgar_asof.__file__).parent

    found = {
        path.name: address.findall(path.read_bytes())
        for path in package.rglob("*")
        if path.is_file() and path.suffix != ".pyc"
    }

    assert found
    assert {name: addresses for name, addresses in found.items() if addresses} == {}


@pytest.mark.spec("CLIENT-3")
def test_no_file_in_a_cache_holds_a_request_header(tmp_path: Path, edgar: Edgar) -> None:
    user_agent = "Distinct Requester requester-7f3a@example.com"
    used = Cache(tmp_path, user_agent=user_agent)
    another = FURTHER.replace("001", "002")
    edgar.serve(HEADER, conditional(A, etag=ETAG, last_modified=LAST_MODIFIED))
    # Each other URL's final attempt records an outcome of its own.
    edgar.serve(SUBMISSIONS, Reply(503), Reply(404))
    edgar.serve(FURTHER, Reply(drop=True))
    edgar.serve(another, Reply(body=B, sent=3))
    edgar.serve(COMPANYFACTS, Reply(200, {"Content-Encoding": "br"}, b"encoded"))

    read_body(HEADER, used)
    read_body(HEADER, used, fresh=True)
    for url in (SUBMISSIONS, FURTHER, another, COMPANYFACTS):
        with pytest.raises(FetchError):
            read_body(url, used)

    kept = b"".join(
        gzip.decompress(content) if name.endswith(".gz") else content
        for name, content in files(tmp_path).items()
    ).lower()
    for sent in (user_agent, "user-agent", "accept-encoding", "if-none-match", "if-modified-since"):
        assert sent.lower().encode() not in kept
    errors = [log(tmp_path, url)[-1]["error"] for url in (FURTHER, another, COMPANYFACTS)]
    assert all(error is not None for error in errors)
    assert len(edgar.requests) == 2 + 2 + 4 + 4 + 1


@pytest.mark.spec("CLIENT-4")
def test_each_request_sends_accept_encoding_gzip(tmp_path: Path, edgar: Edgar) -> None:
    edgar.serve(SUBMISSIONS, Reply(500), Reply(body=A))

    read_body(SUBMISSIONS, cache(tmp_path))

    assert [request.headers["accept-encoding"] for request in edgar.requests] == ["gzip"] * 2


def conditions(request: Request) -> dict[str, str]:
    return {name: value for name, value in request.headers.items() if name.startswith("if-")}


@pytest.mark.spec("CLIENT-5")
@pytest.mark.parametrize(
    ("validators", "sent"),
    [
        pytest.param(
            {"ETag": ETAG, "Last-Modified": LAST_MODIFIED},
            {"if-none-match": ETAG, "if-modified-since": LAST_MODIFIED},
            id="both",
        ),
        pytest.param({"ETag": ETAG}, {"if-none-match": ETAG}, id="etag"),
        pytest.param(
            {"Last-Modified": LAST_MODIFIED},
            {"if-modified-since": LAST_MODIFIED},
            id="last_modified",
        ),
        pytest.param({}, {}, id="neither"),
    ],
)
def test_a_fresh_read_sends_the_validators_of_the_latest_record_with_a_sha256(
    tmp_path: Path, edgar: Edgar, validators: dict[str, str], sent: dict[str, str]
) -> None:
    edgar.serve(
        HEADER,
        Reply(200, {"ETag": '"earlier"', "Last-Modified": "Mon, 05 Oct 2026 10:00:00 GMT"}, A),
        Reply(200, validators, B),
        Reply(404, {"ETag": '"missing"', "Last-Modified": LATER}),
        Reply(200, {}, B),
    )
    used = cache(tmp_path)

    read_body(HEADER, used)
    read_body(HEADER, used, fresh=True)
    # A 404 names no version, so the next read sends B's validators again.
    with pytest.raises(FetchError):
        read_body(HEADER, used, fresh=True)
    read_body(HEADER, used, fresh=True)

    assert conditions(edgar.requests[0]) == {}
    assert [conditions(request) for request in edgar.requests[2:]] == [sent, sent]


@pytest.mark.spec("CLIENT-5", "CLIENT-16")
def test_a_304s_record_keeps_the_validators_that_the_304_sent(tmp_path: Path, edgar: Edgar) -> None:
    edgar.serve(
        HEADER,
        Reply(200, {"Last-Modified": LAST_MODIFIED}, A),
        Reply(304, {"Last-Modified": LAST_MODIFIED}),
        Reply(304),
        Reply(200, {"Last-Modified": LATER}, A),
    )
    used = cache(tmp_path)

    read_body(HEADER, used)
    bodies = [read_body(HEADER, used, fresh=True) for _ in range(3)]

    assert [body.content for body in bodies] == [A, A, A]
    records = log(tmp_path, HEADER)
    assert [record["status"] for record in records] == [200, 304, 304, 200]
    assert [record["last_modified"] for record in records] == [
        LAST_MODIFIED,
        LAST_MODIFIED,
        None,
        LATER,
    ]
    # The 304 that sent no Last-Modified is the latest version's record, so
    # the next read sends none.
    sent = [request.headers.get("if-modified-since") for request in edgar.requests]
    assert sent == [None, LAST_MODIFIED, LAST_MODIFIED, None]


@pytest.mark.spec("CLIENT-6")
def test_each_attempt_times_out_after_60_seconds(tmp_path: Path, edgar: Edgar) -> None:
    edgar.serve(SUBMISSIONS, Reply(503), Reply(body=A))

    read_body(SUBMISSIONS, cache(tmp_path))

    assert edgar.connections == [("data.sec.gov", 60), ("data.sec.gov", 60)]


@pytest.mark.spec("CLIENT-6", "CLIENT-8", "READ-6")
def test_an_attempt_that_times_out_before_its_response_counts_as_no_response(
    tmp_path: Path, edgar: Edgar, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_client, "TIMEOUT", 0.3)
    edgar.serve(SUBMISSIONS, Reply(body=A, delay=1))

    with pytest.raises(FetchError) as raised:
        read_body(SUBMISSIONS, cache(tmp_path))

    assert raised.value.status is None
    assert raised.value.error == "no response: TimeoutError('timed out')"
    [record] = log(tmp_path, SUBMISSIONS)
    assert (record["attempts"], record["status"], record["error"]) == (
        4,
        None,
        raised.value.error,
    )


@pytest.mark.spec("CLIENT-6", "CLIENT-13")
def test_a_body_that_stalls_for_the_timeout_is_cut_short(
    tmp_path: Path, edgar: Edgar, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_client, "TIMEOUT", 0.3)
    edgar.serve(SUBMISSIONS, Reply(body=B, pause=1), Reply(body=A))

    assert read_body(SUBMISSIONS, cache(tmp_path)).content == A

    [record] = log(tmp_path, SUBMISSIONS)
    assert (record["attempts"], record["sha256"]) == (2, sha(A))
    assert objects(tmp_path) == [object_name(A)]


@pytest.mark.spec("CLIENT-6")
def test_a_body_that_keeps_arriving_isnt_cut_off(
    tmp_path: Path, edgar: Edgar, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_client, "TIMEOUT", 0.5)
    # Its four parts arrive over 0.8 seconds, longer than the timeout, but
    # each within it.
    edgar.serve(SUBMISSIONS, Reply(body=A, pause=0.2))

    assert read_body(SUBMISSIONS, cache(tmp_path)).content == A

    [record] = log(tmp_path, SUBMISSIONS)
    assert record["attempts"] == 1


@pytest.mark.spec("CLIENT-7")
def test_requests_from_a_process_start_at_least_0_2_seconds_apart(
    tmp_path: Path, edgar: Edgar, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_client, "PACER", _client.Pacer(clock=clock.time, sleep=clock.sleep))
    edgar.serve(SUBMISSIONS, Reply(503, {"Retry-After": "0"}), Reply(body=A))
    edgar.serve(COMPANYFACTS, Reply(body=B))

    # A retry, a fetch into another cache, and a fresh read.
    read_body(SUBMISSIONS, cache(tmp_path / "one"))
    read_body(COMPANYFACTS, cache(tmp_path / "two"))
    read_body(SUBMISSIONS, cache(tmp_path / "one"), fresh=True)

    starts = [request.at for request in edgar.requests]
    assert starts == pytest.approx([0, 0.2, 0.4, 0.6])


@pytest.mark.spec("CLIENT-7")
def test_requests_from_threads_start_at_least_0_2_seconds_apart_by_the_real_clock(
    tmp_path: Path, edgar: Edgar, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert isinstance(PACER, _client.Pacer)
    assert (PACER.interval, PACER.clock, PACER.sleep) == (0.2, time.monotonic, time.sleep)
    monkeypatch.setattr(_client, "PACER", _client.Pacer())
    edgar.clock = time.monotonic
    urls = [SUBMISSIONS, FURTHER, COMPANYFACTS, HEADER]
    for url in urls:
        edgar.serve(url, Reply(body=A))
    readers = [
        threading.Thread(target=read_body, args=(url, cache(tmp_path / str(number))))
        for number, url in enumerate(urls)
    ]

    for reader in readers:
        reader.start()
    for reader in readers:
        reader.join(timeout=30)

    assert sorted(edgar.urls()) == sorted(urls)
    starts = sorted(request.at for request in edgar.requests)
    # Each request arrives a moment after it starts, which varies a little.
    assert all(later - earlier > 0.15 for earlier, later in itertools.pairwise(starts))


@pytest.mark.spec("CLIENT-7", "CLIENT-14")
def test_a_request_whose_connection_is_slow_to_open_starts_when_its_open(
    tmp_path: Path, edgar: Edgar, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_client, "PACER", _client.Pacer(clock=clock.time, sleep=clock.sleep))
    slow = slow_to_open(monkeypatch, "www.sec.gov")
    edgar.serve(HEADER, Reply(body=A))
    edgar.serve(COMPANYFACTS, Reply(body=B))
    reader, outcome = reading(HEADER, cache(tmp_path / "one"))

    reader.start()
    assert slow.begun.wait(timeout=30)
    # While the header's connection opens, another fetch's request starts.
    read_body(COMPANYFACTS, cache(tmp_path / "two"))
    # It opens in a later millisecond than the one it began to open in.
    time.sleep(0.01)
    opened = datetime.now(UTC)
    slow.let.set()
    reader.join(timeout=30)

    assert outcome == [Body(HEADER, sha(A), A)]
    assert edgar.urls() == [COMPANYFACTS, HEADER]
    starts = [request.at for request in edgar.requests]
    assert starts == pytest.approx([0, 0.2])
    # Its record gives when it was sent, after its connection opened.
    [record] = log(tmp_path / "one", HEADER)
    assert record["requested_at"] >= stamp(opened)


@pytest.mark.spec("CLIENT-9")
def test_a_request_whose_connection_opens_after_a_403_isnt_sent(
    tmp_path: Path, edgar: Edgar, monkeypatch: pytest.MonkeyPatch
) -> None:
    slow = slow_to_open(monkeypatch, "www.sec.gov")
    edgar.serve(HEADER, Reply(body=A))
    edgar.serve(COMPANYFACTS, Reply(403))
    reader, outcome = reading(HEADER, cache(tmp_path / "one"))

    reader.start()
    assert slow.begun.wait(timeout=30)
    # While the header's connection opens, another fetch receives a 403.
    with pytest.raises(ForbiddenError):
        read_body(COMPANYFACTS, cache(tmp_path / "two"))
    slow.let.set()
    reader.join(timeout=30)

    [raised] = outcome
    assert isinstance(raised, ForbiddenError)
    assert raised.url == HEADER
    assert edgar.urls() == [COMPANYFACTS]
    # It made no attempt, so it appended no record.
    assert log(tmp_path / "one", HEADER) == []


@pytest.mark.spec("CLIENT-8")
@pytest.mark.parametrize(
    "failure",
    [
        *(pytest.param(Reply(status), id=str(status)) for status in (429, 500, 502, 503, 504)),
        pytest.param(Reply(drop=True), id="no response"),
        pytest.param(Reply(body=B, sent=10), id="a body cut short"),
    ],
)
def test_a_temporary_failure_is_retried(
    tmp_path: Path, edgar: Edgar, clock: Clock, failure: Reply
) -> None:
    edgar.serve(SUBMISSIONS, failure, Reply(body=A))

    assert read_body(SUBMISSIONS, cache(tmp_path)).content == A

    assert len(edgar.requests) == 2
    assert clock.waits == [2]
    [record] = log(tmp_path, SUBMISSIONS)
    assert (record["attempts"], record["status"], record["error"]) == (2, 200, None)


@pytest.mark.spec("CLIENT-8", "READ-6")
def test_a_fetch_makes_up_to_4_attempts_waiting_2_to_the_power_of_each(
    tmp_path: Path, edgar: Edgar, clock: Clock
) -> None:
    edgar.serve(SUBMISSIONS, Reply(503))

    with pytest.raises(FetchError) as raised:
        read_body(SUBMISSIONS, cache(tmp_path))

    assert (raised.value.url, raised.value.status, raised.value.error) == (SUBMISSIONS, 503, None)
    assert len(edgar.requests) == 4
    assert clock.waits == [2, 4, 8]
    [record] = log(tmp_path, SUBMISSIONS)
    assert (record["attempts"], record["status"], record["sha256"]) == (4, 503, None)


@pytest.mark.spec("CLIENT-8")
@pytest.mark.parametrize(
    ("retry_after", "wait"),
    [
        pytest.param("3", 3, id="seconds"),
        pytest.param("0", 0, id="none"),
        pytest.param("120", 60, id="capped"),
        pytest.param("1.5", 2, id="not digits"),
        pytest.param("soon", 2, id="neither seconds nor a date"),
    ],
)
def test_the_wait_before_a_retry_is_retry_after_in_seconds(
    tmp_path: Path, edgar: Edgar, clock: Clock, retry_after: str, wait: float
) -> None:
    edgar.serve(SUBMISSIONS, Reply(429, {"Retry-After": retry_after}), Reply(body=A))

    read_body(SUBMISSIONS, cache(tmp_path))

    assert clock.waits == [wait]


@pytest.mark.spec("CLIENT-8")
@pytest.mark.parametrize(
    ("ahead", "least", "most"),
    [
        pytest.param(30, 28, 30, id="ahead"),
        pytest.param(-30, 0, 0, id="past"),
        pytest.param(600, 60, 60, id="capped"),
    ],
)
def test_the_wait_before_a_retry_is_retry_after_as_an_http_date(
    tmp_path: Path, edgar: Edgar, clock: Clock, ahead: int, least: float, most: float
) -> None:
    def reply(request: Request) -> Reply:
        when = datetime.now(UTC) + timedelta(seconds=ahead)
        return Reply(503, {"Retry-After": format_datetime(when, usegmt=True)})

    edgar.serve(SUBMISSIONS, reply, Reply(body=A))

    read_body(SUBMISSIONS, cache(tmp_path))

    [wait] = clock.waits
    assert least <= wait <= most


@pytest.mark.spec("CLIENT-9", "READ-6")
def test_a_403_is_recorded_fails_the_read_and_stops_the_processs_requests(
    tmp_path: Path, edgar: Edgar
) -> None:
    one = cache(tmp_path / "one")
    two = tmp_path / "two"
    edgar.serve(SUBMISSIONS, Reply(body=A))
    edgar.serve(COMPANYFACTS, Reply(403))
    edgar.serve(HEADER, Reply(body=B))
    read_body(SUBMISSIONS, one)

    with pytest.raises(ForbiddenError) as raised:
        read_body(COMPANYFACTS, one)

    assert raised.value.url == COMPANYFACTS
    assert "403" in str(raised.value)
    [record] = log(one.directory, COMPANYFACTS)
    assert (record["attempts"], record["status"], record["sha256"]) == (1, 403, None)
    # Nothing more is requested, into any cache, but a read that needn't
    # fetch still reads.
    before = files(one.directory)
    for url, source, fresh in (
        (HEADER, cache(two), False),
        (SUBMISSIONS, one, True),
        (COMPANYFACTS, one, False),
    ):
        with pytest.raises(ForbiddenError) as raised:
            read_body(url, source, fresh=fresh)
        assert raised.value.url == url
    assert read_body(SUBMISSIONS, one).content == A
    assert edgar.urls() == [SUBMISSIONS, COMPANYFACTS]
    assert files(one.directory) == before
    assert not two.exists()


@pytest.mark.spec("CLIENT-9")
def test_a_403_to_a_retry_stops_the_fetch(tmp_path: Path, edgar: Edgar) -> None:
    edgar.serve(SUBMISSIONS, Reply(503), Reply(403), Reply(body=A))

    with pytest.raises(ForbiddenError):
        read_body(SUBMISSIONS, cache(tmp_path))

    assert len(edgar.requests) == 2
    [record] = log(tmp_path, SUBMISSIONS)
    assert (record["attempts"], record["status"]) == (2, 403)


@pytest.mark.spec("CLIENT-9", "CLIENT-14")
def test_a_403_to_another_fetch_stops_a_fetch_before_its_retry(
    tmp_path: Path, edgar: Edgar, clock: Clock
) -> None:
    def sleep(seconds: float) -> None:
        # While this fetch waits to retry, another one in the process
        # receives a 403.
        clock.sleep(seconds)
        _client.PACER.forbidden = True

    _client.PACER.sleep = sleep
    edgar.serve(SUBMISSIONS, Reply(503), Reply(body=A))

    with pytest.raises(ForbiddenError):
        read_body(SUBMISSIONS, cache(tmp_path))

    assert len(edgar.requests) == 1
    # It opens no connection for the retry, either.
    assert len(edgar.connections) == 1
    # Its record describes its final attempt.
    [record] = log(tmp_path, SUBMISSIONS)
    assert (record["attempts"], record["status"]) == (1, 503)


@pytest.mark.spec("CLIENT-10", "READ-6")
@pytest.mark.parametrize("status", [201, 204, 206, 400, 401, 404, 410, 501])
def test_another_status_is_recorded_without_a_retry_and_fails_the_read(
    tmp_path: Path, edgar: Edgar, status: int
) -> None:
    edgar.serve(SUBMISSIONS, Reply(status, {"Content-Type": "text/html"}, b"<p>No.</p>"))

    with pytest.raises(FetchError) as raised:
        read_body(SUBMISSIONS, cache(tmp_path))

    assert (raised.value.status, raised.value.error) == (status, None)
    assert str(status) in str(raised.value)
    assert len(edgar.requests) == 1
    [record] = log(tmp_path, SUBMISSIONS)
    assert (record["status"], record["content_type"], record["sha256"]) == (
        status,
        "text/html",
        None,
    )
    assert objects(tmp_path) == []


@pytest.mark.spec("CLIENT-16", "READ-5")
def test_a_304_returns_the_version_it_names(tmp_path: Path, edgar: Edgar) -> None:
    edgar.serve(HEADER, conditional(A, last_modified=LAST_MODIFIED))
    used = cache(tmp_path)

    first = read_body(HEADER, used)
    again = read_body(HEADER, used, fresh=True)

    assert again == first == Body(HEADER, sha(A), A)
    assert conditions(edgar.requests[1]) == {"if-modified-since": LAST_MODIFIED}
    records = log(tmp_path, HEADER)
    assert [record["status"] for record in records] == [200, 304]
    assert (records[1]["sha256"], records[1]["bytes"], records[1]["object"]) == (
        sha(A),
        len(A),
        object_name(A),
    )
    assert objects(tmp_path) == [object_name(A)]


@pytest.mark.spec("CLIENT-16", "READ-6")
@pytest.mark.parametrize("cached", [False, True], ids=["uncached", "cached without validators"])
def test_a_304_to_a_request_that_sent_no_validators_names_nothing_and_fails_the_read(
    tmp_path: Path, edgar: Edgar, cached: bool
) -> None:
    used = cache(tmp_path)
    if cached:
        edgar.serve(SUBMISSIONS, Reply(body=A), Reply(304))
        read_body(SUBMISSIONS, used)
    else:
        edgar.serve(SUBMISSIONS, Reply(304))

    with pytest.raises(FetchError) as raised:
        read_body(SUBMISSIONS, used, fresh=cached)

    error = "a 304 to a request that sent no validators"
    assert (raised.value.status, raised.value.error) == (304, error)
    assert conditions(edgar.requests[-1]) == {}
    record = log(tmp_path, SUBMISSIONS)[-1]
    assert (record["status"], record["error"], record["sha256"]) == (304, error, None)
    assert len(edgar.requests) == 1 + cached


def identity(body: bytes) -> bytes:
    return body


@pytest.mark.spec("CLIENT-11")
@pytest.mark.parametrize("chunk", [7, _client.CHUNK], ids=["small chunks", "whole"])
@pytest.mark.parametrize(
    ("encoding", "encode"),
    [
        pytest.param("gzip", gzip.compress, id="gzip"),
        pytest.param("x-gzip", gzip.compress, id="x-gzip"),
        pytest.param(" GZip ", gzip.compress, id="case and spaces"),
        pytest.param(
            "gzip", lambda body: gzip.compress(body[:9]) + gzip.compress(body[9:]), id="members"
        ),
        pytest.param("identity", identity, id="identity"),
        pytest.param(None, identity, id="none"),
    ],
)
def test_a_gzip_encoding_is_decoded_before_hashing_and_storing(
    tmp_path: Path,
    edgar: Edgar,
    monkeypatch: pytest.MonkeyPatch,
    chunk: int,
    encoding: str | None,
    encode: Callable[[bytes], bytes],
) -> None:
    monkeypatch.setattr(_client, "CHUNK", chunk)
    headers = {"Content-Encoding": encoding} if encoding is not None else {}
    edgar.serve(COMPANYFACTS, Reply(200, headers, encode(A)))

    assert read_body(COMPANYFACTS, cache(tmp_path)) == Body(COMPANYFACTS, sha(A), A)

    [record] = log(tmp_path, COMPANYFACTS)
    assert (record["sha256"], record["bytes"], record["object"]) == (
        sha(A),
        len(A),
        object_name(A),
    )
    assert gzip.decompress((tmp_path / object_name(A)).read_bytes()) == A


@pytest.mark.spec("CLIENT-12", "READ-6")
@pytest.mark.parametrize("encoding", ["br", "deflate", "zstd", "gzip, br"])
def test_another_encoding_is_recorded_and_nothing_is_stored(
    tmp_path: Path, edgar: Edgar, encoding: str
) -> None:
    edgar.serve(COMPANYFACTS, Reply(200, {"Content-Encoding": encoding}, b"encoded"))

    with pytest.raises(FetchError) as raised:
        read_body(COMPANYFACTS, cache(tmp_path))

    error = f"unsupported Content-Encoding: {encoding}"
    assert (raised.value.status, raised.value.error) == (200, error)
    assert len(edgar.requests) == 1
    [record] = log(tmp_path, COMPANYFACTS)
    assert (record["status"], record["error"], record["sha256"]) == (200, error, None)
    assert objects(tmp_path) == []


CUT_SHORT = [
    pytest.param(Reply(body=B, sent=10), id="fewer bytes than its Content-Length"),
    pytest.param(Reply(body=B, sent=10, reset=True), id="a connection reset mid-stream"),
    pytest.param(Reply(body=B, chunked=True, sent=12), id="a chunked body that ends early"),
    pytest.param(
        Reply(200, {"Content-Encoding": "gzip"}, gzip.compress(B)[:-6]),
        id="a gzip encoding that ends early",
    ),
    pytest.param(
        Reply(200, {"Content-Encoding": "gzip"}, gzip.compress(B), length=False, sent=20),
        id="a gzip encoding without a length, cut off",
    ),
    pytest.param(
        Reply(200, {"Content-Encoding": "gzip"}, b"not gzip at all"),
        id="a gzip encoding that doesn't decode",
    ),
    pytest.param(
        Reply(200, {"Content-Encoding": "gzip"}, gzip.compress(B) + b"trailing"),
        id="a gzip encoding followed by bytes that don't decode",
    ),
]


@pytest.mark.spec("CLIENT-13", "CLIENT-8")
@pytest.mark.parametrize("cut", CUT_SHORT)
def test_a_body_cut_short_stores_nothing_and_is_retried(
    tmp_path: Path, edgar: Edgar, cut: Reply
) -> None:
    edgar.serve(SUBMISSIONS, cut, Reply(body=A))

    assert read_body(SUBMISSIONS, cache(tmp_path)).content == A

    [record] = log(tmp_path, SUBMISSIONS)
    assert (record["attempts"], record["status"], record["error"]) == (2, 200, None)
    assert objects(tmp_path) == [object_name(A)]


@pytest.mark.spec("CLIENT-13", "READ-6")
def test_a_last_attempt_cut_short_records_the_status_and_an_error(
    tmp_path: Path, edgar: Edgar
) -> None:
    edgar.serve(SUBMISSIONS, Reply(body=B, sent=10))

    with pytest.raises(FetchError) as raised:
        read_body(SUBMISSIONS, cache(tmp_path))

    error = f"body cut short: 10 of {len(B)} bytes arrived"
    assert (raised.value.status, raised.value.error) == (200, error)
    [record] = log(tmp_path, SUBMISSIONS)
    assert (record["attempts"], record["status"], record["error"], record["sha256"]) == (
        4,
        200,
        error,
        None,
    )
    assert objects(tmp_path) == []


@pytest.mark.spec("CLIENT-13")
@pytest.mark.parametrize(
    "whole",
    [
        pytest.param(Reply(body=B, chunked=True), id="chunked"),
        pytest.param(Reply(body=B, length=False), id="without a length"),
    ],
)
def test_a_whole_body_without_a_content_length_is_stored(
    tmp_path: Path, edgar: Edgar, whole: Reply
) -> None:
    edgar.serve(SUBMISSIONS, whole)

    assert read_body(SUBMISSIONS, cache(tmp_path)).content == B

    assert len(edgar.requests) == 1


@pytest.mark.spec("CLIENT-14")
def test_a_fetch_appends_one_record_describing_its_final_attempt(
    tmp_path: Path, edgar: Edgar
) -> None:
    # Each reply waits, so that each attempt starts in a later millisecond.
    edgar.serve(
        SUBMISSIONS, Reply(503, delay=0.01), Reply(500, delay=0.01), Reply(body=A, delay=0.01)
    )

    read_body(SUBMISSIONS, cache(tmp_path))

    [record] = log(tmp_path, SUBMISSIONS)
    assert (record["attempts"], record["status"], record["sha256"]) == (3, 200, sha(A))
    _, second, third = (request.received_at for request in edgar.requests)
    assert stamp(second) < record["requested_at"] <= stamp(third)


@pytest.mark.spec("CLIENT-14")
def test_each_fetch_appends_exactly_one_record_after_the_object_it_names(
    tmp_path: Path, edgar: Edgar, monkeypatch: pytest.MonkeyPatch
) -> None:
    placed: list[bool] = []
    append = _cache.Writer.append

    def appending(self: _cache.Writer, **fields: Any) -> dict[str, Any]:
        stored = fields["stored"]
        placed.append(
            stored is None or (self.directory / _cache.object_name(stored.sha256)).is_file()
        )
        return append(self, **fields)

    monkeypatch.setattr(_cache.Writer, "append", appending)
    edgar.serve(HEADER, conditional(A, last_modified=LAST_MODIFIED))
    edgar.serve(SUBMISSIONS, Reply(404), Reply(503), Reply(body=A))
    edgar.serve(COMPANYFACTS, Reply(403))
    used = cache(tmp_path)
    lines = []

    def read(url: str, *, fresh: bool = False) -> None:
        with contextlib.suppress(FetchError, ForbiddenError):
            read_body(url, used, fresh=fresh)
        lines.append(sum(len(log(tmp_path, each)) for each in (HEADER, SUBMISSIONS, COMPANYFACTS)))

    read(HEADER)
    read(HEADER, fresh=True)
    read(SUBMISSIONS)
    read(SUBMISSIONS)
    read(COMPANYFACTS)

    assert lines == [1, 2, 3, 4, 5]
    assert placed == [True] * 5


@pytest.mark.spec("CLIENT-14")
@pytest.mark.parametrize(
    ("url", "user_agent"),
    [
        pytest.param(
            "https://data.sec.gov/submissions/a b.json", USER_AGENT, id="a space in the path"
        ),
        pytest.param(f"{FURTHER}é", USER_AGENT, id="a path that isn't ASCII"),
        pytest.param(SUBMISSIONS, f"{USER_AGENT}\r\nX-Other: 1", id="a header split in two"),
    ],
)
def test_a_request_that_http_client_refuses_is_no_attempt(
    tmp_path: Path, edgar: Edgar, url: str, user_agent: str
) -> None:
    edgar.serve(url, Reply(body=A))

    with pytest.raises((ValueError, http.client.HTTPException)):
        read_body(url, Cache(tmp_path, user_agent=user_agent))

    assert edgar.requests == []
    assert log(tmp_path, url) == []


@pytest.mark.spec("CLIENT-15")
def test_a_fetchs_record_goes_in_the_log_of_its_urls_feed(tmp_path: Path, edgar: Edgar) -> None:
    for url in (SUBMISSIONS, FURTHER, COMPANYFACTS, HEADER):
        edgar.serve(url, Reply(body=A))
        read_body(url, cache(tmp_path))

    logs = {
        path.parent.name: [json.loads(line) for line in path.read_text().splitlines()]
        for path in (tmp_path / "feeds").glob("*/versions.jsonl")
    }
    assert {feed: [record["url"] for record in records] for feed, records in logs.items()} == {
        "submissions": [SUBMISSIONS, FURTHER],
        "companyfacts": [COMPANYFACTS],
        "filings": [HEADER],
    }
    assert all(record["feed"] == feed for feed, records in logs.items() for record in records)


# Reads that fetch


@pytest.mark.spec("CACHE-8")
def test_a_read_fetches_only_when_the_cache_holds_no_version_of_the_url(
    tmp_path: Path, edgar: Edgar
) -> None:
    edgar.serve(SUBMISSIONS, Reply(404), Reply(body=A), Reply(body=B))
    used = cache(tmp_path)

    with pytest.raises(FetchError):
        read_body(SUBMISSIONS, used)
    # A record that names no body is no version.
    assert read_body(SUBMISSIONS, used).content == A
    assert read_body(SUBMISSIONS, used).content == A

    assert len(edgar.requests) == 2


@pytest.mark.spec("CACHE-8", "READ-5")
def test_a_fresh_read_fetches_though_the_cache_holds_a_version(
    tmp_path: Path, edgar: Edgar
) -> None:
    edgar.serve(SUBMISSIONS, Reply(body=A), Reply(body=B), Reply(body=A))
    used = cache(tmp_path)

    assert read_body(SUBMISSIONS, used).content == A
    assert read_body(SUBMISSIONS, used, fresh=True).content == B
    assert read_body(SUBMISSIONS, used).content == B
    # A body the cache holds already is returned from its object.
    assert read_body(SUBMISSIONS, used, fresh=True) == Body(SUBMISSIONS, sha(A), A)

    assert len(edgar.requests) == 3
    assert sorted(objects(tmp_path)) == sorted([object_name(A), object_name(B)])


@pytest.mark.spec("CACHE-10")
def test_a_fresh_read_that_sends_no_validators_doesnt_read_the_latest_versions_object(
    tmp_path: Path, edgar: Edgar
) -> None:
    # A fetch of submissions sends no validators (CLIENT-5), so a fresh read
    # gets the whole body, and needn't read the one the cache holds.
    edgar.serve(SUBMISSIONS, Reply(body=A), Reply(body=B))
    used = cache(tmp_path)
    read_body(SUBMISSIONS, used)
    (tmp_path / object_name(A)).write_bytes(A)

    assert read_body(SUBMISSIONS, used, fresh=True).content == B


@pytest.mark.spec("READ-5")
def test_a_read_that_fetches_makes_the_caches_directory_with_its_parents(
    tmp_path: Path, edgar: Edgar
) -> None:
    directory = tmp_path / "a" / "b" / "cache"
    edgar.serve(SUBMISSIONS, Reply(body=A))

    assert read_body(SUBMISSIONS, cache(directory)).content == A

    assert sorted(files(directory)) == [
        ".lock",
        "feeds/submissions/versions.jsonl",
        object_name(A),
    ]


# Another process that holds the cache's lock, and fetches the URL before
# it lets go.
HOLDING = """
import sys
from datetime import UTC, datetime
from pathlib import Path

from edgar_asof import _cache

directory, url, body = Path(sys.argv[1]), sys.argv[2], sys.argv[3].encode()
with _cache.writing(directory, url) as writer:
    print("locked", flush=True)
    sys.stdin.readline()
    stored = writer.write_object([body])
    writer.append(requested_at=datetime.now(UTC), attempts=1, status=200, stored=stored)
"""


@pytest.mark.spec("READ-5", "CACHE-6")
@pytest.mark.parametrize("fresh", [False, True], ids=["read", "fresh read"])
def test_a_read_waits_for_the_lock_and_then_fetches_only_if_cache_8_still_calls_for_it(
    tmp_path: Path, edgar: Edgar, fresh: bool
) -> None:
    edgar.serve(SUBMISSIONS, Reply(body=B))
    read: list[Body] = []
    reader = threading.Thread(
        target=lambda: read.append(read_body(SUBMISSIONS, cache(tmp_path), fresh=fresh))
    )
    with subprocess.Popen(
        [sys.executable, "-c", HOLDING, str(tmp_path), SUBMISSIONS, A.decode()],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as holder:
        assert holder.stdin is not None
        assert holder.stdout is not None
        try:
            assert holder.stdout.readline() == "locked\n"
            reader.start()
            reader.join(timeout=0.5)
            # The read waits while the other process holds the lock.
            assert reader.is_alive()
            assert edgar.requests == []
            holder.stdin.write("\n")
            holder.stdin.close()
            assert holder.wait(timeout=30) == 0
        except BaseException:
            holder.kill()
            raise
        finally:
            if reader.ident is not None:
                reader.join(timeout=30)

    # The other process fetched the URL, so only a fresh read fetches it again.
    assert [body.content for body in read] == [B if fresh else A]
    assert len(edgar.requests) == fresh


@pytest.mark.spec("READ-6")
def test_a_read_that_cant_fetch_raises_in_read_6s_order_before_requesting_or_writing(
    tmp_path: Path, edgar: Edgar
) -> None:
    edgar.serve(SUBMISSIONS, Reply(body=A))
    log_path = tmp_path / "feeds" / "submissions" / "versions.jsonl"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("not a record\n")
    (tmp_path / "scope.json").write_text('{"urls": []}\n')
    _client.PACER.forbidden = True
    without = Cache(tmp_path)

    def raised(error: type[Exception]) -> None:
        before = files(tmp_path)
        with pytest.raises(error):
            read_body(SUBMISSIONS, without)
        assert files(tmp_path) == before
        assert edgar.requests == []

    raised(CacheError)
    log_path.unlink()
    raised(ForbiddenError)
    _client.PACER.forbidden = False
    raised(SnapshotStoreError)
    (tmp_path / "scope.json").unlink()
    raised(NoUserAgentError)


@pytest.mark.spec("READ-6", "CACHE-5")
def test_a_read_that_would_fetch_into_a_snapshot_store_raises_snapshot_store_error(
    tmp_path: Path, edgar: Edgar
) -> None:
    edgar.serve(SUBMISSIONS, Reply(body=A))
    (tmp_path / "scope.json").write_text('{"urls": []}\n')
    before = files(tmp_path)

    with pytest.raises(SnapshotStoreError) as raised:
        read_body(SUBMISSIONS, cache(tmp_path))

    assert raised.value.url == SUBMISSIONS
    assert edgar.requests == []
    assert files(tmp_path) == before
