"""`EmbedderPort` implementations — FR-RAG-02.

No samples type: the port takes `list[str]` and returns `list[list[float]]`, so
every input the contract suite needs is an ordinary Python value it can build
itself. The one thing that varies per backend, the vector width, is readable from
the adapter through `dimensions`.

NFR-03 constrains what may go behind this port for confidential documents - a
self-hosted or enterprise endpoint, with no third-party training on contract
data. That is a deployment property rather than a capability, so it is not in
`Capability`: no black-box contract test can tell a self-hosted endpoint from a
public one.
"""

from __future__ import annotations

__all__: list[str] = []
