# Working in this repository

This repository holds `edgar-asof`, a Python library, to be released on
PyPI as `edgar-asof`, that answers what a company reported to the SEC as it
was known at a past time. `edgar-data-pipeline`'s decision [0009] records
why the library exists and what it does. For now the repository holds the
library's first specifications, and the code follows them.

It follows `edgar-data-pipeline`'s conventions, as the owner chose on
October 10, 2026, and that repository's [`AGENTS.md`][pipeline-agents] is
the model for this one.

## Read these first

| Document | Governs |
| --- | --- |
| [`spec/fetching.md`](spec/fetching.md) | How the library requests EDGAR's feeds, and its cache, as numbered statements with an index. |
| [`spec/times.md`](spec/times.md) | Filings' acceptance times, as EDGAR gives them and as instants. |
| `edgar-data-pipeline`'s [findings] | Nothing here. They record what EDGAR's feeds do, each finding with an ID from `SRC-1` onward and the stored versions that show it. This repository's specifications depend on EDGAR only through these findings. |
| `edgar-data-pipeline`'s [`spec/snapshots.md`][store] | Nothing here. It specifies the snapshot store, which the cache follows. |

## Where documents go

Each document makes one kind of claim, and its directory says which.

```text
spec/                    normative: numbered statements that code and tests cite
  fetching.md            requests and the cache
  times.md               acceptance times
  NAME.md                one per component, or boundary between components
docs/
  decisions/NNNN-*.md    one record per significant choice
  plan.md                the tasks, in order, and which are done
```

- **A rule the code must follow goes in `spec/`,** where a test checks it.
  An explanation of why goes in `docs/`. What EDGAR does goes in
  `edgar-data-pipeline`'s investigation, in a pull request there. The
  README describes the library for people and is none of these.
- **One spec per component or boundary, not one per kind of content.** A
  component's behavior and its interface change together, so they share a
  document and a version.
- **Each spec has its own version,** as its document says.
  `edgar-data-pipeline` cites a version of these specifications, so a
  change that alters a statement's meaning is a major version.
- **ID areas here aren't `edgar-data-pipeline`'s,** such as `CLIENT` and
  `CACHE` beside its `FETCH` and `REC`, so an ID names one statement across
  both repositories. A statement that follows one of that repository's
  statements cites it as the store's, such as "the store's FETCH-6".
- **Specs depend on EDGAR only through findings.** A statement that relies
  on how the source behaves cites the finding's `SRC` ID, linked. Code and
  tests cite spec IDs, not findings.
- **A significant choice gets a decision record,**
  `docs/decisions/NNNN-title.md`, numbered from 0001, with the context, the
  options, the choice, and its consequences. A later record supersedes an
  earlier one instead of editing it.
- **Never move or rename a spec.** `edgar-data-pipeline` and the commits on
  `main` link to its path.

## Rules

- **The specification comes first.** If code and a specification disagree,
  investigate the code first. If you conclude the specification is wrong,
  ambiguous, or contradicts itself, stop and report it, quoting the
  passages, instead of choosing an interpretation. A change to a
  specification is its own pull request, versioned as the document says.
- **Every statement has an ID, and its tests carry it.** Mark each test with
  the IDs it checks, as `@pytest.mark.spec("CLIENT-5")`. A new statement
  gets the next unused number in its area, and IDs are never reused or
  renumbered. The first code adds a test that fails if a statement in an
  index has no test, or a marker names no statement, as
  `edgar-data-pipeline`'s `tests/test_spec_coverage.py` does.
- **Don't build undocumented source behavior into code.** If EDGAR does
  something no finding records, report it. The finding is recorded in
  `edgar-data-pipeline`.
- **Tests never reach the network.** They use a local server or stored
  versions, such as a snapshot store read as a cache
  ([CACHE-5](spec/fetching.md#6-the-cache)).
- **Send requests to the SEC only when the owner asks for that run.** Never
  put a user agent in code, tests, records, commits, or pull requests.
- **Cite the source.** Data read by this library comes from the U.S.
  Securities and Exchange Commission's EDGAR system; say so wherever it is
  published or described.
- **Nothing outside this repository** unless the owner asks: no issues,
  comments, or messages to other projects. A finding the library needs is
  proposed to `edgar-data-pipeline` when the owner asks for it.

## Commands

None yet. The first code sets up the project with `uv`, with a format
check, a lint, a type check, and tests, as `edgar-data-pipeline` has.

## Commits and pull requests

Write commit subjects as short imperative sentences in sentence case, with
a body that says what changed and why. Commit each logical change
separately. A pull request's description lists what changed, the checks
run with their results, and anything deferred.

[0009]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/docs/decisions/0009-read-edgar-through-a-public-point-in-time-library.md
[pipeline-agents]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/AGENTS.md
[findings]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[store]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/spec/snapshots.md
