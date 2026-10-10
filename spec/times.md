# Specification: acceptance times

**Status:** Version 0.1.0, draft, October 10, 2026. This document governs
how `edgar-asof` reads a filing's acceptance time and turns it into an
instant. Where code and this document disagree, the code is wrong or this
document needs a new version; say which before changing either.

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
  `sha256` of the cached body it was read from
  ([`fetching.md`](fetching.md#6-the-cache)).
- **TIME-4** (rule) When the library has both raw times for a filing, it
  keeps both, and neither replaces the other.
- **TIME-5** (rule) The library compares, orders, or converts raw times only
  through an interpreter.

## 4. Interpreters

- **TIME-6** (rule) An interpreter takes a filing's raw times, each with its
  source, and returns an instant, or nothing if it can't make one from
  them. Wherever the library turns acceptance times into instants, the
  caller can pass an interpreter of their own.
- **TIME-7** (rule) The library provides an interpreter that reads
  `submissions`' `acceptanceDateTime` as the instant it states, in UTC to
  the millisecond ([SRC-2]), and returns nothing for a filing without one.
- **TIME-8** (rule) The library provides an interpreter that reads the
  header's digits as local time in a time zone the caller names by its IANA
  name, such as `America/New_York`, and returns nothing for a filing
  without a header time. It has no default zone. A local time that occurs
  twice, when daylight saving time ends, is read as the earlier instant.
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

## 5. Index

| ID | Kind | Checked by | Statement |
| --- | --- | --- | --- |
| TIME-1 | rule | tests | The header's acceptance time is kept as its 14 digits. |
| TIME-2 | rule | tests | `submissions`' `acceptanceDateTime` is kept as given. |
| TIME-3 | rule | tests | A raw time keeps its source, its filing, and the body it came from. |
| TIME-4 | rule | tests | A filing's two raw times are both kept. |
| TIME-5 | rule | tests | Raw times are compared, ordered, or converted only by an interpreter. |
| TIME-6 | rule | tests | An interpreter gives an instant or nothing, and the caller can pass one. |
| TIME-7 | rule | tests | An interpreter reads `submissions`' time as the UTC instant it states. |
| TIME-8 | rule | tests | An interpreter reads the header's digits in a zone the caller names. |
| TIME-9 | rule | tests | There is no default interpreter; the caller passes one. |

## 6. Open questions

None.

## 7. Changes to this document

Versions follow semantic versioning. Adding a statement or an interpreter
is a minor version. Changing the meaning of a statement, or which instant
an interpreter returns, is a major version. IDs are never reused, and a
retired statement stays in the index.

[0009]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/docs/decisions/0009-read-edgar-through-a-public-point-in-time-library.md
[Times]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/docs/design.md#times
[SRC-1]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-2]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-12]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-13]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[TIME-8]: #4-interpreters
