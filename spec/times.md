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
  `YYYY-MM-DDTHH:MM:SS.sssZ`, with a date that exists and a time from
  `00:00:00.000` to `23:59:59.999`. For a filing whose
  `acceptanceDateTime` has another form, it returns nothing.
- **TIME-8** (rule) The library provides an interpreter that reads the
  header's digits as local time in a time zone the caller names by its IANA
  name, such as `America/New_York`, and returns nothing for a filing
  without a header time. It has no default zone. A local time that occurs
  twice, when daylight saving time ends, is read as the earlier instant.
- **TIME-11** (rule) TIME-8's interpreter returns nothing for a filing
  whose header's digits name no local time in its zone: a date that
  doesn't exist, a time outside `00:00:00` to `23:59:59`, or a time that
  the zone skips, as when daylight saving time starts.
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
| `Interpreter` | Type alias | A callable that takes a filing's `accession_number`, a `str`, and its `raw_times`, a tuple of `RawTime`, and returns an instant or `None` ([TIME-6], [TIME-13]). |
| `submissions_utc(accession_number, raw_times)` | Function | An interpreter that reads `submissions`' `acceptanceDateTime` as the UTC instant it states ([TIME-7], [TIME-10]). |
| `header_in_zone(zone)` | Function | Returns an interpreter that reads the header's digits as local time in `zone`, a `str`, a time zone's IANA name, such as `"America/New_York"` ([TIME-8], [TIME-11]). |

- **TIME-12** (rule) The package `edgar_asof` gives the functions and
  types in the table, with their parameters and fields. An instant is a
  `datetime.datetime` whose `tzinfo` is `datetime.timezone.utc`, and each
  instant that the library's interpreters return is one. A `RawTime` is
  immutable and hashable, equal to another only with the same fields, and
  has no order, so it's compared as a time only through an interpreter
  ([TIME-5]). An interpreter that `header_in_zone` returns is immutable,
  and equal to another for the same zone, with the same hash. Each of the
  library's interpreters has a `repr` that names it, and the zone of one
  that `header_in_zone` returns, as `header_in_zone('America/New_York')`.
- **TIME-13** (rule) The library calls an interpreter with a filing's
  accession number and a tuple of its raw times, as
  [`facts.md`'s ASOF-2][ASOF-2] gives each filing to it: at most one from
  each source, the header's before `submissions`'. Wherever the library
  gives a filing's raw times, as in `Filing.raw_times`, they're in that
  order.
- **TIME-14** (rule) Where the library takes an instant, from the caller
  as an answer's T ([ASOF-1]) or from an interpreter, it takes a
  `datetime.datetime` with a time zone, one whose `utcoffset()` isn't
  `None`, whatever the zone, as the same instant in UTC, and each instant
  it gives, such as `Placed.accepted` and `Answer.at`, is in UTC
  ([TIME-12]). A
  `datetime` without a time zone, given as T, raises `ValueError` before
  anything is interpreted. An interpreter that returns anything but `None`
  or a `datetime` with a time zone raises `TypeError`, which names the
  filing's accession number.
- **TIME-15** (rule) An argument this document refuses raises
  `ValueError`: a `RawTime` whose `source` is neither `"header"` nor
  `"submissions"`; a `zone` that Python's `zoneinfo` can't find, given to
  `header_in_zone`; and raw times that hold more than one from a source,
  given to one of the library's interpreters, which the library never
  gives it ([TIME-13]).

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
| TIME-11 | rule | tests | Header digits that name no local time in the zone give nothing. |
| TIME-9 | rule | tests | There is no default interpreter; the caller passes one. |
| TIME-12 | rule | tests | The package gives §5's functions and types; an instant is a UTC `datetime`. |
| TIME-13 | rule | tests | An interpreter is given a filing's accession number and its raw times, the header's first. |
| TIME-14 | rule | tests | An instant taken in any zone is read in UTC; a T without a zone, or another result, raises. |
| TIME-15 | rule | tests | Refused arguments raise `ValueError`. |

## 7. Open questions

None.

## 8. Changes to this document

Versions follow semantic versioning. Adding a statement or an interpreter
is a minor version. Changing the meaning of a statement, or which instant
an interpreter returns, is a major version. IDs are never reused, and a
retired statement stays in the index.

### Version 1.0.0

Version 1.0.0 changes what two statements mean, and settles what two
others left open:

- **An interpreter also takes its filing's accession number** ([TIME-6]),
  so that it can place a filing with no raw time, which facts.md gives it
  as it gives any other ([ASOF-2]). Version 0.1.0 gave it only the raw
  times, which name their filing only when there is one.
- **A raw time read from a body the caller gives** keeps that body's URL
  and SHA-256 ([TIME-3]), where version 0.1.0 named only a cached body.
- **TIME-7's interpreter reads only the form the findings record**
  ([TIME-10]), and **TIME-8's returns nothing for digits that name no
  local time in its zone** ([TIME-11]), which version 0.1.0 didn't say.

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
