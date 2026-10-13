# Plan: edgar-asof

**Status:** October 13, 2026. No task is done yet. The next is T1, the
facts specification.

The tasks that build `edgar-asof`, in the order they're to be done, and
which are done. When the owner asks for the next item, an agent takes the
first task that isn't done, isn't taken, and is ready to start, as
[`AGENTS.md`](../AGENTS.md#doing-the-next-item) says. The plan makes no
rules: each task names the documents that govern it. Data read by this
library comes from the U.S. Securities and Exchange Commission's EDGAR
system.

## How the plan works

- **Each task is one pull request,** whose title ends with the task's ID.
  IDs run from T1 and are never reused or renumbered; a task split later
  gets new IDs.
- **IDs are this repository's.** `edgar-data-pipeline`'s plan numbers its
  tasks the same way, so a task of that repository is always named as its,
  such as `edgar-data-pipeline`'s T12.
- **The order is the rows' order,** through the sections in turn. A task
  that moves keeps its ID, so IDs needn't be in order.
- **A task is ready when what it depends on is done.** "Owner" means the
  owner asks for the task when it's time. A task of `edgar-data-pipeline`
  is done when that repository's plan marks it done, and a finding there
  can be cited once it's on that repository's `main`.
- **A task's pull request marks it done,** with the date in its row, and
  names the next task in the status line.
- **`edgar-data-pipeline` waits on releases, not tasks.** Its plan names
  the `edgar-asof` release each of its tasks needs, such as its T24, which
  reads `submissions` and headers through the first release.
- **The owner adds, removes, and reorders tasks.**

## The first release

Version 0.1.0 reads `companyfacts` and joins each value to the acceptance
time of the filing that reported it, through `submissions`, as
`edgar-data-pipeline`'s decision [0009] gives for the first release. Each
specification is its own pull request, versioned as its document says.
Each building task builds what its specifications say, with tests that
carry their IDs.

| ID | Task | Depends on | Done |
| --- | --- | --- | --- |
| T1 | **Facts, `spec/facts.md`.** The fact model and what "as of T" returns, which [0009] gives this library to define. Each `companyfacts` value with its concept, unit, and period, joined by its `accn` to its filing in `submissions`, the further files among them, and so to its raw acceptance times ([SRC-6] to [SRC-12]). Each filing's value for a key, kept beside the others, whether it repeats or restates them, amendments among them ([SRC-14] to [SRC-17]). For a concept and a period, the value known at T, through the caller's interpreter ([TIME-9]), and the values later filings reported for it. It also says what an answer records about its inputs, which [`fetching.md`](../spec/fetching.md#7-where-the-cache-departs-from-the-store) leaves to it, and the functions and types a caller uses for facts. It refers to raw times, instants, interpreters, and a read's arguments by their statements ([TIME-3], [TIME-6], [CLIENT-2], [CACHE-9]), and leaves their names to T2 and T3. | — | |
| T2 | **The interface of fetching, a minor version of [`spec/fetching.md`](../spec/fetching.md).** The functions and types a caller uses: reading with a user agent and a cache directory ([CLIENT-2], [CACHE-9]), a fresh fetch ([CACHE-8]), and the errors a read raises ([CLIENT-9], [CLIENT-10]). Named to agree with T1's, so that the building tasks don't choose what the specifications leave open ([`AGENTS.md`](../AGENTS.md#doing-the-next-item), step 7). It also lets a statement's tests wait for the later task in this plan that writes them, in [§3](../spec/fetching.md#3-statement-ids), which [`times.md`](../spec/times.md#2-statement-ids) follows, and in [`AGENTS.md`'s rule on tests](../AGENTS.md#rules), as `edgar-data-pipeline`'s [`spec/snapshots.md`][store-ids] and `AGENTS.md` do. | T1 | |
| T3 | **The interface of acceptance times, a minor version of [`spec/times.md`](../spec/times.md).** The types of raw times and instants, an interpreter's signature, and the two interpreters a caller passes ([TIME-6] to [TIME-8]), named to agree with T1's and T2's. | T2 | |
| T4 | **The project.** The `uv` project for the `edgar-asof` package, with a format check, a lint, a type check, and tests, run on each pull request, as `edgar-data-pipeline` has. Tests carry the `spec` marker, and a guard fails any test that reaches the network ([`AGENTS.md`](../AGENTS.md#rules)). `tests/test_spec_coverage.py` fails if a statement in an index has no test, unless a later task here writes it, as T2 allows, or if a marker names no statement, as `edgar-data-pipeline`'s does. It fills in [`AGENTS.md`'s commands](../AGENTS.md#commands). | T2 | |
| T5 | **The cache.** [CACHE-1] to [CACHE-9], tested on temporary directories, and on stored versions laid out as a snapshot store ([CACHE-5]). | T2, T4 | |
| T6 | **The client.** [CLIENT-1] to [CLIENT-15], tested against a local server that stands in for EDGAR. | T5 | |
| T7 | **Acceptance times.** [TIME-1] to [TIME-9]: raw times from cached headers and `submissions`, and the two interpreters. | T3, T5 | |
| T8 | **Facts.** `spec/facts.md`'s statements, from cached `companyfacts` and `submissions`. | T1, T7 | |
| T9 | **Release 0.1.0.** The package's metadata, the README's account of how to use it, and its publication on PyPI as `edgar-asof`. The PyPI account, and how releases are published to it, are the owner's. | T6, T8, owner | |

## Later

After the first release, so each task here waits for T9.

| ID | Task | Depends on | Done |
| --- | --- | --- | --- |
| T10 | **Published cases for "as of T".** Cases with their inputs and answers, published with the library, so that `edgar-data-pipeline`'s query API is tested against them and both answer the same way ([0009], its T26). Split, when it's next, into a minor version of `spec/facts.md`, a building task, and a release that publishes them, which `edgar-data-pipeline`'s T26 waits on. | T9 | |
| T11 | **XBRL instances.** Every fact a filing reports, read from its XBRL instance with the parser that `edgar-data-pipeline`'s T12 chooses, as [0009] gives for after the first release. Split, when it's next, into its specification, its building tasks, and a release that publishes them, which `edgar-data-pipeline`'s T25 waits on. | T9, `edgar-data-pipeline`'s T12, owner | |
| T12 | **A default interpreter.** Whether the header's digits read as Eastern Time become the default, in a minor version of `spec/times.md` ([TIME-8], [TIME-9]). | T9, and a finding in `edgar-data-pipeline` that compares more headers with `submissions` than [SRC-2] and [SRC-13] do | |

[0009]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/docs/decisions/0009-read-edgar-through-a-public-point-in-time-library.md
[store-ids]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/spec/snapshots.md#3-statement-ids
[SRC-2]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-6]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-12]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-13]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-14]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[SRC-17]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[CLIENT-1]: ../spec/fetching.md#4-requests
[CLIENT-2]: ../spec/fetching.md#4-requests
[CLIENT-9]: ../spec/fetching.md#4-requests
[CLIENT-10]: ../spec/fetching.md#4-requests
[CLIENT-15]: ../spec/fetching.md#5-feeds
[CACHE-1]: ../spec/fetching.md#6-the-cache
[CACHE-5]: ../spec/fetching.md#6-the-cache
[CACHE-8]: ../spec/fetching.md#6-the-cache
[CACHE-9]: ../spec/fetching.md#6-the-cache
[TIME-1]: ../spec/times.md#3-raw-times
[TIME-3]: ../spec/times.md#3-raw-times
[TIME-6]: ../spec/times.md#4-interpreters
[TIME-8]: ../spec/times.md#4-interpreters
[TIME-9]: ../spec/times.md#4-interpreters
