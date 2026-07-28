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

    # --- Thresholds. Both are undefined in the TRS. ---
    hitl_confidence_threshold: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description=(
            "FR-ING-10 routes sub-threshold fields to HITL but names no number. "
            "The TRS baseline is 85-95% extraction accuracy on clean documents."
        ),
    )
    numeric_conflict_tolerance: float = Field(
        default=0.02,
        ge=0.0,
        description=(
            "FR-WEB-04 raises a conflict when values differ 'beyond tolerance' but "
            "never defines it. Fractional, so 0.02 means 2 percent."
        ),
    )

    # --- Chunking (FR-RAG-01: ~400-512 tokens, 10-20% overlap) ---
    chunk_size_tokens: int = 512
    chunk_overlap_ratio: float = Field(default=0.15, ge=0.0, le=0.5)

    # --- Output (FR-OUT-01) ---
    suppliers_as_rows: bool = True


def load_settings() -> Settings:
    return Settings()
