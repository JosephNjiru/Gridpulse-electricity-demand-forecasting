"""Native five-minute adapter and bounded baseline for post-reform WA data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from metrics import forecast_metrics

REQUIRED_FIELDS = (
    "Dispatch Interval",
    "Operational Demand",
    "Unscheduled Operational Demand",
    "Operational Withdrawal",
    "Extracted At",
)


def load_wa_records(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        raise ValueError(f"WA input does not exist: {path}")
    records: list[dict[str, object]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != REQUIRED_FIELDS:
            raise ValueError(f"unexpected WA schema: {reader.fieldnames}")
        for row_number, row in enumerate(reader, start=2):
            try:
                timestamp = datetime.strptime(row["Dispatch Interval"], "%d/%m/%Y %H:%M:%S")
                demand = float(row["Operational Demand"])
                unscheduled = float(row["Unscheduled Operational Demand"])
                withdrawal = float(row["Operational Withdrawal"])
            except (TypeError, ValueError, KeyError) as error:
                raise ValueError(f"invalid WA row {row_number}") from error
            if not all(value == value and abs(value) != float("inf") for value in (demand, unscheduled, withdrawal)):
                raise ValueError(f"non-finite WA value at row {row_number}")
            records.append(
                {
                    "dispatch_interval": timestamp,
                    "operational_demand_mw": demand,
                    "unscheduled_operational_demand_mw": unscheduled,
                    "operational_withdrawal_mw": withdrawal,
                    "extracted_at": row["Extracted At"] or None,
                    "source_row": row_number,
                }
            )
    if not records:
        raise ValueError("WA source contains no rows")
    keys = [record["dispatch_interval"] for record in records]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate WA dispatch intervals")
    source_steps = [
        (right - left).total_seconds() / 60
        for left, right in zip(keys, keys[1:])
    ]
    if source_steps and (
        not all(step == 5.0 for step in source_steps)
        and not all(step == -5.0 for step in source_steps)
    ):
        raise ValueError("WA source order is neither ascending nor descending five-minute cadence")
    source_order = "ascending" if not source_steps or source_steps[0] > 0 else "descending"
    ordered = sorted(records, key=lambda record: record["dispatch_interval"])
    steps = {
        (right["dispatch_interval"] - left["dispatch_interval"]).total_seconds() / 60
        for left, right in zip(ordered, ordered[1:])
    }
    if steps - {5.0}:
        raise ValueError(f"WA source is not contiguous five-minute data: {sorted(steps)}")
    for record in records:
        record["source_order"] = source_order
    return ordered


def validate_wa(path: Path) -> dict[str, object]:
    records = load_wa_records(path)
    demand = [float(record["operational_demand_mw"]) for record in records]
    withdrawal = [float(record["operational_withdrawal_mw"]) for record in records]
    constant_runs = 0
    for left, right in zip(demand, demand[1:]):
        constant_runs += left == right
    return {
        "input": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rows": len(records),
        "first_dispatch_interval": records[0]["dispatch_interval"].strftime("%Y-%m-%d %H:%M:%S"),
        "last_dispatch_interval": records[-1]["dispatch_interval"].strftime("%Y-%m-%d %H:%M:%S"),
        "native_cadence_minutes": 5,
        "source_order": records[0]["source_order"],
        "operational_demand_range_mw": [min(demand), max(demand)],
        "operational_withdrawal_range_mw": [min(withdrawal), max(withdrawal)],
        "negative_withdrawal_count": sum(value < 0 for value in withdrawal),
        "missing_extracted_at_count": sum(record["extracted_at"] is None for record in records),
        "adjacent_constant_value_pairs": constant_runs,
        "source_contract": "WA post-reform native five-minute operational demand; not harmonised to NEM",
    }


def evaluate_wa(records: list[dict[str, object]], origins: int = 3) -> dict[str, object]:
    horizon = 288
    lag = 288
    if len(records) < origins * horizon + lag:
        raise ValueError("WA source lacks history for requested origins")
    first_origin = len(records) - origins * horizon
    results = []
    for origin in range(first_origin, len(records) - horizon + 1, horizon):
        train = [float(row["operational_demand_mw"]) for row in records[:origin]]
        actual = [float(row["operational_demand_mw"]) for row in records[origin : origin + horizon]]
        predicted = train[-lag:]
        metrics = forecast_metrics(actual, predicted, training=train, seasonal_lag=lag)
        results.append(
            {
                "market": "WA_WEM_SWIS",
                "model_id": "seasonal_naive_day_native_5min",
                "origin_index": origin,
                "issue_time_source": records[origin - 1]["dispatch_interval"].strftime("%Y-%m-%d %H:%M:%S"),
                "target_start_source": records[origin]["dispatch_interval"].strftime("%Y-%m-%d %H:%M:%S"),
                "horizon": horizon,
                "evaluation_policy": "retrospective_source_order; availability_unverified",
                **metrics,
            }
        )
    return {
        "schema_version": "wa-forecast-evaluation-v1",
        "source_contract": "native five-minute WA series; no NEM aggregation",
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and evaluate native WA operational demand")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        records = load_wa_records(args.input)
        result = {"validation": validate_wa(args.input), "evaluation": evaluate_wa(records)}
        rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
    except (OSError, ValueError) as error:
        print(f"WA evaluation failed: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
