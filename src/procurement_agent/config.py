"""Runtime configuration.

The TRS implies a config surface without specifying values: supplier row-vs-column
orientation (FR-OUT-01), the HITL confidence threshold (FR-ING-10), the numeric
conflict tolerance (FR-WEB-04), chunking parameters (FR-RAG-01) and endpoint
selection (section 6). Defaults below are starting points, not spec values -
see docs/open-questions.md.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .schema import Severity


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROCUREMENT_", env_file=".env", extra="ignore")

    # --- Endpoints (swappable per NFR-04, self-hosted for confidential data per NFR-03) ---
    llm_endpoint: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    embedding_endpoint: str | None = None
    embedding_model: str | None = None

    database_url: str | None = None
    vector_store_url: str | None = None
    object_store_url: str | None = None
    web_search_api_key: str | None = None

    # --- Review routing ---
    # There is deliberately no `hitl_confidence_threshold` float. A hardcoded
    # number is not derived from anything, and LLM self-reported confidence
    # scores 0.692 ROC AUC - worse than raw logprobs and dangerously
    # plausible-looking. The defensible construction is a precision target with
    # tau read off a risk-coverage curve on a labelled set, tiered by field
    # criticality. See clarifications.md D-3.
    target_precision_auto_accepted: float = Field(
        default=0.99,
        ge=0.0,
        le=1.0,
        description="Target precision on fields accepted without human review",
    )
    review_budget_fraction: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description=(
            "Expected fraction of field instances routed to review in year one. "
            "Falling below this means accepting lower precision - that must be an "
            "explicit decision, not an emergent one."
        ),
    )

    # --- Conflict tolerance ---
    # There is deliberately no global `numeric_conflict_tolerance` float either.
    # A 2% band on a 650 Wp nameplate is +/-13 W, which merges three adjacent
    # 5 W SKUs; the same band on a -0.29 %/degC temperature coefficient is below
    # datasheet precision. Tolerance is per-field with three kinds (exact,
    # absolute, relative) - see the table in clarifications.md D-2.

    # --- Chunking (FR-RAG-01, revised by plan.md Decision 6) ---
    # Overlap reduced from the TRS's 10-20%: systematic analysis found no
    # measurable benefit, and Docling supplies real section boundaries, which is
    # most of what overlap compensated for.
    chunk_size_tokens: int = 512
    chunk_overlap_ratio: float = Field(default=0.05, ge=0.0, le=0.10)

    # --- Concurrency ---
    # The ports are synchronous (plan.md Decision 10); concurrency is driven by the
    # caller via concurrent.futures and bounded here. Size the parse pool off the
    # MEAN page cost, not the median - the distribution is right-skewed, since an
    # OCR page costs roughly an order of magnitude more than a text-layer page.
    max_concurrent_parse: int = Field(
        default=4, ge=1, description="ProcessPoolExecutor width for parse/OCR"
    )
    max_concurrent_llm: int = Field(
        default=8, ge=1, description="ThreadPoolExecutor width for extraction calls"
    )
    web_search_rate_limit_per_minute: int = Field(
        default=30, ge=1, description="Cap on supplementary web queries (FR-WEB-01)"
    )

    # --- Compose gate (issue #14) ---
    # Composition refuses to run while an unresolved conflict sits STRICTLY ABOVE
    # this level. MEDIUM means decision-driving specs may still be open, but a
    # pricing, warranty or certification conflict stops the workbook.
    compose_gate_threshold: Severity = Field(
        default=Severity.MEDIUM,
        description="Unresolved conflicts above this severity block composition",
    )

    # --- Output (FR-OUT-01) ---
    suppliers_as_rows: bool = True


def load_settings() -> Settings:
    return Settings()
