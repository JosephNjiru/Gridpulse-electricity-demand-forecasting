"""One-shot, auditable monitoring and retraining decision logic."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Literal

Action = Literal["KEEP", "RETRAIN_CANDIDATE", "REVIEW_DATA", "INSUFFICIENT_EVIDENCE"]


def monitoring_decision(
    *,
    recent_mae: float | None,
    baseline_mae: float | None,
    recent_mase: float | None,
    baseline_mase: float | None,
    coverage: float,
    quality_failures: int,
    freshness_hours: float | None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return one decision without promoting or replacing a model."""
    if quality_failures < 0:
        raise ValueError("quality_failures must be non-negative")
    if not math.isfinite(coverage) or not 0 <= coverage <= 1:
        raise ValueError("coverage must be finite and between 0 and 1")
    if freshness_hours is not None and (
        not math.isfinite(freshness_hours) or freshness_hours < 0
    ):
        raise ValueError("freshness_hours must be non-negative and finite")
    for name, value in (
        ("recent_mae", recent_mae),
        ("baseline_mae", baseline_mae),
        ("recent_mase", recent_mase),
        ("baseline_mase", baseline_mase),
    ):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError(f"{name} must be non-negative and finite")
    reasons: list[str] = []
    if quality_failures > 0:
        return {
            "action": "REVIEW_DATA",
            "policy_version": "monitoring-v1",
            "reasons": ["data-quality failures present"],
        }
    if recent_mae is None or baseline_mae is None or recent_mase is None or baseline_mase is None:
        return {
            "action": "INSUFFICIENT_EVIDENCE",
            "policy_version": "monitoring-v1",
            "reasons": ["required metrics are missing"],
        }
    if coverage < 0.95:
        reasons.append("evaluation coverage below 95%")
    if freshness_hours is None or freshness_hours > 24:
        reasons.append("source freshness exceeds 24 hours or is unknown")
    if reasons:
        return {"action": "INSUFFICIENT_EVIDENCE", "policy_version": "monitoring-v1", "reasons": reasons}
    degraded = recent_mae > baseline_mae * 1.10 or recent_mase > baseline_mase * 1.10
    action: Action = "RETRAIN_CANDIDATE" if degraded else "KEEP"
    reasons.append("recent error exceeds baseline by more than 10%" if degraded else "recent error within 10% baseline")
    result = {
        "action": action,
        "policy_version": "monitoring-v1",
        "reasons": reasons,
        "recent_mae": recent_mae,
        "baseline_mae": baseline_mae,
        "recent_mase": recent_mase,
        "baseline_mase": baseline_mase,
        "coverage": coverage,
        "freshness_hours": freshness_hours,
    }
    if now is not None:
        result["evaluated_at_utc"] = now.astimezone(timezone.utc).isoformat()
    return result
