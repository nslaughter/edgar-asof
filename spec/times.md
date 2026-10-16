# Specification: acceptance times

**Status:** Version 1.0.0, draft, October 15, 2026. This document governs
how `edgar-asof` reads a filing's acceptance time and turns it into an
instant, and the functions and types a caller uses for them. Where code and
this document disagree, the code is wrong or this document needs a new
version; say which before changing either.

A value becomes known when the SEC accepts the filing that reports it, so a
filing's acceptance time is the transaction time of "as of T", as
`edgar-data-pipeline`'s design says ([Times]). EDGAR gives it in two
places. A filing's header gives 14 digits with no time zone ([SRC-1]).
`submissions` gives a UTC time, which is 4 or 5 hours later than the
header's digits for Microsoft's and Walmart's filings, as converting US
Eastern time to UTC would make it, and 8 hours later for Apple's
([SRC-2]). Following `edgar-data-pipeline`'s decision [0009], the library
keeps both as given and turns them into instants in a separate step that a
caller can replace. Which values an "as of T" query returns is for the
facts specification, which follows that repository's findings on restated
values (its task T2).

Version 1.0.0 gives the functions and types a caller uses for acceptance
times ([§5](#5-functions-and-types)): a raw time, which keeps the body it
was read from, whether from a cache or from the caller; an instant, as a
`datetime`; an interpreter's signature, which takes the filing's
accession number as well as its raw times; and the two interpreters the
library gives. [§8](#8-changes-to-this-document) lists what changed from
version 0.1.0.

## 1. Terms

- **Raw time:** an acceptance time as its source gives it: the header's
  digits, or `submissions`' string.
- **Instant:** a point in time, in UTC.
- **Interpreter:** a function that turns a filing's raw times into one
  instant ([§4](#4-interpreters)).

## 2. Statement IDs

As in [`fetching.md`](fetching.md#3-statement-ids). The area here is
`TIME`, which `edgar-data-pipeline` doesn't use.

## 3. Raw times

- **TIME-1** (rule) From a filing's header, the library reads
  `ACCEPTANCE-DATETIME` as its 14 digits, `YYYYMMDDHHMMSS`, unchanged
  ([SRC-1]).
- **TIME-2** (rule) From `submissions`' `filings.recent` and its further
  files, the library reads each filing's `acceptanceDateTime` as the string
  given, unchanged, such as `2025-10-31T14:01:26.000Z` ([SRC-2],
  [SRC-12]).
- **TIME-3** (rule) Each raw time keeps its source, `header` or
  `submissions`; the accession number of its filing; and the URL and
  `sha256` of the body it was read from, as fetching.md's read returns
  them ([READ-3]): from a cache, those of the version read ([CACHE-7]),
  and from bodies the caller gives, the body's URL and the SHA-256 of its
  bytes.
- **TIME-4** (rule) When the library has both raw times for a filing, it
  keeps both, and neither replaces the other.
- **TIME-5** (rule) The library compares, orders, or converts raw times only
  through an interpreter.

## 4. Interpreters

- **TIME-6** (rule) An interpreter takes a filing's accession number and
  its raw times, each with its source, and returns an instant, or nothing
  if it can't make one from them. Wherever the library turns acceptance
  times into instants, the caller can pass an interpreter of their own.
- **TIME-7** (rule) The library provides an interpreter that reads
  `submissions`' `acceptanceDateTime` as the instant it states, in UTC to
  the millisecond ([SRC-2]), and returns nothing for a filing without one.
- **TIME-10** (rule) TIME-7's interpreter reads an `acceptanceDateTime`
  only in the form that [SRC-2] and [SRC-12] record,
  `YYYY-MM-DDTHH:MM:SS.sssZ`, in ASCII digits, with a date that exists,
  from year 1 on, and a time from `00:00:00.000` to `23:59:59.999`. For a
  filing whose `acceptanceDateTime` has another form, it returns nothing.
- **TIME-8** (rule) The library provides an interpreter that reads the
  header's digits as local time in a time zone the caller names by its IANA
  name, such as `America/New_York`, and returns nothing for a filing
  without a header time. It has no default zone. A local time that occurs
  twice, when daylight saving time ends, is read as the earlier instant.
- **TIME-11** (rule) TIME-8's interpreter returns nothing for a filing
  whose header's raw time isn't 14 ASCII digits, `YYYYMMDDHHMMSS`, which
  only a caller's `RawTime` can be ([TIME-1]), or whose digits name no
  local time in its zone: a date that doesn't exist or is before year 1,
  a time outside `00:00:00` to `23:59:59`, or a time that the zone skips,
  as when daylight saving time starts. It returns nothing, too, for a
  local time whose instant falls outside the years 1 to 9999 in UTC,
  which no instant can be ([TIME-14]), as `99991231230000` does in
  `America/New_York`.
- **TIME-9** (rule) The library has no default interpreter. Wherever it
  turns acceptance times into instants, the caller passes an interpreter,
  and without one the library raises an error.

No interpreter is right for every filing yet. Read as UTC, `submissions`'
time falls outside EDGAR's hours for most of Apple's filings, and for most
of Walmart's before June 2023, but not for Microsoft's ([SRC-13]). Eight
hours earlier, read as Eastern Time, nearly all of them fall within those
hours, as the header's digits for Apple's three stored filings do
([SRC-2]). The header's digits read as Eastern Time ([TIME-8]) may become
the default, in a minor version, once a finding compares more headers with
`submissions`.

## 5. Functions and types

The package `edgar_asof` gives a caller the functions and types below for
acceptance times. [`facts.md`](facts.md#8-functions-and-types) uses a raw
time, an instant, and an interpreter by these names, in `Filing.raw_times`,
`Placed.accepted`, `Answer.at`, and `as_of`'s interpreter. A raw time names
the body it was read from by fetching.md's `BodyRef` ([READ-1]).

| Name | Kind | Parameters or fields |
| --- | --- | --- |
| `RawTime` | Type | A raw time ([§3](#3-raw-times)). `source`, a `str`, `"header"` or `"submissions"`; `text`, a `str`, the header's 14 digits or `submissions`' `acceptanceDateTime`, as given ([TIME-1], [TIME-2]); `accession_number`, a `str`, its filing's, as facts.md's `Filing` has it; and `body`, a `BodyRef`, the URL and `sha256` of the body it was read from ([TIME-3]). |
| `Interpreter` | Type alias | A callable that takes two positional arguments, a filing's `accession_number`, a `str`, and its `raw_times`, a tuple of `RawTime`, and returns an instant or `None`: `Callable[[str, tuple[RawTime, ...]], datetime \| None]` ([TIME-6], [TIME-13]). |
| `submissions_utc(accession_number, raw_times)` | Function | An interpreter that reads `submissions`' `acceptanceDateTime` as the UTC instant it states ([TIME-7], [TIME-10]). |
| `header_in_zone(zone)` | Function | Returns an interpreter that reads the header's digits as local time in `zone`, a `str`, a time zone's IANA name, such as `"America/New_York"` ([TIME-8], [TIME-11]). |

- **TIME-12** (rule) The package `edgar_asof` gives the functions and
  types in the table, with their parameters and fields. An instant is a
  `datetime.datetime` whose `tzinfo` is `datetime.timezone.utc`, and each
  instant that the library's interpreters return is one. A `RawTime` is
  immutable and hashable, equal to another only with the same fields, and
  has no order, so it's compared as a time only through an interpreter
  ([TIME-5]). An interpreter that `header_in_zone` returns is immutable,
  and equal to another, with the same hash, only when both were returned
  for the same `zone` string, as given. Zones aren't resolved, so
  `header_in_zone('US/Eastern')` isn't equal to
  `header_in_zone('America/New_York')`, though the time zone database
  makes the first name an alias of the second. Each of the library's
  interpreters has a `repr` that names it, and for one that
  `header_in_zone` returns, its `zone` as given, as
  `header_in_zone('America/New_York')`.
- **TIME-13** (rule) The library calls an interpreter with two
  positional arguments, a filing's accession number and then a tuple of
  its raw times, so an interpreter's parameters can have any names. It
  gives each filing as [`facts.md`'s ASOF-2][ASOF-2] says, with at most
  one raw time from each source, the header's before `submissions`'.
  Wherever the library gives a filing's raw times, as in
  `Filing.raw_times`, they're in that order.
- **TIME-14** (rule) Where the library takes an instant, from the caller
  as an answer's T ([ASOF-1]) or from an interpreter, it takes a
  `datetime.datetime` with a time zone, one whose `utcoffset()` isn't
  `None`, whatever the zone, as the same instant in UTC, and each instant
  it gives, such as `Placed.accepted` and `Answer.at`, is in UTC
  ([TIME-12]). So an instant falls within the years 1 to 9999 in UTC,
  which a `datetime` in UTC can hold: `datetime.max` with a zone behind
  UTC isn't one. Given as T, a value that isn't a `datetime.datetime`
  raises `TypeError`, and a `datetime` without a time zone, or outside
  those years in UTC, raises `ValueError`, each before anything is
  interpreted. An interpreter that returns anything but `None` or a
  `datetime` with a time zone raises `TypeError`, and one that returns a
  `datetime` outside those years in UTC raises `ValueError`; each names
  the filing's accession number.
- **TIME-15** (rule) An argument this document refuses raises
  `ValueError`: a `RawTime` whose `source` is neither `"header"` nor
  `"submissions"`; a `zone` that Python's `zoneinfo` can't find, given to
  `header_in_zone`; and, given to one of the library's interpreters, raw
  times that hold more than one from a source, or one whose
  `accession_number` isn't the accession number given with them, neither
  of which the library gives it ([TIME-13]).

## 6. Index

| ID | Kind | Checked by | Statement |
| --- | --- | --- | --- |
| TIME-1 | rule | tests | The header's acceptance time is kept as its 14 digits. |
| TIME-2 | rule | tests | `submissions`' `acceptanceDateTime` is kept as given. |
| TIME-3 | rule | tests | A raw time keeps its source, its filing, and the body it came from, cached or given. |
| TIME-4 | rule | tests | A filing's two raw times are both kept. |
| TIME-5 | rule | tests | Raw times are compared, ordered, or converted only by an interpreter. |
| TIME-6 | rule | tests | An interpreter takes a filing's accession number and raw times, gives an instant or nothing, and the caller can pass one. |
| TIME-7 | rule | tests | An interpreter reads `submissions`' time as the UTC instant it states. |
| TIME-10 | rule | tests | `submissions`' time is read only in the form the findings record. |
| TIME-8 | rule | tests | An interpreter reads the header's digits in a zone the caller names. |
| TIME-11 | rule | tests | A header time that isn't 14 digits, or names no local time in the zone or no instant, gives nothing. |
| TIME-9 | rule | tests | There is no default interpreter; the caller passes one. |
| TIME-12 | rule | tests | The package gives §5's functions and types; an instant is a UTC `datetime`. |
| TIME-13 | rule | tests | An interpreter is given, positionally, a filing's accession number and its raw times, the header's first. |
| TIME-14 | rule | tests | An instant taken in any zone is read in UTC, within years 1 to 9999; any other T or result raises. |
| TIME-15 | rule | tests | Refused arguments raise `ValueError`. |

## 7. Open questions

None.

## 8. Changes to this document

Versions follow semantic versioning. Adding a statement or an interpreter
is a minor version. Changing the meaning of a statement, or which instant
an interpreter returns, is a major version. IDs are never reused, and a
retired statement stays in the index.

### Version 1.0.0

Version 1.0.0 is a major version because it changes what an interpreter
takes, and which instant TIME-7's interpreter returns for some text, and
either change alone would make it one. It also extends TIME-3 to bodies
the caller gives, settles what TIME-8 left open, and adds
[§5](#5-functions-and-types)'s functions and types ([TIME-12] to
[TIME-15]), none of which would need a major version alone:

- **An interpreter also takes its filing's accession number** ([TIME-6]),
  so that it can place a filing with no raw time, which facts.md gives it
  as it gives any other ([ASOF-2]). Version 0.1.0 gave it only the raw
  times, which name their filing only when there is one.
- **TIME-7's interpreter reads only the form the findings record**
  ([TIME-10]). Version 0.1.0's read an `acceptanceDateTime` as the instant
  it states, and named no form, so one that states an instant in another
  form, such as `2025-10-31T14:01:26Z`, without milliseconds, gave that
  instant, and now gives nothing.
- **A raw time read from a body the caller gives** keeps that body's URL
  and SHA-256 ([TIME-3]), where version 0.1.0 named only a cached body. A
  raw time read from a cache keeps what version 0.1.0 gave it.
- **TIME-8's interpreter returns nothing for a header time that names no
  local time in its zone, or no instant** ([TIME-11]), which version 0.1.0
  didn't say.

[0009]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/docs/decisions/0009-read-edgar-through-a-public-point-in-time-library.md
[Times]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/docs/design.md#times
[SRC-1]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-2]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-12]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-13]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[READ-1]: fetching.md#8-functions-and-types
[READ-3]: fetching.md#8-functions-and-types
[CACHE-7]: fetching.md#6-the-cache
[ASOF-1]: facts.md#7-as-of-t
[ASOF-2]: facts.md#7-as-of-t
[TIME-1]: #3-raw-times
[TIME-2]: #3-raw-times
[TIME-3]: #3-raw-times
[TIME-5]: #3-raw-times
[TIME-6]: #4-interpreters
[TIME-7]: #4-interpreters
[TIME-8]: #4-interpreters
[TIME-10]: #4-interpreters
[TIME-11]: #4-interpreters
[TIME-12]: #5-functions-and-types
[TIME-13]: #5-functions-and-types
[TIME-14]: #5-functions-and-types
[TIME-15]: #5-functions-and-types
