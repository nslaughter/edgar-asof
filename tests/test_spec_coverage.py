"""Every spec/*.md's statements and the tests that check them.

Every statement appears in its specification's index with its kind, once,
checked by tests, as fetching.md's §3 says; each ID area belongs to one
specification; every statement has a test marked with its ID, unless a
later task in docs/plan.md, not yet done, writes it; and every marker names
a statement in an index.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS = {path.name: path.read_text(encoding="utf-8") for path in sorted(ROOT.glob("spec/*.md"))}
INDEX_ROW = re.compile(r"^\| ([A-Z]+-\d+) \| (invariant|rule|retired) \| ([^|]+) \| .+ \|$", re.M)
STATEMENT = re.compile(r"^- \*\*([A-Z]+-\d+)\*\* \((invariant|rule)\)", re.M)
# A task's row in docs/plan.md, with its last column, Done.
PLAN_ROW = re.compile(r"^\| (T\d+) \|.*\|([^|]*)\|$", re.M)
# Statements whose tests a later task in docs/plan.md writes, with that task,
# as the plan's rows give them: T5 the cache, T6 the client, T7 acceptance
# times, and T8 facts. A task that writes a statement's tests takes it off
# this list. Strict, like xfail_strict: a statement listed here that has a
# test fails too, and so does one whose task the plan marks done.
AWAITING = {
    **dict.fromkeys(
        [
            "CACHE-1",
            "CACHE-2",
            "CACHE-3",
            "CACHE-4",
            "CACHE-5",
            "CACHE-6",
            "CACHE-7",
            "CACHE-9",
            "CACHE-10",
            "READ-1",
            "READ-2",
            "READ-3",
            "READ-4",
        ],
        "T5",
    ),
    **dict.fromkeys(
        [
            "CLIENT-1",
            "CLIENT-2",
            "CLIENT-3",
            "CLIENT-4",
            "CLIENT-5",
            "CLIENT-6",
            "CLIENT-7",
            "CLIENT-8",
            "CLIENT-9",
            "CLIENT-10",
            "CLIENT-11",
            "CLIENT-12",
            "CLIENT-13",
            "CLIENT-14",
            "CLIENT-15",
            "CLIENT-16",
            "CACHE-8",
            "READ-5",
            "READ-6",
        ],
        "T6",
    ),
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
            "TIME-9",
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


def markers() -> dict[str, list[str]]:
    """Each ID named by @pytest.mark.spec(...), with the tests that carry it."""
    found: dict[str, list[str]] = {}
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "spec"
                    and isinstance(decorator.func.value, ast.Attribute)
                    and decorator.func.value.attr == "mark"
                ):
                    for arg in decorator.args:
                        assert isinstance(arg, ast.Constant)
                        assert isinstance(arg.value, str)
                        found.setdefault(arg.value, []).append(node.name)
    return found


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
