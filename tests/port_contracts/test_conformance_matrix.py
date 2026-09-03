"""The matrix's own invariants — ADR-001 decision 2.

> **What a green run here proves, and what it does not.** Every adapter in
> `REGISTERED_ADAPTERS` today is an in-memory reference written *against these
> tests*. A green suite therefore proves that the six port Protocols are
> **expressible** — that some object can satisfy each of them, and that the
> contracts are self-consistent enough to be satisfied at all. It proves
> **nothing whatsoever** about Docling, vLLM, pgvector or any other real
> backend, none of which exist in this repository. NFR-04 says the six swap
> points must be *swappable*; nothing has ever been swapped.
> `test_every_registered_adapter_is_an_in_memory_reference` is the executable
> form of that sentence, so the claim goes red rather than stale on the day a
> real backend is registered.

The companion file `test_port_contracts.py` holds the behavioural contracts.
This one holds the invariants of the declaration mechanism itself: that every
port is covered, that every capability is either declared or explained, and that
an adapter cannot quietly omit one. ADR-001's phrasing is the requirement —
an unimplemented capability must be "**declared, not silently absent**" — and a
declaration mechanism nothing checks is exactly a silent absence with extra
steps.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

from procurement_agent import ports
from procurement_agent.adapters import (
    CAPABILITIES_BY_PORT,
    REGISTERED_ADAPTERS,
    UNEXPRESSIBLE_BOUNDING_BOXES,
    UNXFAILABLE,
    AbsenceKind,
    AdapterEntry,
    Capability,
    adapters_for,
)

THE_SIX_PORTS = (
    ports.ParserPort,
    ports.OCRPort,
    ports.EmbedderPort,
    ports.VectorStorePort,
    ports.RerankerPort,
    ports.LLMPort,
)


def test_the_matrix_covers_every_swap_point_ports_declares() -> None:
    """NFR-04 names six swap points, and a seventh must not arrive uncovered.

    The literal tuple above pins the count the requirement states. The derived
    set below is what makes the test bite in the direction that matters: a new
    `@runtime_checkable` Protocol added to `ports` with no row in
    `CAPABILITIES_BY_PORT` fails here, rather than being discovered when someone
    writes its first adapter and finds no contract to write it against.

    `_is_runtime_protocol` is private, and is used because 3.12 ships no public
    equivalent — `typing.is_protocol` landed in 3.13 and `pyproject.toml` still
    supports 3.12. The discriminator is the right one on the merits, not merely
    the available one: `ParsedElement` and `RetrievedChunk` are data shapes that
    travel *through* the ports, not swap points, and the decorator is precisely
    what separates the two groups in `ports/__init__.py`.
    """
    assert set(CAPABILITIES_BY_PORT) == set(THE_SIX_PORTS)

    exported_swap_points = {
        obj
        for name in ports.__all__
        if isinstance(obj := getattr(ports, name), type)
        and getattr(obj, "_is_runtime_protocol", False)
    }
    assert set(CAPABILITIES_BY_PORT) == exported_swap_points


def test_every_port_has_at_least_one_adapter_under_test() -> None:
    """A port with no entry contributes no evidence and would pass vacuously.

    Every contract test in the companion file is parametrized over
    `adapters_for(port)`. An empty list there is not a failure in pytest — it is
    a *collected nothing*, which reads as green. This is the guard against that,
    and it is the reason the six-port assertion above cannot be the only check.
    """
    for port in CAPABILITIES_BY_PORT:
        assert adapters_for(port), f"{port.__name__} has no registered adapter"


def test_adapter_names_are_unique() -> None:
    """Names are pytest parameter ids, so a collision hides one adapter's results."""
    names = [entry.name for entry in REGISTERED_ADAPTERS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("entry", REGISTERED_ADAPTERS, ids=lambda e: e.name)
def test_every_adapter_accounts_for_every_capability_of_its_port(entry: AdapterEntry) -> None:
    """The partition is exact: declared ∪ absent == applicable, and disjoint.

    This is the whole mechanism in one assertion. ADR-001 adopts predict-rlm's
    pattern so that an unimplemented capability is "declared, not silently
    absent"; without an exactness check an author can support four capabilities,
    say nothing about the fifth, and the fifth's contract test is simply never
    reasoned about. Set equality — not `issubset` — is what turns that omission
    red.

    The disjointness half matters for a different failure: a capability listed in
    both `capabilities` and `absences` makes the gate's behaviour depend on which
    one `cases()` happens to consult first, which is a coin-flip dressed as a
    declaration.
    """
    applicable = CAPABILITIES_BY_PORT[entry.port]
    accounted = entry.capabilities | frozenset(entry.absences)

    assert accounted == applicable, (
        f"{entry.name}: unaccounted {sorted(applicable - accounted)}, "
        f"foreign {sorted(accounted - applicable)}"
    )
    assert not (entry.capabilities & frozenset(entry.absences))


@pytest.mark.parametrize("entry", REGISTERED_ADAPTERS, ids=lambda e: e.name)
def test_an_unxfailable_capability_is_never_declared_absent(entry: AdapterEntry) -> None:
    """Some capabilities are refusals, and a refusal cannot be a roadmap item.

    `ACCESS_FILTERING` is NFR-03/AC-8: an uncleared user must not be able to
    influence a retrieved result. `INSUFFICIENT_EVIDENCE` is FR-RAG-04: the model
    must be able to say it does not know instead of inventing a value. An adapter
    that xfails either of those is not an adapter with a gap — it is a security
    or provenance defect that the matrix would otherwise let a reason string
    excuse. Reasons are for capabilities; these two are admission criteria.
    """
    excused = UNXFAILABLE & frozenset(entry.absences)
    assert not excused, f"{entry.name} declares {sorted(excused)} absent; that is not excusable"


@pytest.mark.parametrize("entry", REGISTERED_ADAPTERS, ids=lambda e: e.name)
def test_every_absence_carries_a_reason_a_reader_can_act_on(entry: AdapterEntry) -> None:
    """A reason of "TODO" restores the silent absence the declaration replaced.

    The length floor is crude and deliberate: it is a check against the empty
    string and the one-word shrug, not an attempt to grade prose. What the
    reader needs is which of the two kinds it is — `NOT_APPLICABLE` (the
    capability is meaningless for this backend) or `UNIMPLEMENTED` (it is
    meaningful and missing) — and enough text to tell whether the classification
    is honest.
    """
    for capability, absence in entry.absences.items():
        assert isinstance(absence.kind, AbsenceKind)
        assert len(absence.reason) >= 25, f"{entry.name}/{capability}: reason is a stub"
        assert not any(token in absence.reason.upper() for token in ("TODO", "FIXME", "XXX")), (
            f"{entry.name}/{capability}: placeholder reason"
        )


@pytest.mark.parametrize("entry", REGISTERED_ADAPTERS, ids=lambda e: e.name)
def test_every_adapter_satisfies_its_port_at_runtime(entry: AdapterEntry) -> None:
    """`isinstance` against the Protocol — the weakest check, run for what it is.

    A `runtime_checkable` Protocol checks attribute *presence* and nothing about
    signatures, so this passes for an adapter whose `search()` takes entirely
    different arguments. It is here because it is the check the companion file's
    `cast()` calls rely on, and because it is the one that fires when a method is
    renamed. The signature half is carried by `mypy --strict` over each
    reference's `_conforms()` helper, and the behavioural half by the contract
    tests; no one of the three is sufficient alone.
    """
    assert isinstance(entry.factory(), entry.port)


def test_every_capability_is_claimed_by_at_least_one_port() -> None:
    """The direction a one-way check misses: vocabulary nothing consults.

    `tolerance.py`'s table test checks that every row is a contract key and not
    that every contract key has a row, and `severity.py` records adding the
    second direction for exactly this reason. A `Capability` member absent from
    every port's set is unreachable: no adapter can declare it, no test can gate
    on it, and it reads as coverage while contributing none.
    """
    claimed = frozenset().union(*CAPABILITIES_BY_PORT.values())
    assert claimed == frozenset(Capability), f"unclaimed: {sorted(frozenset(Capability) - claimed)}"


def test_every_registered_adapter_is_an_in_memory_reference() -> None:
    """The honest statement of what this suite is worth, made executable.

    A conformance suite that has only ever run against references written to
    satisfy it is a suite that has tested its author's understanding of the
    contract. That is worth something — it is how the ports get their first
    importing tests, and how a real adapter arrives to a contract rather than
    defining one — but it is not evidence about any backend.

    Written as a test rather than a comment because comments do not fail. The
    day someone registers a real adapter this goes red, and the person holding
    the red test is exactly the person who can update NFR-04's row in
    `docs/requirements-traceability.md` from the evidence they just created.
    """
    assert REGISTERED_ADAPTERS
    assert all(entry.is_reference for entry in REGISTERED_ADAPTERS), (
        "A non-reference adapter is registered. This suite's limitation statement, "
        "and NFR-04's traceability row, both now understate the evidence — update "
        "them from what the new adapter actually proves."
    )


def _reference_sources() -> dict[str, ast.Module]:
    """Each reference module's parsed source, keyed by dotted module name.

    Read from disk and parsed rather than imported and inspected, so the checks
    below read what the file says instead of what a successful import happened to
    resolve — `inspect.getsource` on a class would also miss module-scope imports
    entirely, which is the half that matters most here.
    """
    trees = {}
    for entry in REGISTERED_ADAPTERS:
        module = sys.modules[type(entry.factory()).__module__]
        source = pathlib.Path(str(module.__file__)).read_text(encoding="utf-8")
        trees[module.__name__] = ast.parse(source)
    return trees


def test_the_references_import_nothing_outside_the_standard_library() -> None:
    """A reference with a vendor dependency stops being a reference.

    Two things break at once if one acquires a third-party import. The suite
    stops running in the lean `uv sync --extra dev` environment that CI's
    `checks` job uses, so the conformance matrix would only be verifiable in an
    environment that installs every extra. And the reference stops being a
    control: its job is to show the *contract* is satisfiable, which it can only
    do while nothing in it is doing the real work.
    """
    for name, tree in _reference_sources().items():
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                assert root in sys.stdlib_module_names or root == "procurement_agent", (
                    f"{name} imports {root}, which is neither the standard library nor this package"
                )


SALTED_OR_MOVING = frozenset({"random", "secrets", "time", "datetime", "uuid", "os"})


def test_no_reference_derives_a_value_from_a_salted_or_moving_source() -> None:
    """`DETERMINISTIC_OUTPUT` cannot be checked by running a test twice.

    The contract suite calls each adapter twice in one process and compares. That
    catches accumulated state and it catches an explicit random draw, and it is
    blind to the failure that has actually recurred in this repository: a value
    that is stable within a process and different in the next one. The builtin
    `hash()` on a `str` is salted per `PYTHONHASHSEED`, so an embedder bucketing
    on it passes every in-process determinism assertion and writes vectors that
    disagree between workers — and plan Decision 1 scales by adding worker
    processes, while FR-RAG-05's incremental updates put both generations in one
    index. That is the A-50 question — *could this change without the data
    changing?* — answered wrongly, and `phase-1-execution.md` says to assume a
    fourth instance of the class exists.

    A source scan rather than a subprocess run, following
    `test_severity.py::test_module_source_never_touches_a_clock_random_source_or_
    reviewer_identity`: it needs no adapter to be constructible with no arguments
    in a fresh interpreter, and it names the offending line rather than a
    mismatch between two opaque vectors. It can only be applied to references,
    whose source this repository owns; a real adapter's determinism is a claim
    its own tests have to carry.
    """
    for name, tree in _reference_sources().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "hash", (
                    f"{name} calls the builtin hash(), which is salted per process. "
                    "Use hashlib for anything a stored value depends on."
                )
            roots = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                assert root not in SALTED_OR_MOVING, (
                    f"{name} imports {root}; a reference declaring DETERMINISTIC_OUTPUT "
                    "must not read a clock, a random source or the environment"
                )


def test_fr_ing_04s_bounding_box_clause_is_not_expressible_through_parsedelement() -> None:
    """A named gap in `ports`, pinned so that closing it cannot be silent.

    `OCRPort.recognize`'s own docstring promises to "retain bounding boxes" and
    FR-ING-04 requires them, but `ParsedElement` declares `kind`, `text` and
    `page` and nothing else. Structural typing means an adapter *may* return
    elements carrying a box; it means no consumer may rely on one, so no contract
    test can assert it, so no capability can honestly cover it. The gap is in the
    Protocol, not in the adapters — see `UNEXPRESSIBLE_BOUNDING_BOXES`.

    This asserts the exact member set rather than the box's absence, so that
    *any* change to `ParsedElement` lands here and gets a deliberate answer about
    whether it is a new capability. `ports/` is out of this track's file
    boundary, so the defect is reported rather than fixed; the test is what stops
    it from being reported and then forgotten.
    """
    assert set(ports.ParsedElement.__annotations__) == {"kind", "text", "page"}
    assert "FR-ING-04" in UNEXPRESSIBLE_BOUNDING_BOXES
