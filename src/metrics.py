"""Finite, explicit forecast metrics with auditable eligibility counts."""

from __future__ import annotations

import math
from collections.abc import Sequence


def _finite_pairs(actual: Sequence[float], forecast: Sequence[float]) -> tuple[list[tuple[float, float]], int]:
    if len(actual) != len(forecast):
        raise ValueError("actual and forecast lengths must match")
    pairs = []
    excluded = 0
    for observed, predicted in zip(actual, forecast):
        if not (math.isfinite(float(observed)) and math.isfinite(float(predicted))):
            excluded += 1
            continue
        pairs.append((float(observed), float(predicted)))
    if not pairs:
        raise ValueError("no finite actual/forecast pairs")
    return pairs, excluded


def seasonal_scale(training: Sequence[float], lag: int) -> tuple[float | None, str | None]:
    if lag <= 0 or len(training) <= lag:
        return None, "insufficient training length for seasonal scale"
    differences = [
        abs(float(training[index]) - float(training[index - lag]))
        for index in range(lag, len(training))
    ]
    if any(not math.isfinite(value) for value in differences):
        return None, "non-finite training value"
    scale = sum(differences) / len(differences)
    if scale == 0:
        return None, "zero training seasonal scale"
    return scale, None


def forecast_metrics(
    actual: Sequence[float],
    forecast: Sequence[float],
    *,
    training: Sequence[float] | None = None,
    seasonal_lag: int | None = None,
) -> dict[str, object]:
    pairs, nonfinite_count = _finite_pairs(actual, forecast)
    errors = [predicted - observed for observed, predicted in pairs]
    abs_errors = [abs(error) for error in errors]
    abs_actual = [abs(observed) for observed, _ in pairs]
    positive = [
        (observed, error)
        for (observed, _), error in zip(pairs, errors)
        if observed > 0
    ]
    zero_count = sum(observed == 0 for observed, _ in pairs)
    negative_count = sum(observed < 0 for observed, _ in pairs)
    smape_terms = [
        0.0 if abs(observed) + abs(predicted) == 0
        else 200.0 * abs(predicted - observed) / (abs(observed) + abs(predicted))
        for observed, predicted in pairs
    ]
    total_abs_actual = sum(abs_actual)
    mape = (
        100.0 * sum(abs(error) / abs(observed) for observed, error in positive) / len(positive)
        if positive
        else None
    )
    wape = 100.0 * sum(abs_errors) / total_abs_actual if total_abs_actual else None
    scale = None
    scale_reason = None
    if training is not None and seasonal_lag is not None:
        scale, scale_reason = seasonal_scale(training, seasonal_lag)
    mase = sum(abs_errors) / len(abs_errors) / scale if scale else None
    rmsse = (
        math.sqrt(sum(error * error for error in errors) / len(errors))
        / math.sqrt(
            sum(
                (float(training[index]) - float(training[index - seasonal_lag])) ** 2
                for index in range(seasonal_lag, len(training))
            )
            / (len(training) - seasonal_lag)
        )
        if training is not None
        and seasonal_lag is not None
        and len(training) > seasonal_lag
        and seasonal_scale(training, seasonal_lag)[0] is not None
        else None
    )
    result: dict[str, object] = {
        "mae_mw": sum(abs_errors) / len(abs_errors),
        "rmse_mw": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "bias_mw": sum(errors) / len(errors),
        "mape_percent": mape,
        "smape_percent": sum(smape_terms) / len(smape_terms),
        "wape_percent": wape,
        "mase": mase,
        "rmsse": rmsse,
        "planned_count": len(actual),
        "matched_valid_count": len(pairs),
        "nonfinite_count": nonfinite_count,
        "mape_valid_count": len(positive),
        "mape_excluded_zero_count": zero_count,
        "mape_excluded_negative_count": negative_count,
        "mape_valid_fraction": len(positive) / len(pairs),
        "zero_actual_count": zero_count,
        "negative_actual_count": negative_count,
        "undefined_mase_reason": scale_reason if mase is None else None,
        "undefined_wape_reason": "zero absolute actual denominator" if wape is None else None,
    }
    return result
