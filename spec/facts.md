# Specification: facts

**Status:** Version 1.0.0, draft, October 17, 2026. This document governs
what `edgar-asof` makes of a company's `companyfacts`: each value as a
fact, joined to the raw acceptance times of the filing that reported it;
what "as of T" returns; what an answer records about its inputs; and the
functions and types a caller uses for facts. Where code and this document
disagree, the code is wrong or this document needs a new version; say
which before changing either.

`edgar-data-pipeline`'s decision [0009] gives this library the fact model
and what "as of T" returns, and that repository's facts specification is to
cite a version of this one. Each value is kept in two times, as in
Fowler's [Bitemporal History]: its period, when it was true, and the
acceptance time of the filing that reported it, when it became known. The
library reads its bodies as [`fetching.md`](fetching.md) says, and keeps
acceptance times raw and turns them into instants as
[`times.md`](times.md) says, both at version 1.0.0. Data read by this
library comes from the U.S. Securities and Exchange Commission's EDGAR
system; this document depends on how EDGAR behaves only where it cites a
finding, and in the parts of the feeds' layout that no finding records
yet, which [§10](#10-open-questions)'s second question names.

Version 1.0.0 uses fetching.md's and times.md's names and types in its
functions and types ([§8](#8-functions-and-types)), and gives an
interpreter each filing's accession number as well as its raw times, as
times.md's version 1.0.0 has an interpreter take them ([ASOF-2]).
[§11](#11-changes-to-this-document) lists what changed from version
0.1.0.

## 1. Guarantees

Each guarantee holds because of the statements it lists.

1. **Every value `companyfacts` gives is a fact, kept as given, beside
   every other value for its key.** [FACT-6], [FACT-7], [FACT-8],
   [FACT-9].
2. **Each fact keeps its filing's acceptance times as their sources give
   them.** [FACT-10], [FACT-11], [FACT-12], and times.md's [TIME-1] to
   [TIME-4].
3. **"As of T" is decided by acceptance alone, through the caller's
   interpreter.** [ASOF-1], [ASOF-2], [ASOF-4].
4. **An answer never guesses.** When facts share the latest instant, from
   one filing or several, it gives each of them, and it gives apart the
   facts whose filings the interpreter couldn't place. [ASOF-3].
5. **An answer can be reproduced.** It names each body it was read from by
   URL and SHA-256, and the same bodies, key, T, and interpreter give the
   same answer. [FACT-5], [ASOF-4], [ASOF-5], [ASOF-6].
6. **Facts are read through fetching.md's rules, or from bodies the caller
   gives, from which nothing is fetched.** [FACT-1], [FACT-2], [FACT-3].

## 2. Terms

As in [`fetching.md`](fetching.md#2-terms): **feed**, **body**,
**version**, **cache**, and **read**. As in
[`times.md`](times.md#1-terms): **raw time**, **instant**, and
**interpreter**. And for this document:

- **Company:** a filer, named by its CIK.
- **Value:** an entry that a company's `companyfacts` gives for a concept
  and a unit. It has its `val`; its `end`, and for most durations a
  `start`; the `accn` of the filing that reported it; that filing's
  `form`, `filed`, `fy`, and `fp`; and for some values a `frame` ([SRC-6],
  [SRC-8], [SRC-11], [SRC-14]).
- **Concept:** what a value measures, which `companyfacts` names within a
  taxonomy, such as `us-gaap` or `dei` ([SRC-14]). **Unit:** what it's
  measured in, such as `USD` or `shares`.
- **Key:** a company, a concept, a unit, and a period: a `start` and an
  `end`, as `edgar-data-pipeline`'s findings key values ([SRC-14]).
- **Fact:** a value, with its key and its filing
  ([§5](#5-facts)).
- **Filing:** the filing an accession number names.
- **List:** `submissions`' `filings.recent`, or one of its further files.
  Each lists filings in the same columns ([SRC-12]).
- **A read of facts:** reading one company's bodies and making its facts
  ([§4](#4-reading-a-companys-facts)).
- **Source:** where a read of facts takes its bodies: a cache, or bodies
  the caller gives ([FACT-2]).
- **Placed:** a fact is placed at the instant an interpreter gives its
  filing, and **unplaced** when the interpreter gives nothing.
- **Known at T:** placed at or before the instant T.

## 3. Statement IDs

As in [`fetching.md`](fetching.md#3-statement-ids). The areas here, `FACT`
and `ASOF`, aren't used in `edgar-data-pipeline`, so an ID names one
statement across both repositories.

## 4. Reading a company's facts

A read of facts reads every body it needs before it makes any fact, so an
answer only interprets and compares, and reads nothing
([§7](#7-as-of-t)).

- **FACT-1** (rule) A read of facts is for one company, named by its CIK,
  an integer from 1 to 9,999,999,999. It reads these bodies, at the URLs
  that [fetching.md's §5](fetching.md#5-feeds) and [SRC-21] give, and no
  others:
  1. The company's `companyfacts`.
  2. Its `submissions`.
  3. Each further file that `submissions` names in `filings.files` whose
     `filingFrom` to `filingTo` holds the `filed` date of one of the
     company's values. A further file lists no filing outside those dates,
     and a value's `filed` is its filing's `filingDate` ([SRC-9],
     [SRC-12]).
  4. When the caller asks for headers, the header of each filing that a
     value names and a list read holds.
- **FACT-2** (rule) A read of facts takes each body from the source the
  caller passes. From a cache, each body is read as fetching.md says
  ([CACHE-8], [READ-3]), in the cache's directory, and fetched, when it
  must be, with the user agent the caller gives the cache ([CLIENT-2],
  [CACHE-9], [READ-5]). From bodies the caller gives, each with its URL,
  the library fetches nothing, and a read of facts that needs a URL the
  caller didn't give fails, with an error that names the URL ([READ-2]).
- **FACT-3** (rule) When the caller asks for a fresh read, the company's
  `companyfacts`, `submissions`, and further files are each read with a
  fresh fetch ([CACHE-8]), and its headers without one. A fresh read from
  bodies the caller gives fails before reading anything, since it can't
  fetch ([READ-4]).
- **FACT-4** (rule) A read of facts fails, and makes no facts, if a read
  of one of its bodies fails ([READ-2], [READ-6], [CACHE-10]), or if a
  body isn't what this document reads:
  - `submissions` is read when it's a JSON object whose `filings.recent`
    holds the columns `accessionNumber` and `acceptanceDateTime`, lists of
    strings of one length, and whose `filings.files` is a list of objects,
    each with a `name` that [fetching.md's §5](fetching.md#5-feeds) takes
    as a further file's name, and a `filingFrom` and a `filingTo` that are
    dates, `YYYY-MM-DD`. A further file is read when it's a JSON object
    that holds those columns itself ([SRC-12]).
  - `companyfacts` is read when it gives each value under its concept,
    named within its taxonomy, and its unit. Each value has a
    `val` that is a number; an `end` and a `filed` that are dates; and an
    `accn` and a `form` that are strings. Where it has a `start`, a `fy`,
    an `fp`, or a `frame` that isn't null, the `start` is a date, the `fy`
    an integer, and the `fp` and the `frame` strings ([SRC-6], [SRC-8],
    [SRC-11]).
  - A header is read whatever it gives. One that doesn't give its
    `ACCEPTANCE-DATETIME` as the 14 digits that times.md reads ([TIME-1],
    [SRC-1]) gives its filing no raw time ([FACT-11]).

  No finding yet records the column `accessionNumber`, what
  `filings.files` is for a company with no further file, or how
  `companyfacts` nests its values, which
  [§10](#10-open-questions)'s second question leaves open.
- **FACT-5** (rule) A company's facts record, as their inputs, the URL and
  `sha256` of each body the read of facts took, as fetching.md's read
  returns them ([READ-3]), ordered by URL. A cached body's `sha256` is
  that of the version read ([CACHE-7]); a given body's is the SHA-256 of
  its bytes.

So the same facts can be read again from those versions, given as bodies,
wherever a cache or a snapshot store keeps them ([CACHE-5]).

## 5. Facts

- **FACT-6** (rule) Each value that `companyfacts` gives becomes one fact,
  and nothing else does. No value is dropped, merged with another, or
  replaced by another filing's value for its key, which `companyfacts`
  keeps beside it ([SRC-14]). No filing of the three companies
  `edgar-data-pipeline` investigated gives a key twice ([SRC-14]), and if
  another company's does, each of its values for the key is a fact, as
  any value is, ordered as [ASOF-5] says.
- **FACT-7** (rule) A fact's key is the company's CIK; its concept,
  written as the taxonomy, a colon, and the concept's name, such as
  `us-gaap:Revenues`; its unit, as given; and its value's `start`, if it
  has one, and its `end`, as dates. A value without a `start` has a key
  without one. The library doesn't take it for an instant, since a
  duration that starts and ends on the same day has no `start` either
  ([SRC-11]).
- **FACT-8** (rule) A fact's value is its `val`, exactly as written: an
  integer, with no fraction or exponent, as an integer, and any other
  number as a decimal, never as a binary floating-point number.
- **FACT-9** (rule) A fact keeps its value's `form`, its `filed` as a
  date, and its `fy`, `fp`, and `frame`, each as given, with none where
  the value has none or gives null ([SRC-6], [SRC-8]).

These five describe the filing, or a calendar period, not the value's own
period. `fy` and `fp` are the fiscal year and period of the filing that
reported a value, whatever the value's dates, and Walmart's filings
through March 2014 name a fiscal year differently from its later ones
([SRC-6], [SRC-7]). A `frame` is a calendar period matched to the value's,
not the value's own ([SRC-8]), and only the latest-filed value of a key
has one, so it follows the version of `companyfacts` read, not what was
known at any time ([SRC-17]). So a fact's period is its key's `start` and
`end` alone, and none of the five decides an answer ([ASOF-4]).

## 6. Filings and their acceptance times

- **FACT-10** (rule) A fact's filing is the one its value's `accn` names.
  When a list read holds that accession number, the filing has the list's
  `acceptanceDateTime` for it as its raw time from `submissions`
  ([TIME-2], [SRC-9], [SRC-12]). No accession number is in two of a
  company's lists ([SRC-12]), and if the lists read hold one more than
  once, in one list or in two, the read of facts fails.
- **FACT-11** (rule) When the caller asks for headers, each filing that a
  value names and a list read holds also has its header's raw time
  ([TIME-1]), beside the one from `submissions` ([TIME-4]), if its header
  gives `ACCEPTANCE-DATETIME` as the 14 digits that times.md reads. A
  filing whose header doesn't has only its raw time from `submissions`,
  and its facts are kept as any others are ([FACT-6]): times.md's
  interpreter of the header's digits leaves them unplaced ([TIME-8]). No
  other filing's header is read ([FACT-1]).
- **FACT-12** (rule) A filing that no list read holds has no raw time from
  `submissions`, and the library doesn't read its header, since [SRC-21]
  gives the URL of only a listed filing's files. Its facts are kept as any
  others are ([FACT-6]).

Every value of the three companies `edgar-data-pipeline` investigated
joins to a filing in a list ([SRC-12]), but another company's may not. A
fact whose filing has no raw time stays among the facts, and an answer
gives it as unplaced unless the caller's interpreter places it
([ASOF-2]).

A header's raw time is the one that times.md's interpreter of the
header's digits reads ([TIME-8]), so that interpreter places a fact only
when its read of facts asked for headers, and its filing's header gave
the 14 digits ([FACT-11]). Such a read takes one more body for each
filing with values: 216 for the three companies `edgar-data-pipeline`
investigated ([SRC-6]).

## 7. As of T

An answer says which of a key's facts were known at an instant T, by the
acceptance of their filings alone, as `edgar-data-pipeline`'s design has
it ([Times]): the latest filing accepted at or before T gives the value
known, and later filings give the values that came after.

- **ASOF-1** (rule) An answer is for one key, an instant T, and an
  interpreter, all three of which the caller passes ([TIME-6],
  [TIME-14]). Without an interpreter, or for a key of another company, it
  raises an error before interpreting anything ([TIME-9]).
- **ASOF-2** (rule) For each answer, the library gives the interpreter
  each filing of the key's facts once: its accession number, and its raw
  times, each with its source, whether it has two, one, or none
  ([TIME-6], [TIME-13]). Each fact is placed at the instant the
  interpreter gives its filing, or unplaced if it gives nothing.
- **ASOF-3** (rule) An answer gives each fact of the key in exactly one of
  four parts. Facts placed at or before T are known at T: those at the
  latest such instant are its `known`, and the others its `earlier`. Facts
  placed after T are its `later`, and the unplaced are its `unplaced`. So
  `known` is empty when no fact of the key is known at T, as when the key
  has no facts, and it holds more than one fact only when they share that
  instant: the library doesn't choose among them.
- **ASOF-4** (rule) Which part a fact is in depends only on T and the
  instants the interpreter gives. A fact's `fy`, `fp`, `frame`, `form`,
  and `filed`, and the order in which `companyfacts` and the lists give
  values and filings, change nothing. So an amendment is known from its
  own acceptance, as any filing is ([SRC-16]), and two filings of the same
  day are ordered by their instants, not by `filed` ([SRC-10]).
- **ASOF-5** (rule) `earlier` and `later` are ordered by instant, then by
  accession number, and `known` and `unplaced` by accession number. Facts
  with the same accession number, as when a filing gives the key twice
  ([FACT-6]), are then ordered by their value, as numbers, then by their
  value as written, and then by `form`, `filed`, `fy`, `fp`, and `frame`,
  in that order, with none first. A value as written is the text of its
  `val`, as `companyfacts` writes the number, and two such texts are
  compared character by character, by code point, with the shorter first
  where one begins the other, so `1` comes before `1.0`. Accession numbers
  order facts only so that an answer is repeatable, not as times, and
  these fields only so that its order doesn't depend on the order in which
  `companyfacts` gives values. Facts that tie on all of them are equal, so
  their order changes nothing.
- **ASOF-6** (rule) An answer also gives its key, T, its interpreter, and
  the inputs of its company's facts ([FACT-5]).

An answer doesn't say whether a fact restates an earlier one or reports it
again, rounded or unchanged. `companyfacts` marks no change and gives no
`decimals`, so a changed `val` can be either ([SRC-15]). Each fact's value
is as given, and comparing them is for the caller.

For example, Apple's `us-gaap:OtherAssetsNoncurrent` in `USD` at
2025-09-27, with no `start`, is 83,727,000,000 in its 10-K for the year
ending then and in its 10-Q of 2026-01-30, and 72,634,000,000 in its
10-Qs of 2026-05-01 and 2026-07-31 ([SRC-15]). As of
2026-03-01T00:00:00Z, with times.md's interpreter of `submissions`' time
([TIME-7]), the 10-Q of 2026-01-30's fact is `known`, the 10-K's is
`earlier`, and the other two 10-Qs' are `later`.

## 8. Functions and types

The package `edgar_asof` gives a caller the function and types below.
Where they use a source, a body's URL and `sha256`, a raw time, an
instant, or an interpreter, they use fetching.md's and times.md's names
and types: `Source` and `BodyRef` ([READ-1]); and `RawTime`, an instant,
a `datetime.datetime` in UTC, and `Interpreter` ([TIME-12]).

| Name | Kind | Parameters or fields |
| --- | --- | --- |
| `read_facts(cik, source, *, headers=False, fresh=False)` | Function | Reads a company's facts and returns its `CompanyFacts` ([§4](#4-reading-a-companys-facts)). `cik` is the company's CIK, an `int` ([FACT-1]); `source`, a `Source`, is where its bodies come from ([FACT-2]); `headers` asks for headers ([FACT-1], [FACT-11]); and `fresh` for a fresh read ([FACT-3]). |
| `CompanyFacts` | Type | `cik`, an `int`. `inputs`, a tuple of `BodyRef`, each body's URL and `sha256` ([FACT-5]). `keys()`, a tuple of every key that has a fact, ordered by concept, unit, `end`, and `start`, with no `start` first. `facts(key)`, a tuple of the key's facts, ordered by accession number and then, for the facts of one filing, as [ASOF-5] orders them, and empty for a key with none. `as_of(key, at, interpreter)`, an `Answer` ([§7](#7-as-of-t)), where `at` is T, a `datetime.datetime` with a time zone ([TIME-14]), and `interpreter` an `Interpreter` ([TIME-13]). |
| `Key` | Type | `cik`, an `int`; `concept` and `unit`, each a `str`; `start`, a `datetime.date` or `None`; and `end`, a `datetime.date` ([FACT-7]). |
| `Fact` | Type | `key`, a `Key`; `value`, an `int` or a `decimal.Decimal` ([FACT-8]); `filing`, a `Filing`; `form`, a `str`; `filed`, a `datetime.date`; `fy`, an `int` or `None`; and `fp` and `frame`, each a `str` or `None` ([FACT-9]). |
| `Filing` | Type | `accession_number`, a `str`, as `accn` gives it; and `raw_times`, a tuple of `RawTime`, the filing's raw times: two, one, or none, the header's first ([FACT-10] to [FACT-12], [TIME-13]). |
| `Placed` | Type | `fact`, a `Fact`; and `accepted`, the instant the interpreter gave its filing, a `datetime.datetime` in UTC ([ASOF-2], [TIME-14]). |
| `Answer` | Type | `key`, a `Key`; `at`, the instant T, a `datetime.datetime` in UTC ([TIME-14]); `interpreter`, the `Interpreter` passed; `earlier`, `known`, and `later`, each a tuple of `Placed`; `unplaced`, a tuple of `Fact`; and `inputs`, its `CompanyFacts`' ([ASOF-3] to [ASOF-6]). |
| `FactsError` | Exception | A body that a read of facts can't read ([FACT-4], [FACT-10]). A header that's read never raises it ([FACT-11]). |

- **FACT-13** (rule) The package `edgar_asof` gives the function and types
  in the table, with their parameters and fields. Each type but
  `FactsError` is immutable, and a `Key` is hashable, and equal to another
  with the same fields.
- **FACT-14** (rule) An argument this document refuses raises
  `ValueError`, before anything is read or interpreted: a CIK out of range
  ([FACT-1]), a fresh read from bodies the caller gives ([FACT-3]), a key
  of another company, given to `facts` or `as_of`, and an interpreter of
  `None` ([ASOF-1]). A T, or an interpreter's result, that times.md
  refuses raises the error that its [TIME-14] gives. A body that a read of
  facts can't read raises `FactsError`, which names the body's URL
  ([FACT-4], [FACT-10]); a header that's read never raises it
  ([FACT-11]). A read of a body that fails raises the `ReadError` that
  fetching.md gives it ([READ-6], [CACHE-10]), and a read of facts that
  needs a URL the caller didn't give raises `BodyNotGivenError` ([FACT-2],
  [READ-2]).

## 9. Index

| ID | Kind | Checked by | Statement |
| --- | --- | --- | --- |
| FACT-1 | rule | tests | A read of facts reads `companyfacts`, `submissions`, the further files its values' dates need, and, if asked, headers. |
| FACT-2 | rule | tests | Bodies come from a cache, as fetching.md reads them, or from the caller, with nothing fetched. |
| FACT-3 | rule | tests | A fresh read fetches the company's lists and `companyfacts` again, and fails on given bodies. |
| FACT-4 | rule | tests | A failed read or an unreadable body fails the read of facts, and makes no facts; a header without the 14 digits doesn't. |
| FACT-5 | rule | tests | Facts record each body's URL and `sha256` as their inputs. |
| FACT-6 | rule | tests | Each value becomes one fact, and none replaces another; a key given twice by one filing has a fact for each value. |
| FACT-7 | rule | tests | A key is the CIK, `taxonomy:name`, the unit, and the dates as given. |
| FACT-8 | rule | tests | A value is kept exactly, as an integer or a decimal. |
| FACT-9 | rule | tests | `form`, `filed`, `fy`, `fp`, and `frame` are kept as given. |
| FACT-10 | rule | tests | A fact's filing has its list's `acceptanceDateTime`; an accession number listed twice fails the read. |
| FACT-11 | rule | tests | When asked, a listed filing that a value names also has its header's raw time, if its header gives the 14 digits. |
| FACT-12 | rule | tests | A filing no list holds has no raw time from `submissions`, and its facts are kept. |
| ASOF-1 | rule | tests | An answer is for a key, T, and an interpreter the caller passes. |
| ASOF-2 | rule | tests | Each filing is interpreted once, by its accession number and raw times; its facts are placed at its instant, or unplaced. |
| ASOF-3 | rule | tests | Each fact is in one of `earlier`, `known`, `later`, and `unplaced`; ties are all `known`. |
| ASOF-4 | rule | tests | Only T and the instants decide an answer. |
| ASOF-5 | rule | tests | Each part is in a fixed order, total even among one filing's facts. |
| ASOF-6 | rule | tests | An answer gives its key, T, interpreter, and inputs. |
| FACT-13 | rule | tests | The package gives the function and types of §8, immutable. |
| FACT-14 | rule | tests | Refused arguments raise `ValueError`, unreadable bodies `FactsError`, and failed reads fetching.md's errors. |

## 10. Open questions

1. **Whether `companyfacts` can give a new filing's values before
   `submissions` lists the filing** (the investigation's Q4). If it can, a
   fresh read soon after a filing is accepted gives its facts no raw time
   from `submissions` ([FACT-12]), and times.md's interpreters leave them
   unplaced until a later fresh read finds the filing listed. Proposed
   default: as written, so nothing is inferred, until a finding from
   `edgar-data-pipeline`'s record shows how soon each feed shows a filing.
   The owner kept this default on October 14, 2026.
2. **The parts of the feeds' layout that no finding records yet.** The
   findings name the values' fields, the column `acceptanceDateTime`, and
   the further files ([SRC-6], [SRC-12], [SRC-14], [SRC-21]), but not how
   `companyfacts` nests its values, under `facts`, each taxonomy, each
   concept, `units`, and each unit; the column `accessionNumber`, which
   holds a list's accession numbers; or what `filings.files` is for a
   company with no further file. [FACT-4] checks all three, and [FACT-7]
   writes a concept from the first. If `filings.files` were missing for
   such a company, FACT-4 as written would fail every read of its facts.
   Proposed default: as written, with a finding in `edgar-data-pipeline`
   that records this layout, which T8 depends on and this document then
   cites. The owner deferred the finding until T8 on October 14, 2026, and
   the [plan](../docs/plan.md)'s T8 depends on it.

### Left to other specifications

- **Later versions of this one:** published cases, with their inputs and
  answers (the plan's T10); and facts read from XBRL instances (T11),
  whose keys may need dimensions, which no `companyfacts` value has
  ([SRC-14]).
- **`edgar-data-pipeline`'s facts specification (its T17):** how the
  pipeline stores facts, citing a version of this one.

## 11. Changes to this document

Versions follow semantic versioning. Adding a statement, a type, a field,
a parameter with a default, or a check is a minor version. Changing the
meaning of a statement or of a key, or which part of an answer a fact is
in, is a major version. IDs are never reused, and a retired statement stays
in the index.

### Version 1.0.0

Version 1.0.0 cites fetching.md and times.md at their version 1.0.0,
where version 0.1.0 cited both at version 0.1.0. It's a major version
because of two changes that come with times.md's version 1.0.0, either
of which alone would make it one: what the library gives an interpreter,
and which part of an answer a fact can be in through times.md's
interpreter of `submissions`' time. The rest would need no major version
alone:

- **An interpreter also takes its filing's accession number** ([ASOF-2]),
  as times.md's version 1.0.0 has it ([TIME-6]), so that it can place a
  filing with no raw time. Version 0.1.0 gave it a filing's raw times
  alone, so an interpreter written for it takes one argument where the
  library now passes two ([TIME-13]).
- **Through times.md's interpreter of `submissions`' time, a filing whose
  `acceptanceDateTime` isn't in the form the findings record is
  unplaced** ([TIME-10]). Under version 0.1.0, that interpreter placed it
  at the instant it states, so its facts move from `earlier`, `known`, or
  `later` to `unplaced` ([ASOF-3]).
- **[§8](#8-functions-and-types) uses fetching.md's and times.md's names
  and types,** which version 0.1.0 left to their next versions: `Source`,
  for `read_facts`' `source`; `BodyRef`, for `CompanyFacts.inputs`;
  `RawTime`, for `Filing.raw_times`, the header's first; a
  `datetime.datetime`, for `as_of`'s `at`, and one in UTC for `Answer.at`
  and `Placed.accepted`; and `Interpreter`, for `as_of`'s interpreter and
  `Answer.interpreter`. [FACT-14] names the errors that the other two
  specifications give a read and a T, `BodyNotGivenError` among them.
- **A further file's name is checked** ([FACT-4]). `submissions` is read
  only when each `name` in its `filings.files` is one that fetching.md's
  §5 takes as a further file's, since fetching.md's version 1.0.0 allows
  a further file's URL by its form ([CLIENT-1]), where its version 0.1.0
  allowed whatever file `submissions` named.
- **The statements cite what fetching.md's and times.md's version 1.0.0
  add:** how a read takes its body and how it fails ([FACT-2] to
  [FACT-5]), and how an interpreter is called and an instant taken
  ([ASOF-1], [ASOF-2]). FACT-4 cites the errors of a read ([READ-2],
  [READ-6], [CACHE-10]), where version 0.1.0 cited fetching.md's CLIENT-8
  to CLIENT-13, which don't name every way a read now fails, such as a
  cache it can't read.
- **"Left to other specifications" no longer lists fetching.md's and
  times.md's next versions,** whose version 1.0.0 did what it listed.

[0009]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/docs/decisions/0009-read-edgar-through-a-public-point-in-time-library.md
[Bitemporal History]: https://martinfowler.com/articles/bitemporal-history.html
[Times]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/docs/design.md#times
[SRC-1]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-6]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-7]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-8]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-9]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-10]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-11]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-12]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-14]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-15]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-16]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-17]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-21]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[CLIENT-1]: fetching.md#4-requests
[CLIENT-2]: fetching.md#4-requests
[CACHE-5]: fetching.md#6-the-cache
[CACHE-7]: fetching.md#6-the-cache
[CACHE-8]: fetching.md#6-the-cache
[CACHE-9]: fetching.md#6-the-cache
[CACHE-10]: fetching.md#6-the-cache
[READ-1]: fetching.md#8-functions-and-types
[READ-2]: fetching.md#8-functions-and-types
[READ-3]: fetching.md#8-functions-and-types
[READ-4]: fetching.md#8-functions-and-types
[READ-5]: fetching.md#8-functions-and-types
[READ-6]: fetching.md#8-functions-and-types
[TIME-1]: times.md#3-raw-times
[TIME-2]: times.md#3-raw-times
[TIME-4]: times.md#3-raw-times
[TIME-6]: times.md#4-interpreters
[TIME-7]: times.md#4-interpreters
[TIME-8]: times.md#4-interpreters
[TIME-9]: times.md#4-interpreters
[TIME-10]: times.md#4-interpreters
[TIME-12]: times.md#5-functions-and-types
[TIME-13]: times.md#5-functions-and-types
[TIME-14]: times.md#5-functions-and-types
[FACT-1]: #4-reading-a-companys-facts
[FACT-2]: #4-reading-a-companys-facts
[FACT-3]: #4-reading-a-companys-facts
[FACT-4]: #4-reading-a-companys-facts
[FACT-5]: #4-reading-a-companys-facts
[FACT-6]: #5-facts
[FACT-7]: #5-facts
[FACT-8]: #5-facts
[FACT-9]: #5-facts
[FACT-10]: #6-filings-and-their-acceptance-times
[FACT-11]: #6-filings-and-their-acceptance-times
[FACT-12]: #6-filings-and-their-acceptance-times
[FACT-14]: #8-functions-and-types
[ASOF-1]: #7-as-of-t
[ASOF-2]: #7-as-of-t
[ASOF-3]: #7-as-of-t
[ASOF-4]: #7-as-of-t
[ASOF-5]: #7-as-of-t
[ASOF-6]: #7-as-of-t
