"""The client: one fetch of a URL from EDGAR, written into a cache with its record.

fetching.md's §4 governs it. A fetch requests its URL over https from the
URL's own host (CLIENT-1), with the caller's user agent (CLIENT-2) and the
latest version's validators (CLIENT-5). It retries what CLIENT-8 retries,
stores a 200's body (CLIENT-11 to CLIENT-13), and appends one record,
describing its final attempt (CLIENT-14). A redirect isn't followed: its
status is another one (CLIENT-10), so no URL but the one read is requested.
A process's requests are spaced (CLIENT-7), and none is sent after a 403
(CLIENT-9).
"""

from __future__ import annotations

import functools
import http.client
import math
import re
import ssl
import threading
import time
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from edgar_asof import _cache
from edgar_asof._errors import ForbiddenError

INTERVAL = 0.2  # CLIENT-7: 5 requests a second, half the SEC's maximum
TIMEOUT = 60.0  # CLIENT-6
ATTEMPTS = 4  # CLIENT-8
RETRIED = frozenset({429, 500, 502, 503, 504})
LONGEST_WAIT = 60.0
CHUNK = 1 << 16
GZIP = frozenset({"gzip", "x-gzip"})  # CLIENT-11: decoded before hashing
PLAIN = frozenset({"", "identity"})  # CLIENT-11: stored as received
# A Retry-After in seconds is digits (RFC 9110, §10.2.3).
SECONDS = re.compile(r"[0-9]+")
# zlib reads a gzip member's header and trailer with these window bits.
GZIP_MEMBER = 16 + zlib.MAX_WBITS
FORBIDDEN = (
    "a fetch in this process received a 403, which the SEC returns to clients over its limit, "
    "so edgar-asof sends no further request from this process"
)


@functools.cache
def context() -> ssl.SSLContext:
    """The TLS context of every connection, which checks the host's certificate and name."""
    return ssl.create_default_context()


def connect(host: str, timeout: float) -> http.client.HTTPConnection:
    """A connection to the host of an `https` URL that CLIENT-1 allows.

    `timeout` is for connecting, and then for each wait on the connection
    (CLIENT-6). Tests replace this with a connection to a local server that
    stands in for EDGAR.
    """
    return http.client.HTTPSConnection(host, timeout=timeout, context=context())


class Pacer:
    """When the process's requests may start: at least `interval` seconds apart (CLIENT-7).

    One pacer serves every cache the process fetches into. After a 403,
    it lets no request start (CLIENT-9).
    """

    def __init__(
        self,
        *,
        interval: float = INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = interval
        self.clock = clock
        self.sleep = sleep
        self.forbidden = False
        self.lock = threading.Lock()
        self.last = -math.inf

    def start(self) -> bool:
        """Wait until a request may start, and count it as started; or False after a 403."""
        with self.lock:
            delay = self.last + self.interval - self.clock()
            if delay > 0:
                self.sleep(delay)
            # A request that was already sent may have received a 403 meanwhile.
            if self.forbidden:
                return False
            self.last = self.clock()
            return True


PACER = Pacer()


class CutShort(Exception):
    """A body that ended before it was complete (CLIENT-13)."""


class Gunzip:
    """Decodes a gzip encoding as it arrives, member after member (RFC 1952)."""

    def __init__(self) -> None:
        self.member = zlib.decompressobj(GZIP_MEMBER)

    def decode(self, data: bytes) -> bytes:
        decoded = []
        try:
            while data:
                if self.member.eof:
                    self.member = zlib.decompressobj(GZIP_MEMBER)
                decoded.append(self.member.decompress(data))
                # What follows a member's end begins the next member.
                data = self.member.unused_data
        except zlib.error as err:
            raise CutShort(f"body cut short: its gzip encoding doesn't decode: {err}") from err
        return b"".join(decoded)

    def finish(self) -> None:
        if not self.member.eof:
            raise CutShort("body cut short: its gzip encoding ends early")


def received(response: http.client.HTTPResponse, *, gzipped: bool) -> Iterator[bytes]:
    """A 200's body as it arrives, decoded, in chunks.

    Raises CutShort if the connection fails mid-stream, if fewer bytes
    arrive than the response's length, or if its gzip encoding ends early
    or doesn't decode (CLIENT-13).
    """
    # http.client gives the length from Content-Length, unless the body is
    # chunked, and returns no more than it.
    length = response.length
    gunzip = Gunzip() if gzipped else None
    count = 0
    while True:
        try:
            chunk = response.read(CHUNK)
        except (OSError, http.client.HTTPException) as err:
            raise CutShort(f"body cut short: {err!r}") from err
        if not chunk:
            break
        count += len(chunk)
        yield gunzip.decode(chunk) if gunzip else chunk
    if gunzip:
        gunzip.finish()
    if length is not None and count != length:
        raise CutShort(f"body cut short: {count} of {length} bytes arrived")


@dataclass
class Attempt:
    """One request of a fetch, and what its response gives the fetch's record."""

    requested_at: datetime
    status: int | None = None
    error: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    content_type: str | None = None
    stored: _cache.Stored | None = None
    # How long to wait before the next attempt, or None if it isn't retried
    # (CLIENT-8).
    retry: float | None = None


def wait(retry_after: str | None, number: int) -> float:
    """The wait before a retry, after attempt `number` (CLIENT-8).

    The response's Retry-After, in seconds or as an HTTP date, or else 2 to
    the power of the attempt number; either capped at 60 seconds.
    """
    seconds = 2.0**number
    if retry_after is not None:
        value = retry_after.strip()
        if SECONDS.fullmatch(value):
            seconds = float(value)
        else:
            try:
                when = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                pass
            else:
                # An HTTP date is in UTC, which `-0000` leaves unsaid.
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
                seconds = max((when - datetime.now(UTC)).total_seconds(), 0.0)
    return min(seconds, LONGEST_WAIT)


def attempt(
    writer: _cache.Writer,
    headers: dict[str, str],
    named: _cache.Stored | None,
    number: int,
) -> Attempt | None:
    """Request the writer's URL once, and store the body of a 200.

    The request starts when the pacer lets it, once its connection is open,
    and is sent then (CLIENT-7). Returns None, having sent nothing, after a
    403 to a fetch in the process (CLIENT-9). A request line or header that
    http.client refuses, which sends nothing, raises its error, and isn't
    an attempt.
    """
    # No connection opens after a 403, either.
    if PACER.forbidden:
        return None
    # The URL is a feed's (READ-4), so it's https on one of CLIENT-1's hosts,
    # and its path is the rest of it, sent as it's given. Parsing it would
    # drop a tab or a line break from the path, which http.client refuses.
    host, _, path = writer.url.removeprefix("https://").partition("/")
    tried = Attempt(datetime.now(UTC))
    connection = connect(host, TIMEOUT)
    try:
        # Putting the request checks it, and sends nothing until the end of
        # its headers.
        connection.putrequest("GET", f"/{path}", skip_host=True, skip_accept_encoding=True)
        for name, value in ({"Host": host} | headers).items():
            connection.putheader(name, value)
        try:
            # The connection opens first, and the request is sent when its
            # turn comes, so that one slow to open sends nothing less than
            # the interval after another request, or after a 403 that
            # another received meanwhile.
            connection.connect()
            if not PACER.start():
                return None
            # A record's requested_at is when its attempt was sent.
            tried.requested_at = datetime.now(UTC)
            connection.endheaders()
            response = connection.getresponse()
        except (OSError, http.client.HTTPException) as err:
            tried.error = f"no response: {err!r}"
            tried.retry = wait(None, number)
            return tried
        tried.status = response.status
        tried.etag = response.getheader("ETag")
        tried.last_modified = response.getheader("Last-Modified")
        tried.content_type = response.getheader("Content-Type")
        if response.status == 200:
            encoding = (response.getheader("Content-Encoding") or "").strip().lower()
            if encoding not in GZIP | PLAIN:
                # CLIENT-12: the body can't be named without decoding it.
                tried.error = f"unsupported Content-Encoding: {encoding}"
                return tried
            try:
                tried.stored = writer.write_object(received(response, gzipped=encoding in GZIP))
            except CutShort as err:
                tried.error = str(err)
                tried.retry = wait(response.getheader("Retry-After"), number)
        elif response.status == 304:
            # CLIENT-16: it names the version whose validators were sent.
            if named is None:
                tried.error = "a 304 to a request that sent no validators"
            tried.stored = named
        elif response.status == 403:
            # CLIENT-9: the SEC returns it to clients over its limit.
            PACER.forbidden = True
        elif response.status in RETRIED:
            tried.retry = wait(response.getheader("Retry-After"), number)
        return tried
    finally:
        connection.close()


def fetch(
    writer: _cache.Writer,
    user_agent: str,
    validators: dict[str, str],
    named: _cache.Stored | None,
) -> dict[str, Any]:
    """Fetch the writer's URL into its cache, and return the fetch's record.

    `validators` are the conditional request's headers, from the record of
    the URL's latest version (CLIENT-5), and `named` is that version, which
    a 304 names (CLIENT-16), or None when there are none. The record
    describes the final attempt and is appended after the object it names
    (CLIENT-14). Raises ForbiddenError, after appending it, if the fetch
    received a 403, or if one in the process did before its next attempt,
    and before requesting anything if one did before its first (CLIENT-9).
    """
    url = writer.url
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip"} | validators
    tried: Attempt | None = None
    attempts = 0
    stopped = False
    while True:
        outcome = attempt(writer, headers, named, attempts + 1)
        if outcome is None:
            stopped = True
            break
        tried = outcome
        attempts += 1
        if tried.retry is None or attempts == ATTEMPTS:
            break
        PACER.sleep(tried.retry)
    if tried is None:
        raise ForbiddenError(url, FORBIDDEN)
    record = writer.append(
        requested_at=tried.requested_at,
        attempts=attempts,
        status=tried.status,
        error=tried.error,
        etag=tried.etag,
        last_modified=tried.last_modified,
        content_type=tried.content_type,
        stored=tried.stored,
    )
    if stopped or tried.status == 403:
        raise ForbiddenError(url, FORBIDDEN)
    return record
