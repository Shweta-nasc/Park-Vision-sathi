"""
CIS validation / "density ≠ impact" proof endpoint (Task 13).

Serves the offline ``cis_validation_report.json`` (Task 2/10 output) as a stable,
additive payload: the three held-out test-split Spearman correlations vs the
measured MapMyIndia ratio (honest non-circular CIS, raw-count baseline, and the
circular full-CIS upper bound), each with a bootstrap CI, plus the per-zone
scatter points. With no report on disk it returns ``available: False`` (pending
the live peak-time collection) — never fabricated numbers. Read-only, in-memory.
"""

from fastapi import APIRouter
from backend.app.data_loader import store

router = APIRouter()


@router.get("/validation/proof")
def validation_proof():
    """The density≠impact proof: scatter points + non-circular trust metric."""
    return store.validation_proof()
