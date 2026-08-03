from procurement_agent.schema import CanonicalField, SourceRef, SourceTier
from procurement_agent.services.conflict_hitl import (
    AutonomousOverwriteError,
    assert_no_autonomous_overwrite,
)

contract_value = CanonicalField(
    value=650,
    unit="W",
    verbatim_value="650 W",
    source_tier=SourceTier.SYSTEM_OF_RECORD,
    source_ref=SourceRef(document_id="supplier-spec.pdf", page=3),
    confidence=0.98,
)

web_value = CanonicalField(
    value=655,
    unit="W",
    verbatim_value="655 W",
    source_tier=SourceTier.WEB_SUPPLEMENT,
    source_ref=SourceRef(url="https://manufacturer.example/module"),
    confidence=0.90,
)

try:
    assert_no_autonomous_overwrite(contract_value, web_value)
except AutonomousOverwriteError:
    # A production reducer would create a conflict for human review.
    pass

print("README EXAMPLE OK")
