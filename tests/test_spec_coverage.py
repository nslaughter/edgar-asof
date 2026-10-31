"""Every spec/*.md's statements and the tests that check them.

Every statement appears in its specification's index with its kind, once,
checked by tests, as fetching.md's §3 says; each ID area belongs to one
specification; every statement has a test marked with its ID, unless a
later task in docs/plan.md, not yet done, writes it; and every marker names
a statement in an index. A test is one that pytest collects, with the
markers pytest gives it.
"""

from __future__ import annotations

import functools
import json
import re
import subprocess
import sys
import tempfile
import textwrap
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPECS = {path.name: path.read_text(encoding="utf-8") for path in sorted(ROOT.glob("spec/*.md"))}
INDEX_ROW = re.compile(r"^\| ([A-Z]+-\d+) \| (invariant|rule|retired) \| ([^|]+) \| .+ \|$", re.M)
STATEMENT = re.compile(r"^- \*\*([A-Z]+-\d+)\*\* \((invariant|rule)\)", re.M)
# A task's row in docs/plan.md, with its last column, Done.
PLAN_ROW = re.compile(r"^\| (T\d+) \|.*\|([^|]*)\|$", re.M)
# Statements whose tests a later task in docs/plan.md writes, with that task,
# as the plan's rows give them: T7 acceptance times, and T8 facts. A task
# that writes a statement's tests takes it off this list. Strict, like
# xfail_strict: a statement listed here that has a test fails too, and so
# does one whose task the plan marks done.
AWAITING = {
    **dict.fromkeys(
        [
            "TIME-1",
            "TIME-2",
            "TIME-3",
            "TIME-4",
            "TIME-5",
            "TIME-6",
            "TIME-7",
            "TIME-8",
            "TIME-10",
            "TIME-11",
            "TIME-12",
            "TIME-15",
        ],
        "T7",
    ),
    **dict.fromkeys(
        [
            "FACT-1",
            "FACT-2",
            "FACT-3",
            "FACT-4",
            "FACT-5",
            "FACT-6",
            "FACT-7",
            "FACT-8",
            "FACT-9",
            "FACT-10",
            "FACT-11",
            "FACT-12",
            "FACT-13",
            "FACT-14",
            "ASOF-1",
            "ASOF-2",
            "ASOF-3",
            "ASOF-4",
            "ASOF-5",
            "ASOF-6",
            "TIME-9",
            "TIME-13",
            "TIME-14",
        ],
        "T8",
    ),
}


def spec_index(spec: str) -> list[tuple[str, str, str]]:
    """A specification's index: each row's ID, kind, and Checked by."""
    return [(id, kind, checked.strip()) for id, kind, checked in INDEX_ROW.findall(spec)]


def index() -> dict[str, str]:
    """Every specification's index as one, each ID with its kind."""
    return {id: kind for spec in SPECS.values() for id, kind, _ in spec_index(spec)}


def statements() -> list[str]:
    """Every statement in an index that isn't retired, which tests check."""
    return [id for id, kind in index().items() if kind != "retired"]


def area(id: str) -> str:
    return id.rsplit("-", 1)[0]


def repeated(ids: list[str]) -> list[str]:
    return sorted(id for id, count in Counter(ids).items() if count > 1)


@functools.cache
def markers(tests: Path = ROOT / "tests") -> dict[str, list[str]]:
    """Each ID that a `spec` marker names, with the tests that carry it.

    The tests are those that pytest collects from a directory, with this
    repository's configuration, in a process of its own. So a definition
    that pytest doesn't collect, such as a class whose name doesn't start
    with `Test`, isn't a test, and a marker counts wherever pytest reads it,
    such as in `pytestmark` or a `pytest.param`.
    """
    with tempfile.TemporaryDirectory() as scratch:
        output = Path(scratch) / "markers.json"
        collection = subprocess.run(
            [sys.executable, __file__, str(tests), str(output)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert collection.returncode == 0, collection.stdout + collection.stderr
        found: dict[str, list[str]] = json.loads(output.read_text(encoding="utf-8"))
    return found


class Markers:
    """A pytest plugin that keeps the IDs of the tests a collection finds.

    An ID that isn't a string is kept as its `repr`, which names no
    statement.
    """

    def __init__(self) -> None:
        self.found: dict[str, list[str]] = {}

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        for item in session.items:
            for marker in item.iter_markers("spec"):
                for id in marker.args:
                    key = id if isinstance(id, str) else repr(id)
                    self.found.setdefault(key, []).append(item.nodeid)


def collect(tests: str, output: str) -> int | pytest.ExitCode:
    """Collect a directory's tests, without running them, and write their IDs."""
    plugin = Markers()
    code = pytest.main(
        [
            "--collect-only",
            "--quiet",
            "-p",
            "no:cacheprovider",
            "-c",
            str(ROOT / "pyproject.toml"),
            tests,
        ],
        plugins=[plugin],
    )
    Path(output).write_text(json.dumps(plugin.found), encoding="utf-8")
    return code


def plan_tasks() -> dict[str, str]:
    """Each task in docs/plan.md, with what its Done column says."""
    plan = (ROOT / "docs" / "plan.md").read_text(encoding="utf-8")
    return {task: done.strip() for task, done in PLAN_ROW.findall(plan)}


def test_every_statement_is_in_its_specs_index_once_with_its_kind() -> None:
    for name, spec in SPECS.items():
        stated = STATEMENT.findall(spec)
        rows = spec_index(spec)
        indexed = {id: kind for id, kind, _ in rows if kind != "retired"}

        assert repeated([id for id, _ in stated]) == [], name
        assert repeated([id for id, _, _ in rows]) == [], name
        assert dict(stated) == indexed, name


def test_every_statement_is_checked_by_tests() -> None:
    checked = {id: by for spec in SPECS.values() for id, kind, by in spec_index(spec)}

    assert {id: checked[id] for id in statements() if checked[id] != "tests"} == {}


def test_each_id_area_belongs_to_one_spec() -> None:
    owners: dict[str, set[str]] = {}
    for name, spec in SPECS.items():
        for id, _, _ in spec_index(spec):
            owners.setdefault(area(id), set()).add(name)

    assert {a: names for a, names in owners.items() if len(names) > 1} == {}


def test_every_statement_has_a_test() -> None:
    marked = markers()

    assert [id for id in statements() if id not in marked and id not in AWAITING] == []


def test_a_statement_awaits_its_test_only_until_the_test_exists() -> None:
    marked = markers()

    assert sorted(set(AWAITING) - set(statements())) == []
    assert sorted(id for id in AWAITING if id in marked) == []


def test_a_statement_awaits_only_a_task_the_plan_has_not_done() -> None:
    not_done = {task for task, done in plan_tasks().items() if not done}

    assert sorted(set(AWAITING.values()) - not_done) == []


def test_every_marker_names_a_statement() -> None:
    assert sorted(set(markers()) - set(index())) == []


def test_a_marker_counts_on_a_test_that_pytest_collects(tmp_path: Path) -> None:
    (tmp_path / "test_module.py").write_text(
        textwrap.dedent(
            """
            import pytest

            pytestmark = pytest.mark.spec("EXAMPLE-1")

            def test_module():
                pass
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "test_forms.py").write_text(
        textwrap.dedent(
            """
            import pytest
            from pytest import mark

            @mark.spec("EXAMPLE-2")
            def test_mark():
                pass

            @pytest.mark.parametrize("n", [pytest.param(1, marks=pytest.mark.spec("EXAMPLE-3"))])
            def test_param(n):
                pass

            @pytest.mark.spec("EXAMPLE-4")
            class TestClass:
                def test_method(self):
                    pass

            # Not tests: pytest collects neither.
            @pytest.mark.spec("EXAMPLE-5")
            class ExampleTests:
                def test_method(self):
                    pass

            @pytest.mark.spec("EXAMPLE-6")
            def example():
                pass
            """
        ),
        encoding="utf-8",
    )

    found = {
        id: [test.split("::", 1)[1] for test in tests] for id, tests in markers(tmp_path).items()
    }

    assert found == {
        "EXAMPLE-1": ["test_module"],
        "EXAMPLE-2": ["test_mark"],
        "EXAMPLE-3": ["test_param[1]"],
        "EXAMPLE-4": ["TestClass::test_method"],
    }


def test_an_id_that_isnt_a_string_names_no_statement(tmp_path: Path) -> None:
    (tmp_path / "test_number.py").write_text(
        textwrap.dedent(
            """
            import pytest

            @pytest.mark.spec(5)
            def test_number():
                pass
            """
        ),
        encoding="utf-8",
    )

    assert list(markers(tmp_path)) == ["5"]


if __name__ == "__main__":
    # How markers() collects a directory's tests: `python
    # tests/test_spec_coverage.py DIRECTORY OUTPUT`.
    sys.exit(collect(*sys.argv[1:]))
