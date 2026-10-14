# Specification: fetching and the cache

**Status:** Version 1.0.0, draft, October 14, 2026. This document governs
how `edgar-asof` requests EDGAR's feeds, keeps what it receives, and reads
a body, from its cache or from the caller. Where code and this document
disagree, the code is wrong or this document needs a new version; say
which before changing either.

The library fetches for people who use it on its own, under the SEC's rules
for automated access
([Accessing EDGAR data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)).
It also reads bodies that a caller gives it, and fetches nothing for them,
as `edgar-data-pipeline`'s services give it bodies from their store
(FETCH-18 in the store's version 1.0.0). Its cache follows the snapshot
store of `edgar-data-pipeline`, as that repository's decision [0009] says:
each body stored once by its SHA-256, each fetch a record, and nothing
overwritten. The store is specified in that repository's
[`spec/snapshots.md`][store], version 0.2.0, whose statements are cited
here as the store's, such as the store's FETCH-6.
[§7](#7-where-the-cache-departs-from-the-store) lists where this document
departs from it, and why. Data read by this library comes from the U.S.
Securities and Exchange Commission's EDGAR system.

Version 1.0.0 gives the functions and types a caller uses to read a body
([§8](#8-functions-and-types)): from a cache, with a fresh fetch when the
caller asks for one, or from bodies the caller gives; the errors a read
raises when it fails; and what a `304` returns.
[§11](#11-changes-to-this-document) says how a cache written under version
0.1.0 is read.

## 1. Guarantees

Each guarantee holds because of the statements it lists.

1. **Every body the library reads from a cache was fetched by a recorded
   request and is kept unchanged.** [CACHE-1], [CACHE-2], [CACHE-10],
   [CLIENT-14].
2. **Nothing in a cache is changed or removed.** A refetch adds a record,
   and a new body adds an object. [CACHE-3].
3. **No requester identity is kept.** [CLIENT-3].
4. **A snapshot store can be read as a cache, and the library never fetches
   into one.** [CACHE-5], [READ-6].
5. **Requests keep to the SEC's rules:** a user agent the caller supplies,
   and at most 5 requests a second from a process. [CLIENT-2], [CLIENT-7].
6. **A read is repeatable.** From a cache, it uses the version the cache
   holds, unless the caller asks for a fresh fetch, and from bodies the
   caller gives, the body given. [CACHE-8], [READ-3].
7. **A body the caller gives is read as given, and nothing is fetched or
   written for it.** The library can't know how it was fetched, so the
   first guarantee doesn't hold for it, but a read names it by its URL and
   SHA-256, as it names a cached body. [READ-2], [READ-3].

## 2. Terms

As in the store's §2:

- **Feed:** a named set of URLs fetched for one purpose ([§5](#5-feeds)).
- **Fetch:** one request for one URL, including any retries, ending in one
  record.
- **Body:** a response's content after any `Content-Encoding` is removed.
- **Object:** a stored body.
- **Version:** a distinct body among one URL's records ([CACHE-7]).

And for this document:

- **Cache:** a directory where the library keeps the bodies it fetched and
  their records ([§6](#6-the-cache)).
- **Source:** where a read takes its body: a cache, or bodies the caller
  gives, each with its URL ([§8](#8-functions-and-types)).
- **Read:** the library's use of a URL's body, from its source: from the
  cache or from a fetch into it, or from the body the caller gives.

## 3. Statement IDs

Every normative statement has an ID, such as `CLIENT-5`: an area and a
number. An ID is assigned once and never reused or renumbered. A statement
that is dropped stays in the [index](#9-index), marked retired. The areas
here, `CLIENT`, `CACHE`, and `READ`, aren't used in `edgar-data-pipeline`,
so an ID names one statement across both repositories.

Each statement is one of two kinds:

- An **invariant** is a property of a cache that holds whenever no fetch is
  writing to it.
- A **rule** is how the library behaves while it runs.

Tests check both. Every statement in the index has at least one test
marked with its ID, as `@pytest.mark.spec("CLIENT-5")`, and every marker
names an ID in the index. A test, `tests/test_spec_coverage.py`, enforces
both, except for a statement whose tests a later task in the
[plan](../docs/plan.md) writes. It lists such a statement as awaiting that
task, and fails if the statement has a test or the plan marks the task
done.

## 4. Requests

- **CLIENT-1** (rule) Only `https` URLs on `www.sec.gov` and `data.sec.gov`
  are requested, and only URLs of the feeds in [§5](#5-feeds), as in the
  store's FETCH-1.
- **CLIENT-2** (rule) Every request carries a `User-Agent` that the caller
  supplies, which must contain an `@`, following the SEC's sample of a name
  and a contact address. The library ships none and reads none from the
  environment or any file, and without one it requests nothing.
- **CLIENT-3** (rule) No file in a cache contains the `User-Agent` or any
  other request header, as in the store's ID-1.
- **CLIENT-4** (rule) Each request sends `Accept-Encoding: gzip`.
- **CLIENT-5** (rule) If the cache has an earlier record of the URL with a
  `sha256`, the latest such record's `etag` is sent as `If-None-Match` and
  its `last_modified` as `If-Modified-Since`, when they are set, as in the
  store's FETCH-4. `submissions` and `companyfacts` send neither, so a
  refetch of either returns the whole body. Filing headers send only
  `Last-Modified` ([SRC-4]).
- **CLIENT-6** (rule) Each attempt times out after 60 seconds, which counts
  as no response.
- **CLIENT-7** (rule) Requests from one process start at least 0.2 seconds
  apart, whatever caches they fetch into: at most 5 a second, half the
  SEC's stated maximum of 10, as in the store's FETCH-6. The SEC counts
  all of a user's requests, and the library can space only its own.
- **CLIENT-8** (rule) No response, a `429`, `500`, `502`, `503`, or `504`,
  and a body cut short ([CLIENT-13]) are retried, up to 4 attempts in all.
  The wait before a retry is the response's `Retry-After`, in seconds or as
  an HTTP date, or else 2 to the power of the attempt number, in seconds;
  either is capped at 60 seconds.
- **CLIENT-9** (rule) A `403`, which the SEC returns to clients over its
  limit, is recorded, the read fails with an error that says so, and the
  library sends no further request from that process.
- **CLIENT-10** (rule) Any other status but a `200` or a `304`
  ([CLIENT-16]) is recorded without a retry, and the read fails with an
  error that gives the status.
- **CLIENT-16** (rule) A `304` is recorded without a retry, naming the
  version its conditional request asked about, as in the store's REC-5,
  and the read returns that version's body ([READ-5]). A `304` to a
  request that sent no validators names nothing and is recorded with
  `error` set, as REC-5 also says, and the read fails.
- **CLIENT-11** (rule) A `Content-Encoding` of `gzip` or `x-gzip` is decoded
  before hashing and storing. No encoding, or `identity`, is stored as
  received.
- **CLIENT-12** (rule) Any other `Content-Encoding` is recorded with `error`
  set and nothing stored, without a retry, and the read fails.
- **CLIENT-13** (rule) A body cut short stores nothing and is retried
  ([CLIENT-8]): one with fewer bytes than its `Content-Length`, one whose
  connection fails mid-stream, and one whose gzip encoding ends early or
  doesn't decode. If the last attempt is cut short too, the record has the
  status and `error` set, and the read fails.
- **CLIENT-14** (rule) A fetch appends exactly one record, describing its
  final attempt, after the object it names, if any, is in place
  ([CACHE-2]).

## 5. Feeds

The library reads three feeds, named as in the store, so that a store's
records are found by feed ([CACHE-5]):

| Feed | URLs | Read for |
| --- | --- | --- |
| `submissions` | `https://data.sec.gov/submissions/CIK##########.json`, and the further files it names in `filings.files`, such as `CIK0000320193-submissions-001.json` ([SRC-10]) | Each filing and its acceptance time ([`times.md`](times.md)) |
| `companyfacts` | `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | The values a company reported, each with the accession number of the filing that reported it ([SRC-9]) |
| `filings` | A filing's header, `https://www.sec.gov/Archives/edgar/data/CIK/ACCESSION/ACCESSION-WITH-DASHES-index-headers.html` | The acceptance time as the header gives it ([SRC-1]) |

`##########` is the company's CIK in ten digits with leading zeros. In a
header's URL, `CIK` is the company's CIK without them, and `ACCESSION` is
the accession number without its dashes. An accession number can begin
with another filer's CIK, such as a filing agent's ([SRC-2]).

- **CLIENT-15** (rule) A fetch's record goes in the log of the feed its URL
  belongs to, named as in the table.

## 6. The cache

A cache has the store's layout, objects, and records, without the store's
scope and imports:

```text
CACHE/
  feeds/FEED/versions.jsonl     one record per fetch (the store's §6)
  objects/AA/SHA256.gz          one object per distinct body (the store's §5)
  .lock                         held while a process fetches (CACHE-6)
```

- **CACHE-1** (invariant) A cache the library writes holds only the files
  above, apart from the unfinished writes that the store's OBJ-3 allows. Its
  objects and records meet the store's OBJ-1, OBJ-3, and REC-1 to REC-8.
- **CACHE-2** (rule) An object is written as in the store's OBJ-2: to a
  temporary file named `*.tmp` in `objects/`, flushed to disk, then renamed
  into place, or deleted if the path already exists.
- **CACHE-3** (rule) The library only appends records and adds objects. It
  never edits or deletes a record or an object, apart from the `*.tmp`
  files and unnamed objects that the store's OBJ-3 allows to be deleted.
- **CACHE-4** (rule) A record's `tool` is `edgar-asof@` followed by the
  library's version, as `edgar-asof@0.1.0`.
- **CACHE-5** (rule) The library reads a snapshot store's `data/` directory
  as a cache, ignoring its `README.md`, `scope.json`, and `imports/`. It
  never fetches into a directory that holds a `scope.json`, so it can't
  break a store's scope (the store's SCOPE-2).
- **CACHE-6** (rule) A process holds an exclusive lock on the cache's
  `.lock` file while it fetches into the cache, so only one process fetches
  into a cache at a time, as in the store's FETCH-7. Reading takes no lock.
  A reader ignores a log's last line if it doesn't end in a newline, since
  a fetch may still be appending it.
- **CACHE-7** (rule) A URL's versions are the distinct `sha256` values among
  its records, numbered in the order each first appears, as in the store's
  VER-1.
- **CACHE-8** (rule) A read uses the URL's latest version in the cache. It
  fetches only when the cache holds no version of the URL, or when the
  caller asks for a fresh fetch, which is conditional as [CLIENT-5] says.
- **CACHE-9** (rule) The caller names the cache's directory. The library
  has no default.
- **CACHE-10** (rule) A read from a cache raises `CacheError`, which names
  the file, and fetches nothing, when it can't read what it needs: a line
  of the URL's feed log, other than an unfinished last line ([CACHE-6]),
  that isn't a JSON object with a `url` that is a string and a `sha256`
  that is null or 64 lower-case hexadecimal digits; or the object of the
  version it reads, when the object is missing or isn't gzip data whose
  decompressed bytes have that SHA-256 (the store's OBJ-1). A read that
  would send validators ([CLIENT-5]) reads, before it requests anything,
  the object of the version they come from, which a `304` names
  ([CLIENT-16]).

## 7. Where the cache departs from the store

- **No scope.** The store holds a small scope, reviewed before anything is
  fetched, because it is committed to git. A cache holds what its caller
  reads, limited to the feeds in [§5](#5-feeds) ([CLIENT-1]), so it has no
  `scope.json`.
- **No imports.** The store's imports are the pipeline's programs. The
  library's reads aren't imports, and what an answer records about its
  inputs is for the facts specification.
- **The caller supplies the user agent,** where the store's `snapshot.py`
  reads `SEC_USER_AGENT` from the environment or `.env.dev` (the store's
  FETCH-2 and FETCH-15). The library is called from programs the caller
  writes, so the user agent is an argument, and the library reads none from
  the environment ([CLIENT-2]).
- **A failure is an error to the caller** ([READ-6]), not a run's exit
  status (the store's FETCH-10), and a `403` stops the process's requests,
  not a run (the store's FETCH-9).
- **The library also reads bodies the caller gives,** where the store's
  programs read only what its writers fetched. `edgar-data-pipeline`'s
  services give the library bodies from their store, and never use its
  client or keep a cache (FETCH-18 in the store's version 1.0.0), so a
  read from them fetches and writes nothing ([READ-2]).
- **The library enforces one process at a time** with a lock ([CACHE-6]),
  where the store leaves it to the operator (the store's FETCH-7).
- **A cache's history isn't in git,** so keeping it unchanged is a rule the
  library follows ([CACHE-3]), not an invariant checked against an earlier
  commit (the store's LOG-1 and LOG-2).
- **`tool` names the library and its version** ([CACHE-4]), not a script
  and its commit.

## 8. Functions and types

The package `edgar_asof` gives a caller the function and types below for
reading a body. [`facts.md`](facts.md#8-functions-and-types) uses a
source, and a body's URL and `sha256`, by these names ([FACT-2],
[FACT-5]).

| Name | Kind | Parameters or fields |
| --- | --- | --- |
| `read_body(url, source, *, fresh=False)` | Function | Reads a URL's body and returns its `Body`. `url` is a `str`, a URL of a feed in [§5](#5-feeds) ([CLIENT-1]); `source` is where the body comes from; and `fresh` asks for a fresh fetch ([CACHE-8]). |
| `Source` | Type alias | `Cache` or `Bodies`: where a read takes its body. |
| `Cache(directory, *, user_agent=None)` | Type | A cache, as a source. `directory`, a `pathlib.Path`, from the `str` or `os.PathLike` passed ([CACHE-9]); and `user_agent`, a `str` or `None`, which each fetch into the cache sends as its `User-Agent` ([CLIENT-2]). Without one, a read that would fetch fails ([READ-6]), so a snapshot store, which is never fetched into, can be read without one ([CACHE-5]). |
| `Bodies(bodies)` | Type | Bodies the caller gives, as a source. `bodies`, a read-only mapping of each URL, a `str`, to its body, `bytes`, after any `Content-Encoding` is removed ([§2](#2-terms)), copied from the mapping passed. |
| `Body` | Type | `url`, a `str`; `sha256`, a `str` of 64 lower-case hexadecimal digits; and `content`, the body, `bytes` ([READ-3]). |
| `BodyRef` | Type | `url` and `sha256`, as a `Body` has them, without its content: how `CompanyFacts.inputs` names each body ([FACT-5]). |
| `ReadError` | Exception | A read that fails. `url`, the URL read. Each error below is a `ReadError`. |
| `BodyNotGivenError` | Exception | `Bodies` that hold no body for the URL ([READ-2]). |
| `CacheError` | Exception | A cache that a read can't read ([CACHE-10]). `path`, the file it couldn't read, a `pathlib.Path`. |
| `ForbiddenError` | Exception | A `403`, received by the read's fetch or by an earlier one in the process ([CLIENT-9], [READ-6]). |
| `SnapshotStoreError` | Exception | A read that would fetch into a snapshot store ([CACHE-5], [READ-6]). |
| `NoUserAgentError` | Exception | A read that would fetch into a cache without a user agent ([CLIENT-2], [READ-6]). |
| `FetchError` | Exception | A fetch whose record names no body ([READ-6]). `status`, an `int` or `None`, and `error`, a `str` or `None`, as the record has them. |

- **READ-1** (rule) The package `edgar_asof` gives the function and types
  in the table, with their parameters and fields. Each of its errors is a
  `ReadError`, which names the URL read. Each other type is immutable, a
  `BodyRef` is hashable, and equal to another with the same fields, and a
  `Cache`'s `repr` doesn't show its user agent.
- **READ-2** (rule) A read from `Bodies` requests nothing and writes
  nothing. It takes the body given for its URL, and raises
  `BodyNotGivenError` if none was given.
- **READ-3** (rule) A read returns a `Body`: its URL, the body, and the
  body's SHA-256. From a cache, without a fetch, the body is the URL's
  latest version ([CACHE-8]): the one that the URL's latest record with a
  `sha256` names, as [CLIENT-5] takes its validators from that record.
  From `Bodies`, it's the body given for the URL, unchanged.
- **READ-4** (rule) An argument this document refuses raises `ValueError`
  before anything is read: a URL that [CLIENT-1] doesn't allow, given to
  `read_body` or held by `Bodies`; a user agent that doesn't contain an
  `@` ([CLIENT-2]); and a fresh read from `Bodies`, which can't fetch.
- **READ-5** (rule) A read from a cache that fetches ([CACHE-8]) makes the
  cache's directory, with its parents, if it doesn't exist; waits while
  another process holds the cache's lock ([CACHE-6]); and then fetches
  only if CACHE-8 still calls for it, since that process may have fetched
  the URL. It returns the body that its fetch's record names: the body
  received with a `200`, or the version that a `304` names ([CLIENT-16]).
- **READ-6** (rule) A read from a cache that would fetch raises, before it
  requests or writes anything, `CacheError` if it can't read what
  [CACHE-10] says it needs; else `ForbiddenError` if a fetch in the
  process has received a `403` ([CLIENT-9]); else `SnapshotStoreError` if
  the cache's directory holds a `scope.json` ([CACHE-5]); else
  `NoUserAgentError` if the cache has no user agent ([CLIENT-2]). A fetch
  that receives a `403` raises `ForbiddenError`, and one whose record
  names no body raises `FetchError`, with the record's `status` and
  `error`: after its last attempt ([CLIENT-8], [CLIENT-13]), for another
  status ([CLIENT-10]), for another encoding ([CLIENT-12]), and for a
  `304` that names nothing ([CLIENT-16]).

## 9. Index

| ID | Kind | Checked by | Statement |
| --- | --- | --- | --- |
| CLIENT-1 | rule | tests | Only `https` URLs of the library's feeds on `www.sec.gov` and `data.sec.gov`. |
| CLIENT-2 | rule | tests | The caller's user agent is required and sent; none is read from the environment. |
| CLIENT-3 | rule | tests | No request header is kept in a cache. |
| CLIENT-4 | rule | tests | `Accept-Encoding: gzip` is sent. |
| CLIENT-5 | rule | tests | The latest version's validators are sent. |
| CLIENT-6 | rule | tests | An attempt times out after 60 seconds. |
| CLIENT-7 | rule | tests | Requests from a process start at least 0.2 seconds apart. |
| CLIENT-8 | rule | tests | Temporary failures are retried, up to 4 attempts, with capped waits. |
| CLIENT-9 | rule | tests | A `403` is recorded, fails the read, and stops the process's requests. |
| CLIENT-10 | rule | tests | Other statuses but `200` and `304` aren't retried, and fail the read. |
| CLIENT-16 | rule | tests | A `304` returns the version it names, and fails the read if it names none. |
| CLIENT-11 | rule | tests | gzip encodings are decoded before hashing. |
| CLIENT-12 | rule | tests | Other encodings are recorded and not stored. |
| CLIENT-13 | rule | tests | A body cut short stores nothing and is retried. |
| CLIENT-14 | rule | tests | Each fetch appends one record, after its object. |
| CLIENT-15 | rule | tests | A record goes in its feed's log. |
| CACHE-1 | invariant | tests | A cache has the store's layout, objects, and records, without scope or imports. |
| CACHE-2 | rule | tests | Objects are written to `*.tmp`, flushed, and renamed; never replaced. |
| CACHE-3 | rule | tests | Records are only appended and objects only added. |
| CACHE-4 | rule | tests | `tool` is the library and its version. |
| CACHE-5 | rule | tests | A snapshot store is read as a cache, and never fetched into. |
| CACHE-6 | rule | tests | One process fetches into a cache at a time; readers skip an unfinished line. |
| CACHE-7 | rule | tests | Versions are distinct bodies per URL, numbered by first appearance. |
| CACHE-8 | rule | tests | A read uses the latest cached version, and fetches only when there is none or the caller asks. |
| CACHE-9 | rule | tests | The caller names the cache's directory; there is no default. |
| CACHE-10 | rule | tests | A cache a read can't read raises `CacheError`, and nothing is fetched. |
| READ-1 | rule | tests | The package gives §8's function and types; all but the errors are immutable. |
| READ-2 | rule | tests | A read from given bodies requests and writes nothing, and fails on a URL not given. |
| READ-3 | rule | tests | A read returns the URL, the body, and its SHA-256: the latest cached version, or the body given. |
| READ-4 | rule | tests | Refused arguments raise `ValueError` before anything is read. |
| READ-5 | rule | tests | A read that fetches makes the directory, waits for the lock, and returns the body its record names. |
| READ-6 | rule | tests | A read that can't fetch, or whose fetch names no body, raises its error. |

## 10. Open questions

None.

## 11. Changes to this document

Versions follow semantic versioning. Adding a statement, an optional field,
or a check is a minor version. Changing the meaning of a statement, the
cache's layout, or a guarantee is a major version, and must say how a cache
written under the earlier version is read. IDs are never reused, and a
retired statement stays in the index.

### Reading a cache written under version 0.1.0

Version 1.0.0 changes no file of a cache: its layout, objects, and records
are as version 0.1.0 had them, so a cache written under that version is a
cache under this one, and nothing in it is rewritten. What changed is how
the library reads:

- **A `304` returns the version it names** ([CLIENT-16]), where
  [CLIENT-10] failed the read on it.
- **A read can take its body from the caller** ([READ-2]), so the first
  guarantee holds for a body read from a cache, and the seventh for a body
  the caller gives.
- **A read checks the object it reads** against its SHA-256, and fails on
  a log or an object it can't read ([CACHE-10]).

[0009]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/docs/decisions/0009-read-edgar-through-a-public-point-in-time-library.md
[store]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/spec/snapshots.md
[SRC-1]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-2]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-4]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-9]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-10]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[FACT-2]: facts.md#4-reading-a-companys-facts
[FACT-5]: facts.md#4-reading-a-companys-facts
[CLIENT-1]: #4-requests
[CLIENT-2]: #4-requests
[CLIENT-3]: #4-requests
[CLIENT-5]: #4-requests
[CLIENT-7]: #4-requests
[CLIENT-8]: #4-requests
[CLIENT-9]: #4-requests
[CLIENT-10]: #4-requests
[CLIENT-12]: #4-requests
[CLIENT-13]: #4-requests
[CLIENT-14]: #4-requests
[CLIENT-16]: #4-requests
[CACHE-1]: #6-the-cache
[CACHE-2]: #6-the-cache
[CACHE-3]: #6-the-cache
[CACHE-4]: #6-the-cache
[CACHE-5]: #6-the-cache
[CACHE-6]: #6-the-cache
[CACHE-7]: #6-the-cache
[CACHE-8]: #6-the-cache
[CACHE-9]: #6-the-cache
[CACHE-10]: #6-the-cache
[READ-2]: #8-functions-and-types
[READ-3]: #8-functions-and-types
[READ-5]: #8-functions-and-types
[READ-6]: #8-functions-and-types
