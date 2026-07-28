# Open questions

**Superseded.** This file was written during scaffolding, before any research. The open items it
raised are now resolved with researched defaults in
[specs/001-procurement-agent/clarifications.md](../specs/001-procurement-agent/clarifications.md).

Work from that document, not this one.

| Original question | Now resolved in |
|---|---|
| HITL confidence threshold | D-3 — a precision target, not a fixed float |
| Numeric conflict tolerance | D-2 — a per-field table with three tolerance kinds |
| 7 categories or 8 | D-9 — eight, following the TRS |
| Supplier and model identity resolution | D-4, D-4a |
| Authentication and identity model | D-12a |
| Orchestrator contract | plan.md Decision 1 — a Postgres state machine, not a framework |
| HITL resolution UI | plan.md Decision 2, D-10 |
| Retrieval tuning | plan.md Decisions 3, 5, 6 |

## Still genuinely open

These carry forward. Each is assigned in
[tasks.md](../specs/001-procurement-agent/tasks.md).

1. **The deterministic workbook has never been opened in desktop Excel or LibreOffice.** Gating
   for AC-7 — task G.6.
2. **IEEE C57.12.00 clause text is paywalled.** Its tolerance figures are corroborated three
   times but never read from a licensed copy. IEC figures are primary-verified.
3. **CEC's weighted-efficiency derivation is not reproducible** from the published matrix. The
   0.5 pp quantisation is verified fact; the formula is not.
4. **Several inverter suffix semantics remain undecoded** — see the carried-forward list at the
   foot of clarifications.md.
5. **BABA applicability** still hinges on the project's funding status, which nobody has
   confirmed. Until then `baba_status` stays `unconfirmed`.
