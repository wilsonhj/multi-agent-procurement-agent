"""Phase 2 Track 0 — the nine additive contract freeze (P2-C1..P2-C9).

Named Verify tests from phase-2-execution.md. Each pin is the thing a later
track compiles against; a silent reshape here is a broken consumer, not a
style change.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from typing import get_type_hints

import pytest

from procurement_agent.adapters.vector_store import ChunkMetadata
from procurement_agent.ports import ParsedElement
from procurement_agent.schema.registry import FIELD_SPECS, FieldSpec
from procurement_agent.services import indexing

REPO = pathlib.Path(__file__).resolve().parent.parent


def test_parsed_element_annotations_include_optional_bbox_table_page_quality_role() -> None:
    """P2-C1: the Protocol carries the four fields FR-ING-04/05 could not state."""
    assert set(ParsedElement.__annotations__) == {
        "kind",
        "text",
        "page",
        "bbox",
        "table",
        "page_quality",
        "role",
    }


def test_chunk_record_fields() -> None:
    """P2-C2: story-2 §1, imported from the schema package, not a second home."""
    from procurement_agent.schema import ChunkRecord

    assert ChunkRecord.__module__ == "procurement_agent.schema.chunk"
    assert set(ChunkRecord.__annotations__) == {
        "chunk_id",
        "document_id",
        "kind",
        "text",
        "body",
        "context_prefix",
        "page",
        "section",
        "table_id",
        "ordinal",
    }


def test_chunk_metadata_gains_chunk_kind_table_id_section() -> None:
    """P2-C2: upsert vocabulary grows; existing keys stay."""
    keys = set(ChunkMetadata.__annotations__)
    assert {
        "document_id",
        "text",
        "page",
        "source_tier",
        "category",
        "supplier",
        "chunk_kind",
        "table_id",
        "section",
    } == keys


def test_chunk_returns_list_of_chunk_record() -> None:
    """P2-C2: return type only. The body is still Track 2's."""
    from procurement_agent.schema import ChunkRecord

    assert get_type_hints(indexing.chunk)["return"] == list[ChunkRecord]
    with pytest.raises(NotImplementedError):
        indexing.chunk([], size_tokens=512, overlap_ratio=0.05)


def test_lexical_search_port_none_allowlist_returns_nothing() -> None:
    """P2-C3: the VectorStorePort rule, on the seventh Protocol."""
    from procurement_agent.adapters.lexical_store.memory import InMemoryLexicalStore
    from procurement_agent.schema import ComponentCategory, SourceTier

    store = InMemoryLexicalStore()
    store.upsert(
        chunk_ids=["chunk-0"],
        texts=["JKM610N-66HL4M-V rated power"],
        document_ids=["doc-0"],
        pages=[1],
        source_tiers=[SourceTier.SYSTEM_OF_RECORD],
        categories=[ComponentCategory.PV_MODULES],
        suppliers=["jinko"],
    )
    omitted = store.search_lexical("JKM610N", limit=6, allowed_document_ids=None)
    empty = store.search_lexical("JKM610N", limit=6, allowed_document_ids=set())
    allowed = store.search_lexical("JKM610N", limit=6, allowed_document_ids={"doc-0"})
    assert omitted == []
    assert empty == []
    assert [hit.document_id for hit in allowed] == ["doc-0"]


def test_web_hit_has_no_snippet_or_rank() -> None:
    """P2-C4 / D-20: the provider list is transient; only the URL is kept."""
    from procurement_agent.ports import WebHit

    assert set(WebHit.__annotations__) == {"url", "title", "retrieved_at", "provider"}
    assert "snippet" not in WebHit.__annotations__
    assert "rank" not in WebHit.__annotations__


def test_principal_context_is_the_schema_type() -> None:
    """P2-C5: one class, in schema/. 4a must not mint a second under services/."""
    from procurement_agent.schema import PrincipalContext

    assert PrincipalContext.__module__ == "procurement_agent.schema.principal"
    hints = get_type_hints(PrincipalContext)
    assert hints["subject"] is str
    assert hints["cleared_for_restricted"] is bool
    assert hints["denied_suppliers"] == frozenset[str]
    parameters = inspect.signature(PrincipalContext).parameters
    assert parameters["denied_suppliers"].default == frozenset()

    services = REPO / "src" / "procurement_agent" / "services"
    duplicated = [
        path
        for path in services.rglob("*.py")
        if "class PrincipalContext" in path.read_text(encoding="utf-8")
    ]
    assert not duplicated, f"PrincipalContext class body under services/: {duplicated}"


def test_sql_readme_reserves_10_through_14() -> None:
    """P2-C6/C7: reservation rows, not the DDL files. 4a/7 write those."""
    readme = (REPO / "sql" / "README.md").read_text(encoding="utf-8")
    for number in ("10", "11", "12", "13", "14"):
        assert number in readme, f"sql/README.md does not reserve {number}_"
    sql_dir = REPO / "sql"
    leaked = sorted(p.name for p in sql_dir.glob("[0-9][0-9]_*.sql") if p.name >= "10_")
    assert leaked == [], f"Track 0 must not write sql/10–14; found {leaked}"


def test_sql_apply_glob_is_two_digit() -> None:
    """P2-C6/C7: `0*.sql` silently skips `10_`…`14_`. Two-digit is the apply order."""
    needle = "[0-9][0-9]_*.sql"
    readme = (REPO / "sql" / "README.md").read_text(encoding="utf-8")
    assert needle in readme
    assert "sql/0*.sql" not in readme

    schema = (REPO / "tests" / "test_sql_schema.py").read_text(encoding="utf-8")
    behaviour = (REPO / "tests" / "test_sql_behaviour.py").read_text(encoding="utf-8")
    audit = (REPO / "tests" / "test_audit_live.py").read_text(encoding="utf-8")
    for source, name in (
        (schema, "test_sql_schema.py"),
        (behaviour, "test_sql_behaviour.py"),
        (audit, "test_audit_live.py"),
    ):
        assert 'glob("[0-9][0-9]_*.sql")' in source, f"{name} still applies 0*.sql"


def test_extractor_version_prefixes() -> None:
    """P2-C8: the four prefixes, pinned. No claim is written here."""
    from procurement_agent.schema import EXTRACTOR_VERSION_PREFIXES

    assert EXTRACTOR_VERSION_PREFIXES == (
        "<pipeline>@<semver-or-hash>",
        "human:<oidc-sub>",
        "web:<provider>@<version>",
        "gold:<annotator>",
    )


def test_fieldspec_has_optional_web_query_template() -> None:
    """P2-C9: silence is the default; Story 3 fills templates, not this freeze."""
    field = FieldSpec.model_fields["web_query_template"]
    assert field.annotation == str | None
    assert field.default is None
    assert all(spec.web_query_template is None for spec in FIELD_SPECS)


def test_current_state_baseline_is_the_post_36_count() -> None:
    """P2-A-8: the measured baseline this worktree started from, not the 1000 pin."""
    text = (REPO / "docs" / "current-state.md").read_text(encoding="utf-8")
    assert "1039 passed" in text or "1039 passing" in text
    assert "42 skipped" in text
    assert "4 xfailed" in text or "4 expected failures" in text
    assert "**1000 passing" not in text


def test_plan_decision_4_names_pypdfium2_and_libreoffice_for_word() -> None:
    """P2-A-18: the probe is pypdfium2; Word pages come from LibreOffice → PDF."""
    plan = (REPO / "specs" / "001-procurement-agent" / "plan.md").read_text(encoding="utf-8")
    start = plan.index("## Decision 4")
    end = plan.index("\n## Decision 5")
    decision_4 = plan[start:end]
    assert "pypdfium2" in decision_4
    assert "LibreOffice" in decision_4
    assert "raw PyMuPDF text count" not in decision_4
    assert "MSWord backend" not in decision_4 or "LibreOffice" in decision_4


def test_current_decision_10_count_files_do_not_claim_six() -> None:
    """P2-A-24: Decision 10's current count is eight. Historical Phase 1 may say six."""
    files = (
        REPO / "src" / "procurement_agent" / "ports" / "__init__.py",
        REPO / "tests" / "port_contracts" / "test_conformance_matrix.py",
        REPO / "tests" / "port_contracts" / "test_port_contracts.py",
        REPO / "docs" / "decisions" / "ADR-001-cross-repo-pattern-adoption.md",
        REPO / "docs" / "current-state.md",
        REPO / "src" / "procurement_agent" / "adapters" / "registry.py",
        REPO / "src" / "procurement_agent" / "adapters" / "__init__.py",
    )
    phrases = (
        "six port",
        "six Protocol",
        "six swap",
        "Six interfaces",
        "six Protocols",
        "the six ports",
        "the six port",
    )
    offenders: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for phrase in phrases:
            if phrase.lower() in lowered:
                offenders.append(f"{path.relative_to(REPO)}: {phrase!r}")
    assert not offenders, "current Decision 10 count files still claim six:\n" + "\n".join(
        offenders
    )


def test_no_principal_context_class_body_under_services() -> None:
    """Companion to P2-C5: AST, so a comment cannot satisfy the grep pin."""
    services = REPO / "src" / "procurement_agent" / "services"
    hits: list[str] = []
    for path in services.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "PrincipalContext":
                hits.append(str(path.relative_to(REPO)))
    assert hits == []
