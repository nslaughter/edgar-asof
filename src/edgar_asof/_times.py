"""Acceptance times: raw times as their sources give them, and the interpreters.

times.md governs them. A raw time keeps its text as given, and has no
order (TIME-5), so it becomes an instant only through an interpreter, a
callable that takes a filing's accession number and its raw times
(TIME-6). The library gives two: one for `submissions`' time (TIME-7,
TIME-10), and one for the header's digits in a zone the caller names
(TIME-8, TIME-11). Neither is a default (TIME-9).
"""

from __future__ import annotations

import re
import zoneinfo
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from edgar_asof._read import BodyRef

SOURCES = ("header", "submissions")
# TIME-10: the form that the findings record, `YYYY-MM-DDTHH:MM:SS.sssZ`.
SUBMISSIONS = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})\.([0-9]{3})Z"
)
# TIME-11: the header's 14 digits, `YYYYMMDDHHMMSS`.
HEADER = re.compile(r"([0-9]{4})([0-9]{2})([0-9]{2})([0-9]{2})([0-9]{2})([0-9]{2})")


@dataclass(frozen=True)
class RawTime:
    """An acceptance time as its source gives it (times.md's §3).

    `source` is `"header"` or `"submissions"`; `text`, the header's 14
    digits or `submissions`' `acceptanceDateTime`, as given;
    `accession_number`, its filing's; and `body`, the body it was read
    from. It has no order: it's compared as a time only through an
    interpreter (TIME-5, TIME-12).
    """

    source: str
    text: str
    accession_number: str
    body: BodyRef

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(
                f"a raw time's source is 'header' or 'submissions', not {self.source!r}"
            )


type Interpreter = Callable[[str, tuple[RawTime, ...]], datetime | None]


def given(accession_number: str, raw_times: Iterable[RawTime]) -> dict[str, RawTime]:
    """A filing's raw times by source, as the library gives them (TIME-13).

    Raises ValueError for more than one from a source, or one of another
    filing (TIME-15).
    """
    by_source: dict[str, RawTime] = {}
    for raw_time in raw_times:
        if raw_time.accession_number != accession_number:
            raise ValueError(
                f"a raw time of {raw_time.accession_number!r} given with {accession_number!r}"
            )
        if raw_time.source in by_source:
            raise ValueError(
                f"more than one raw time from {raw_time.source} for {accession_number!r}"
            )
        by_source[raw_time.source] = raw_time
    return by_source


def submissions_utc(accession_number: str, raw_times: tuple[RawTime, ...]) -> datetime | None:
    """An interpreter: `submissions`' `acceptanceDateTime`, as the UTC instant it states.

    It reads only the form that the findings record, and gives nothing for
    a filing without one, or one in another form (TIME-7, TIME-10).
    """
    raw_time = given(accession_number, raw_times).get("submissions")
    if raw_time is None or not isinstance(raw_time.text, str):
        return None
    match = SUBMISSIONS.fullmatch(raw_time.text)
    if match is None:
        return None
    year, month, day, hour, minute, second, millisecond = map(int, match.groups())
    try:
        return datetime(year, month, day, hour, minute, second, millisecond * 1000, tzinfo=UTC)
    except ValueError:
        # A date that doesn't exist, or a time out of range, such as 24:00.
        return None


@dataclass(frozen=True)
class HeaderInZone:
    """An interpreter: the header's digits, as local time in a zone (TIME-8, TIME-11).

    It's equal to another, with the same hash, only for the same `zone`, as
    given (TIME-12). It resolves `zone` whenever one is made, by
    `header_in_zone` or by `dataclasses.replace`, so two that are equal
    read the same instants.
    """

    zone: str
    tzinfo: zoneinfo.ZoneInfo = field(init=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.zone, str):
            raise TypeError(f"a zone is a time zone's IANA name, a str, not {self.zone!r}")
        try:
            tzinfo = zoneinfo.ZoneInfo(self.zone)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as err:
            raise ValueError(f"no time zone found named {self.zone!r}") from err
        # A frozen dataclass sets its own fields only through object's.
        object.__setattr__(self, "tzinfo", tzinfo)

    def __call__(self, accession_number: str, raw_times: tuple[RawTime, ...]) -> datetime | None:
        raw_time = given(accession_number, raw_times).get("header")
        if raw_time is None or not isinstance(raw_time.text, str):
            return None
        match = HEADER.fullmatch(raw_time.text)
        if match is None:
            return None
        year, month, day, hour, minute, second = map(int, match.groups())
        try:
            # A local time that occurs twice is read as the earlier instant,
            # whose fold is 0.
            local = datetime(year, month, day, hour, minute, second, tzinfo=self.tzinfo)
            instant = local.astimezone(UTC)
            # A time the zone skips comes back as another local time.
            back = instant.astimezone(self.tzinfo)
        except ValueError:
            # A date that doesn't exist, or is before year 1, or a time out
            # of range.
            return None
        except OverflowError:
            # An instant outside the years 1 to 9999 in UTC.
            return None
        if back.replace(tzinfo=None) != local.replace(tzinfo=None):
            return None
        return instant

    def __repr__(self) -> str:
        return f"header_in_zone({self.zone!r})"


def header_in_zone(zone: str) -> HeaderInZone:
    """An interpreter of the header's digits, as local time in `zone`, an IANA name (TIME-8).

    A local time that occurs twice is read as the earlier instant. Raises
    ValueError for a zone that zoneinfo can't find (TIME-15), and
    TypeError for one that isn't a str.
    """
    return HeaderInZone(zone)
