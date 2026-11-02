"""Raw acceptance times, and the library's two interpreters.

times.md governs them. Each test makes its raw times up, as a caller can,
with the forms the findings record: the header's 14 digits and
`submissions`' RFC 3339 time, such as Apple's 10-K 0000320193-25-000079's
`20251031060126` and `2025-10-31T14:01:26.000Z`. Reading them from bodies
is T8's (TIME-1 to TIME-4).
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import shutil
import zoneinfo
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import edgar_asof
from edgar_asof import BodyRef, Interpreter, RawTime, header_in_zone, submissions_utc

ACCESSION = "0000320193-25-000079"
OTHER = "0001140361-26-035325"
HEADER_BODY = BodyRef(
    "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/"
    "0000320193-25-000079-index-headers.html",
    hashlib.sha256(b"a header").hexdigest(),
)
SUBMISSIONS_BODY = BodyRef(
    "https://data.sec.gov/submissions/CIK0000320193.json",
    hashlib.sha256(b"a submissions").hexdigest(),
)
NEW_YORK = "America/New_York"


def header(text: object, accession_number: str = ACCESSION) -> RawTime:
    # A caller's RawTime can hold any text (TIME-11).
    return RawTime("header", text, accession_number, HEADER_BODY)  # type: ignore[arg-type]


def submissions(text: object, accession_number: str = ACCESSION) -> RawTime:
    return RawTime("submissions", text, accession_number, SUBMISSIONS_BODY)  # type: ignore[arg-type]


@pytest.fixture
def alias(tmp_path: Path) -> Iterator[str]:
    """US/Eastern, a name that the time zone database links to America/New_York.

    Some systems' databases leave out such legacy names, as Ubuntu 26.04's
    does, so the test's own database holds both, each with the system's
    America/New_York.
    """
    found = next(
        Path(directory) / NEW_YORK
        for directory in zoneinfo.TZPATH
        if (Path(directory) / NEW_YORK).is_file()
    )
    for name in (NEW_YORK, "US/Eastern"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(found, tmp_path / name)
    zoneinfo.reset_tzpath(to=[str(tmp_path)])
    zoneinfo.ZoneInfo.clear_cache()
    try:
        yield "US/Eastern"
    finally:
        zoneinfo.reset_tzpath()
        zoneinfo.ZoneInfo.clear_cache()


def at(
    year: int,
    month: int = 1,
    day: int = 1,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    microsecond: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, second, microsecond, tzinfo=UTC)


@pytest.mark.spec("TIME-5", "TIME-12")
def test_a_raw_time_has_no_order() -> None:
    earlier = submissions("2025-10-31T14:01:26.000Z")
    later = submissions("2026-07-31T14:01:02.000Z", OTHER)

    for compare in (
        lambda: earlier < later,  # type: ignore[operator]
        lambda: earlier <= later,  # type: ignore[operator]
        lambda: earlier > later,  # type: ignore[operator]
        lambda: earlier >= later,  # type: ignore[operator]
        lambda: sorted([later, earlier]),  # type: ignore[type-var]
        lambda: max(earlier, later),  # type: ignore[call-overload]
    ):
        with pytest.raises(TypeError):
            compare()
    assert earlier != earlier.text  # type: ignore[comparison-overlap]
    assert later != at(2026, 7, 31, 14, 1, 2)


@pytest.mark.spec("TIME-6")
def test_an_interpreter_takes_a_filings_accession_number_and_raw_times() -> None:
    interpreters: list[Interpreter] = [submissions_utc, header_in_zone(NEW_YORK)]
    raw_times = (header("20251031060126"), submissions("2025-10-31T14:01:26.000Z"))

    for interpreter in interpreters:
        assert inspect.signature(interpreter).parameters.keys() == {
            "accession_number",
            "raw_times",
        }
        assert isinstance(interpreter(ACCESSION, raw_times), datetime)
        # Nothing, for a filing with no raw time it can read.
        assert interpreter(ACCESSION, ()) is None


@pytest.mark.spec("TIME-6")
def test_a_callers_own_function_is_an_interpreter() -> None:
    def mine(accession_number: str, raw_times: tuple[RawTime, ...]) -> datetime | None:
        return at(2025, 10, 31) if raw_times else None

    # mypy checks that it's an Interpreter.
    interpreter: Interpreter = mine

    assert interpreter(ACCESSION, (submissions("soon"),)) == at(2025, 10, 31)
    assert interpreter(ACCESSION, ()) is None


@pytest.mark.spec("TIME-7")
@pytest.mark.parametrize(
    ("text", "instant"),
    [
        pytest.param("2025-10-31T14:01:26.000Z", at(2025, 10, 31, 14, 1, 26), id="apple-10-k"),
        pytest.param("2026-09-02T00:30:35.000Z", at(2026, 9, 2, 0, 30, 35), id="apple-8-k-a"),
        pytest.param(
            "2026-01-31T02:10:02.123Z", at(2026, 1, 31, 2, 10, 2, 123000), id="milliseconds"
        ),
        pytest.param("2026-07-31T23:59:59.999Z", at(2026, 7, 31, 23, 59, 59, 999000), id="last"),
    ],
)
def test_submissions_utc_reads_the_instant_stated_in_utc_to_the_millisecond(
    text: str, instant: datetime
) -> None:
    alone = submissions_utc(ACCESSION, (submissions(text),))
    beside_a_header = submissions_utc(ACCESSION, (header("20000101000000"), submissions(text)))
    header_after = submissions_utc(ACCESSION, (submissions(text), header("20000101000000")))

    assert alone == beside_a_header == header_after == instant
    assert alone is not None
    assert alone.tzinfo is UTC


@pytest.mark.spec("TIME-7")
def test_submissions_utc_gives_nothing_for_a_filing_without_a_submissions_time() -> None:
    assert submissions_utc(ACCESSION, ()) is None
    assert submissions_utc(ACCESSION, (header("20251031060126"),)) is None


@pytest.mark.spec("TIME-10")
@pytest.mark.parametrize(
    ("text", "instant"),
    [
        pytest.param("0001-01-01T00:00:00.000Z", at(1, 1, 1), id="year-1"),
        pytest.param("9999-12-31T23:59:59.999Z", at(9999, 12, 31, 23, 59, 59, 999000), id="9999"),
        pytest.param("2024-02-29T12:00:00.000Z", at(2024, 2, 29, 12), id="leap-day"),
        pytest.param("2026-03-08T07:30:00.000Z", at(2026, 3, 8, 7, 30), id="no-zone-applies"),
    ],
)
def test_submissions_utc_reads_the_recorded_form_at_its_limits(
    text: str, instant: datetime
) -> None:
    assert submissions_utc(ACCESSION, (submissions(text),)) == instant


@pytest.mark.spec("TIME-10")
@pytest.mark.parametrize(
    "text",
    [
        pytest.param("2025-10-31T14:01:26Z", id="no-milliseconds"),
        pytest.param("2025-10-31T14:01:26.00Z", id="two-digits"),
        pytest.param("2025-10-31T14:01:26.0000Z", id="four-digits"),
        pytest.param("2025-10-31T14:01:26.000+00:00", id="offset"),
        pytest.param("2025-10-31T14:01:26.000", id="no-zone"),
        pytest.param("2025-10-31T14:01:26.000z", id="lowercase-z"),
        pytest.param("2025-10-31t14:01:26.000Z", id="lowercase-t"),
        pytest.param("2025-10-31 14:01:26.000Z", id="space"),
        pytest.param("20251031T140126.000Z", id="basic-format"),
        pytest.param(" 2025-10-31T14:01:26.000Z", id="leading-space"),
        pytest.param("2025-10-31T14:01:26.000Z\n", id="trailing-newline"),
        pytest.param("\u0662\u0660\u0662\u0665-10-31T14:01:26.000Z", id="arabic-indic-digits"),
        pytest.param("\uff12\uff10\uff12\uff15-10-31T14:01:26.000Z", id="fullwidth-digits"),
        pytest.param("2025-02-29T14:01:26.000Z", id="no-such-date"),
        pytest.param("2025-13-01T14:01:26.000Z", id="month-13"),
        pytest.param("2025-10-00T14:01:26.000Z", id="day-0"),
        pytest.param("0000-12-31T14:01:26.000Z", id="year-0"),
        pytest.param("2025-10-31T24:00:00.000Z", id="hour-24"),
        pytest.param("2025-10-31T23:60:00.000Z", id="minute-60"),
        pytest.param("2025-10-31T23:59:60.000Z", id="leap-second"),
        pytest.param("", id="empty"),
        pytest.param(b"2025-10-31T14:01:26.000Z", id="bytes"),
        pytest.param(None, id="none"),
    ],
)
def test_submissions_utc_gives_nothing_for_another_form(text: object) -> None:
    assert submissions_utc(ACCESSION, (submissions(text),)) is None


@pytest.mark.spec("TIME-8")
@pytest.mark.parametrize(
    ("zone", "text", "instant"),
    [
        # Eastern daylight time, 4 hours behind UTC.
        pytest.param(NEW_YORK, "20251031060126", at(2025, 10, 31, 10, 1, 26), id="edt"),
        # Eastern standard time, 5 hours behind.
        pytest.param(NEW_YORK, "20260130161002", at(2026, 1, 30, 21, 10, 2), id="est"),
        pytest.param("Asia/Tokyo", "20260101090000", at(2026, 1, 1), id="ahead-of-utc"),
        pytest.param("Asia/Kolkata", "20260101053000", at(2026, 1, 1), id="half-hour"),
        pytest.param("UTC", "20260901163035", at(2026, 9, 1, 16, 30, 35), id="utc"),
    ],
)
def test_header_in_zone_reads_the_digits_as_local_time_in_its_zone(
    zone: str, text: str, instant: datetime
) -> None:
    interpreter = header_in_zone(zone)

    alone = interpreter(ACCESSION, (header(text),))
    beside_submissions = interpreter(
        ACCESSION, (header(text), submissions("2000-01-01T00:00:00.000Z"))
    )
    submissions_first = interpreter(
        ACCESSION, (submissions("2000-01-01T00:00:00.000Z"), header(text))
    )

    assert alone == beside_submissions == submissions_first == instant
    assert alone is not None
    assert alone.tzinfo is UTC


@pytest.mark.spec("TIME-8")
def test_header_in_zone_reads_a_local_time_that_occurs_twice_as_the_earlier_instant() -> None:
    # 1:30 a.m. on November 1, 2026 occurs in daylight time, then in
    # standard time, when New York's clocks go back from 2:00 to 1:00.
    instant = header_in_zone(NEW_YORK)(ACCESSION, (header("20261101013000"),))

    assert instant == at(2026, 11, 1, 5, 30)
    assert header_in_zone(NEW_YORK)(ACCESSION, (header("20261101005959"),)) == at(
        2026, 11, 1, 4, 59, 59
    )
    assert header_in_zone(NEW_YORK)(ACCESSION, (header("20261101020000"),)) == at(2026, 11, 1, 7)


@pytest.mark.spec("TIME-8")
def test_header_in_zone_gives_nothing_for_a_filing_without_a_header_time() -> None:
    interpreter = header_in_zone(NEW_YORK)

    assert interpreter(ACCESSION, ()) is None
    assert interpreter(ACCESSION, (submissions("2025-10-31T14:01:26.000Z"),)) is None


@pytest.mark.spec("TIME-8")
def test_header_in_zone_has_no_default_zone() -> None:
    (zone,) = inspect.signature(header_in_zone).parameters.values()

    assert zone.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        header_in_zone()  # type: ignore[call-arg]


@pytest.mark.spec("TIME-11")
@pytest.mark.parametrize(
    "text",
    [
        pytest.param("2025103106012", id="13-digits"),
        pytest.param("202510310601260", id="15-digits"),
        pytest.param("2025-10-31 06:01:26", id="separators"),
        pytest.param("20251031060126\n", id="trailing-newline"),
        pytest.param(" 20251031060126", id="leading-space"),
        pytest.param("\u0662\u0660\u0662\u06651031060126", id="arabic-indic-digits"),
        pytest.param("\uff12\uff10\uff12\uff151031060126", id="fullwidth-digits"),
        pytest.param("", id="empty"),
        pytest.param(b"20251031060126", id="bytes"),
        pytest.param(20251031060126, id="int"),
    ],
)
def test_header_in_zone_gives_nothing_for_a_header_time_that_isnt_14_digits(text: object) -> None:
    assert header_in_zone(NEW_YORK)(ACCESSION, (header(text),)) is None


@pytest.mark.spec("TIME-11")
@pytest.mark.parametrize(
    "text",
    [
        pytest.param("20250229060126", id="no-such-date"),
        pytest.param("20251301060126", id="month-13"),
        pytest.param("20250001060126", id="month-0"),
        pytest.param("20251000060126", id="day-0"),
        pytest.param("20251032060126", id="day-32"),
        pytest.param("00001231060126", id="year-0"),
        pytest.param("20251031240000", id="hour-24"),
        pytest.param("20251031236000", id="minute-60"),
        pytest.param("20251031235960", id="second-60"),
        # 2:30 a.m. on March 8, 2026 doesn't occur in New York: clocks go
        # forward from 2:00 to 3:00.
        pytest.param("20260308023000", id="skipped"),
        pytest.param("20260308020000", id="skipped-start"),
        pytest.param("20260308025959", id="skipped-end"),
    ],
)
def test_header_in_zone_gives_nothing_for_digits_that_name_no_local_time(text: str) -> None:
    assert header_in_zone(NEW_YORK)(ACCESSION, (header(text),)) is None


@pytest.mark.spec("TIME-11")
def test_header_in_zone_reads_the_local_times_around_a_skipped_hour() -> None:
    interpreter = header_in_zone(NEW_YORK)

    assert interpreter(ACCESSION, (header("20260308015959"),)) == at(2026, 3, 8, 6, 59, 59)
    assert interpreter(ACCESSION, (header("20260308030000"),)) == at(2026, 3, 8, 7)


@pytest.mark.spec("TIME-11")
@pytest.mark.parametrize(
    ("zone", "text"),
    [
        # 11 p.m. on December 31, 9999 in New York is in the year 10000 in UTC.
        pytest.param(NEW_YORK, "99991231230000", id="after-9999"),
        # Midnight on January 1 of year 1, 9 hours ahead of UTC, is in year 0
        # in UTC. (Etc/GMT-9 is 9 hours ahead, in the database's POSIX sign.)
        pytest.param("Etc/GMT-9", "00010101000000", id="before-year-1"),
    ],
)
def test_header_in_zone_gives_nothing_for_a_local_time_outside_the_years_in_utc(
    zone: str, text: str
) -> None:
    assert header_in_zone(zone)(ACCESSION, (header(text),)) is None


@pytest.mark.spec("TIME-11")
@pytest.mark.parametrize(
    ("zone", "text", "instant"),
    [
        pytest.param("UTC", "00010101000000", at(1, 1, 1), id="year-1"),
        pytest.param("UTC", "99991231235959", at(9999, 12, 31, 23, 59, 59), id="9999"),
        pytest.param(NEW_YORK, "99991231185959", at(9999, 12, 31, 23, 59, 59), id="new-york"),
        pytest.param("Etc/GMT-9", "00010101090000", at(1, 1, 1), id="ahead-of-utc"),
    ],
)
def test_header_in_zone_reads_a_local_time_at_the_years_limits(
    zone: str, text: str, instant: datetime
) -> None:
    assert header_in_zone(zone)(ACCESSION, (header(text),)) == instant


@pytest.mark.spec("TIME-12")
def test_the_package_gives_the_functions_and_types_of_acceptance_times() -> None:
    def parameters(function: Callable[..., object]) -> list[tuple[str, str]]:
        return [
            (name, parameter.kind.name)
            for name, parameter in inspect.signature(function).parameters.items()
        ]

    assert [field.name for field in dataclasses.fields(RawTime)] == [
        "source",
        "text",
        "accession_number",
        "body",
    ]
    assert Interpreter.__value__ == Callable[[str, tuple[RawTime, ...]], datetime | None]
    assert inspect.isfunction(submissions_utc)
    assert parameters(submissions_utc) == [
        ("accession_number", "POSITIONAL_OR_KEYWORD"),
        ("raw_times", "POSITIONAL_OR_KEYWORD"),
    ]
    assert inspect.isfunction(header_in_zone)
    assert parameters(header_in_zone) == [("zone", "POSITIONAL_OR_KEYWORD")]
    assert callable(header_in_zone(NEW_YORK))
    assert set(edgar_asof.__all__) >= {
        "RawTime",
        "Interpreter",
        "submissions_utc",
        "header_in_zone",
    }


@pytest.mark.spec("TIME-12")
def test_each_instant_an_interpreter_gives_is_a_datetime_in_utc() -> None:
    raw_times = (header("20251031060126"), submissions("2025-10-31T14:01:26.000Z"))

    for interpreter in (submissions_utc, header_in_zone(NEW_YORK), header_in_zone("Asia/Tokyo")):
        instant = interpreter(ACCESSION, raw_times)
        assert type(instant) is datetime
        assert instant.tzinfo is UTC
        assert instant.utcoffset() == timedelta(0)


@pytest.mark.spec("TIME-12")
def test_a_raw_time_is_immutable_hashable_and_equal_only_with_the_same_fields() -> None:
    raw_time = submissions("2025-10-31T14:01:26.000Z")
    same = submissions("2025-10-31T14:01:26.000Z")
    others = [
        RawTime("header", raw_time.text, ACCESSION, SUBMISSIONS_BODY),
        submissions("2025-10-31T14:01:26.001Z"),
        submissions("2025-10-31T14:01:26.000Z", OTHER),
        RawTime("submissions", raw_time.text, ACCESSION, BodyRef(SUBMISSIONS_BODY.url, "0" * 64)),
    ]

    assert raw_time == same
    assert hash(raw_time) == hash(same)
    assert len({raw_time, same, *others}) == 5
    for other in others:
        assert raw_time != other
    for field in dataclasses.fields(raw_time):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(raw_time, field.name, "other")


@pytest.mark.spec("TIME-12")
def test_header_in_zone_gives_equal_interpreters_only_for_the_same_zone_as_given() -> None:
    interpreter = header_in_zone(NEW_YORK)

    assert interpreter == header_in_zone(NEW_YORK)
    assert hash(interpreter) == hash(header_in_zone(NEW_YORK))
    assert header_in_zone("Asia/Tokyo") != interpreter
    assert interpreter != NEW_YORK  # type: ignore[comparison-overlap]
    assert interpreter != submissions_utc
    assert len({interpreter, header_in_zone(NEW_YORK), header_in_zone("Asia/Tokyo")}) == 2


@pytest.mark.spec("TIME-12")
def test_header_in_zone_doesnt_resolve_a_zone_the_database_links_to_another(alias: str) -> None:
    interpreter = header_in_zone(alias)
    raw_times = (header("20251031060126"),)

    # The same zone, by another name.
    assert interpreter(ACCESSION, raw_times) == header_in_zone(NEW_YORK)(ACCESSION, raw_times)
    assert interpreter != header_in_zone(NEW_YORK)
    assert interpreter == header_in_zone(alias)
    assert len({interpreter, header_in_zone(NEW_YORK), header_in_zone(alias)}) == 2
    assert repr(interpreter) == "header_in_zone('US/Eastern')"


@pytest.mark.spec("TIME-12")
def test_an_interpreter_header_in_zone_gives_is_immutable() -> None:
    interpreter = header_in_zone(NEW_YORK)

    for field in dataclasses.fields(interpreter):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(interpreter, field.name, "Asia/Tokyo")
    assert interpreter(ACCESSION, (header("20251031060126"),)) == at(2025, 10, 31, 10, 1, 26)


@pytest.mark.spec("TIME-12")
def test_each_of_the_librarys_interpreters_has_a_repr_that_names_it() -> None:
    assert repr(header_in_zone(NEW_YORK)) == "header_in_zone('America/New_York')"
    assert repr(header_in_zone("Asia/Tokyo")) == "header_in_zone('Asia/Tokyo')"
    assert "submissions_utc" in repr(submissions_utc)


@pytest.mark.spec("TIME-15")
@pytest.mark.parametrize("source", ["", "Header", "SUBMISSIONS", "filings", None])
def test_a_raw_time_from_another_source_raises_value_error(source: object) -> None:
    with pytest.raises(ValueError, match="source"):
        RawTime(source, "20251031060126", ACCESSION, HEADER_BODY)  # type: ignore[arg-type]


@pytest.mark.spec("TIME-15")
@pytest.mark.parametrize(
    "zone",
    [
        pytest.param("Nowhere/Zone", id="unknown"),
        pytest.param("America/New_York ", id="trailing-space"),
        pytest.param("", id="empty"),
        pytest.param("../zoneinfo", id="relative"),
        pytest.param("/etc/localtime", id="absolute"),
    ],
)
def test_a_zone_zoneinfo_cant_find_raises_value_error(zone: str) -> None:
    with pytest.raises(ValueError, match="time zone"):
        header_in_zone(zone)


@pytest.mark.spec("TIME-15")
@pytest.mark.parametrize("zone", [5, None, b"UTC"])
def test_a_zone_that_isnt_a_str_raises_type_error(zone: object) -> None:
    with pytest.raises(TypeError, match="IANA name"):
        header_in_zone(zone)  # type: ignore[arg-type]


INTERPRETERS = [
    pytest.param(submissions_utc, id="submissions-utc"),
    pytest.param(header_in_zone(NEW_YORK), id="header-in-zone"),
]


@pytest.mark.spec("TIME-15")
@pytest.mark.parametrize("interpreter", INTERPRETERS)
@pytest.mark.parametrize(
    "raw_times",
    [
        pytest.param(
            (header("20251031060126"), header("20251031060126")), id="two-headers-the-same"
        ),
        pytest.param((header("20251031060126"), header("20251031060127")), id="two-headers"),
        pytest.param(
            (submissions("2025-10-31T14:01:26.000Z"), submissions("2025-10-31T14:01:27.000Z")),
            id="two-from-submissions",
        ),
        pytest.param(
            (
                header("20251031060126"),
                submissions("2025-10-31T14:01:26.000Z"),
                header("20251031060126"),
            ),
            id="three",
        ),
    ],
)
def test_an_interpreter_given_more_than_one_raw_time_from_a_source_raises_value_error(
    interpreter: Interpreter, raw_times: tuple[RawTime, ...]
) -> None:
    with pytest.raises(ValueError, match="more than one"):
        interpreter(ACCESSION, raw_times)


@pytest.mark.spec("TIME-15")
@pytest.mark.parametrize("interpreter", INTERPRETERS)
@pytest.mark.parametrize(
    "raw_times",
    [
        pytest.param((header("20251031060126", OTHER),), id="header"),
        pytest.param((submissions("2025-10-31T14:01:26.000Z", OTHER),), id="submissions"),
        pytest.param(
            (header("20251031060126"), submissions("2025-10-31T14:01:26.000Z", OTHER)),
            id="one-of-two",
        ),
    ],
)
def test_an_interpreter_given_another_filings_raw_time_raises_value_error(
    interpreter: Interpreter, raw_times: tuple[RawTime, ...]
) -> None:
    with pytest.raises(ValueError, match=OTHER):
        interpreter(ACCESSION, raw_times)
