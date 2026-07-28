"""Procurement Agent.

An agentic, human-in-the-loop RAG pipeline that ingests multi-format procurement
documents, extracts structured fields into a canonical component schema,
supplements gaps via web search, detects cross-source conflicts, and emits a
multi-tab Excel supplier comparison.

Final procurement authority remains human (NFR-08).
"""

__version__ = "0.1.0"
