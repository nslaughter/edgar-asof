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
| [`docs/plan.md`](docs/plan.md) | Nothing; it orders the work. The tasks that build the library, in order, what each depends on, and which are done. [Doing the next item](#doing-the-next-item) takes the next task from it. |

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
  options, the choice, and its consequences. Its **Status** line says
  Proposed until the owner accepts it, then Accepted, with the date, or
  Superseded by a later record. Once a record merges, only its status
  changes: a later record supersedes it instead of editing it.
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

The owner merges pull requests. Merge one only when the owner explicitly
approves merging that specific pull request in the current conversation.
The repository allows squash merges only, so the pull request's title and
description become the commit on `main`: keep the description current as
commits are added.

No pull request is merged until the owner's iterative review has run on
it, documentation-only ones included, as the owner chose on October 12,
2026. The owner starts the review. Each of its reviews, the third
included, is by a reviewer who didn't write or fix the change and doesn't
share the context of whoever did. It runs in this order:

1. Two reviews at the same time.
2. Fixes: each finding is fixed, or declined with a reason, and answered
   under it on the pull request.
3. A third review of the fixes, when the first two reviews found anything
   of medium or high severity or the fixes changed behavior, tests, or a
   statement's meaning, and only if the fixes pushed a change. Its
   findings are fixed or declined the same way, which ends the review.
   Without a third review, the fixes end it.

Each review is posted on the pull request as a review of its own,
numbered, even when it finds nothing, so the pull request shows which
reviews ran. The owner's approval to merge comes after the review, never
in place of it. If the review hasn't run, or hasn't ended, don't merge,
even when the owner asks: say so, and stop.

## Doing the next item

When the owner asks for the next item, do the next task in the plan,
`docs/plan.md`: one task, in one pull request. The request assigns that
task and nothing beyond it.

1. **Update `main`.** Fetch `origin`, and fast-forward the local `main` to
   `origin/main`. Leave the main checkout on `main`, because other agents
   may share it. If the update changed this file or the plan, read it
   again before going on.
2. **Find the task.** Go through the plan's tasks in order. The next item
   is the first task that is:
   - **not done:** the plan on `main` doesn't mark it done. The plan is
     the progress record, and each task's pull request updates it.
   - **not taken:** no open pull request names its ID in the title
     (`gh pr list --state open`), and no branch names it
     (`git branch --all --list '*/<id>-*'`, with the ID in lowercase). A
     task is taken from the moment step 4 makes its branch.
   - **ready to start:** each task it depends on is done. A specification
     that relies on how EDGAR behaves needs the findings it cites, on
     `edgar-data-pipeline`'s `main`, and code needs its specification. A
     decision record it depends on must be Accepted, as its **Status**
     line says ([where documents go](#where-documents-go)). An approval it
     needs, such as a run against the SEC, is met only when the owner
     gives it in the current conversation.

   Never build on an unmerged branch. A task whose dependency is still in
   an open pull request waits for it to merge.
3. **Stop if nothing can start.** Make no branch and no change. Report
   why, and what would unblock the next task: a pull request to merge, a
   decision record to accept, an approval such as a run against the SEC,
   or a finding `edgar-data-pipeline` still needs. When there is no plan,
   or every task in it is done, the next step is for the owner to write or
   extend it. Stop too when the documents contradict each other on the
   task ([rules](#rules)).
4. **Make a worktree.** Create the branch `<area>/<id>-<short-name>` from
   `origin/main` in a git worktree of its own, outside the main checkout,
   and run `uv sync` in it once the project is set up. `<id>` is the
   task's ID in lowercase, so other agents see that the task is taken
   (step 2). `<area>` is the directory the task mainly changes, such as
   `spec`, `docs`, `src`, or `tests`.
5. **Read for the task.** Follow [read these first](#read-these-first),
   and read closely what the task names: the statements and their tests,
   the findings and the stored versions they cite, and the decision
   records.
6. **Do the task, and only the task.** Keep the [rules](#rules): a change
   to a specification is its own pull request, versioned as its document
   says, and requests go to the SEC only when the owner asks for that run.
   Don't change what a statement or an Accepted decision record says
   beyond what the task asks: that takes the owner's decision, so stop and
   ask. A test of this task's work that the plan assigns to a later task
   may be written now: say in the plan and the pull request that it was
   written ahead of that task.
7. **Record the details you settled.** Where the task left a detail open
   and you decided it, write it where
   [where documents go](#where-documents-go) puts it: a rule as a
   statement in its spec, with the next unused ID in its area, and a
   significant choice as a decision record, whose status is Proposed.
   What EDGAR does isn't recorded here: report it, for a finding in
   `edgar-data-pipeline`. In a code task, a detail the specification
   leaves open is an ambiguity: stop and report it instead
   ([rules](#rules)). List each detail you settled in the pull request for
   the owner to confirm, with the alternative where there was one. Each
   choice you leave for the owner is an open question with a proposed
   default. Only the owner confirms a detail or accepts a decision record.
8. **Update the plan and the status lines.** Mark the task done in the
   plan, with the date, and name the next task. Update the **Status** line
   of each spec the task changed, with its version and the date. When
   another open pull request also edits the plan, the later one to merge
   rebases onto `origin/main` once the other merges: it keeps both tasks'
   entries, and names the next task again.
9. **Verify.** Run the checks in [commands](#commands): the format check,
   the lint, the type check, and the tests, once the first code sets them
   up. Check that each new test fails without the behavior it covers.
   Requests to the SEC wait for the owner. Report only what you ran, with
   its outcome.
10. **Open the pull request.** Commit as
    [commits and pull requests](#commits-and-pull-requests) says. Push the
    branch, and open the pull request with `gh pr create`, under a title
    that ends with the task's ID in parentheses. Its description gives:
    - the task, and the plan it's in, linked;
    - what changed;
    - the details to confirm, linked to where step 7 recorded them, or
      that there are none;
    - the checks run, with their results;
    - any tests written ahead of a later task;
    - anything deferred, and the remaining work.

    Don't merge it: it waits for the owner's iterative review, and then
    the owner's approval
    ([commits and pull requests](#commits-and-pull-requests)).
11. **Report.** Finish with a short handoff: what changed, the evidence,
    the limitations, and the remaining work, with the pull request's link
    and the next task. Name what awaits the owner: the iterative review of
    the pull request, this task's details to confirm, any decision record
    still Proposed, and any approval, such as a run against the SEC.

[0009]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/docs/decisions/0009-read-edgar-through-a-public-point-in-time-library.md
[pipeline-agents]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/AGENTS.md
[findings]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/investigation/edgar.md#findings-so-far
[store]: https://github.com/nslaughter/edgar-data-pipeline/blob/main/spec/snapshots.md
