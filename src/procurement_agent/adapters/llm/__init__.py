"""`LLMPort` implementations — FR-ING-07, FR-RAG-04.

No samples type: the prompt, the context chunks and the JSON schema are all
ordinary values the contract suite builds.

Two constraints on anything that lands here, both already decided. Plan Decision
7 requires `json_schema` mode and forbids tool-calling, because tool calls do not
emit logprobs and the log probabilities are a required confidence signal - so an
adapter that satisfies this port through a tool call is off-contract even though
the Protocol cannot see the difference. And D-3 bans self-reported confidence
outright (0.692 AUC), so an adapter must not smuggle one into its result dict.

Note what the contract suite does *not* test: extraction quality. That needs the
labelled gold set (B.9 / D-11), which does not exist. What is tested here is the
refusal - that the model can decline - and the shape of what it returns.
"""

from __future__ import annotations

__all__: list[str] = []
