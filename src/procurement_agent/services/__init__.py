"""The seven functional services of TRS section 2.

    Ingestion & Extraction -> Indexing -> Retrieval -> Web Search
        -> Conflict & HITL -> Comparison / Output, coordinated by Orchestrator.

The TRS names these as services, not as named agents: it specifies no agent
roster, message protocol or handoff schema. "Agentic" here means
schema-constrained LLM extraction inside an orchestrated workflow with a human
gate, so each module below is a unit of responsibility rather than a persona.
"""
