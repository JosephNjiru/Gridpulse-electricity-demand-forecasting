"""Small, transparent seasonal-naive NEM backtest."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from gridpulse import DemandRecord, load_nem_records
from metrics import forecast_metrics


def build_origin_manifest(
    records: Iterable[DemandRecord],
    *,
    horizon: int = 48,
    warmup: int = 336,
    stride: int = 336,
    holdout_intervals: int = 672,
) -> list[dict[str, object]]:
    """Create deterministic weekly origins while reserving a final holdout."""
    by_region: dict[str, list[DemandRecord]] = defaultdict(list)
    for record in records:
        by_region[record.region_id].append(record)
    manifest: list[dict[str, object]] = []
    for region, values in sorted(by_region.items()):
        ordered = sorted(
            values,
            key=lambda record: datetime.strptime(record.interval_datetime, "%Y/%m/%d %H:%M:%S"),
        )
        final_origin = len(ordered) - horizon - holdout_intervals
        fold = 0
        for origin in range(warmup, final_origin + 1, stride):
            fold += 1
            manifest.append(
                {
                    "fold_id": f"{region}-dev-{fold:03d}",
                    "split": "development",
                    "region": region,
                    "origin_index": origin,
                    "issue_time_source": ordered[origin - 1].interval_datetime,
                    "target_start_source": ordered[origin].interval_datetime,
                    "target_end_source": ordered[origin + horizon - 1].interval_datetime,
                    "horizon": horizon,
                    "training_start_source": ordered[0].interval_datetime,
                    "training_end_source": ordered[origin - 1].interval_datetime,
                }
            )
    if not manifest:
        raise ValueError("insufficient history for origin manifest")
    return manifest


def seasonal_naive(values: list[float], horizon: int, lag: int) -> list[float]:
    """Forecast using the latest available value from a fixed seasonal lag."""
    if len(values) < lag:
        raise ValueError(f"at least {lag} observations are required")
    return [values[-lag + offset % lag] for offset in range(horizon)]


def evaluate_nem(
    records: Iterable[DemandRecord],
    origins: int = 3,
    origin_manifest: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Evaluate baselines as a retrospective, source-order hindcast.

    The source timestamp is retained verbatim. Publication availability is not
    proven, so this output is not represented as a live issued forecast.
    """
    by_region: dict[str, list[DemandRecord]] = defaultdict(list)
    for record in records:
        by_region[record.region_id].append(record)
    results: list[dict[str, object]] = []
    forecasts: list[dict[str, object]] = []
    for region, region_records in sorted(by_region.items()):
        ordered = sorted(
            region_records,
            key=lambda record: datetime.strptime(record.interval_datetime, "%Y/%m/%d %H:%M:%S"),
        )
        values = [float(record.operational_demand) for record in ordered]
        horizon = 48
        lag = 48
        region_manifest = [
            item for item in (origin_manifest or [])
            if item["region"] == region
        ]
        if origin_manifest is None:
            first_origin = len(values) - origins * horizon
            region_manifest = [
                {
                    "fold_id": f"{region}-legacy-{index:03d}",
                    "split": "development",
                    "origin_index": origin,
                }
                for index, origin in enumerate(
                    range(first_origin, len(values) - horizon + 1, horizon), start=1
                )
            ]
        for fold in region_manifest:
            origin = int(fold["origin_index"])
            if origin < 336 or origin + horizon > len(values):
                raise ValueError(f"origin outside available history for {region}: {origin}")
            train = values[:origin]
            actual = values[origin : origin + horizon]
            reference_lag = 48
            for model_id, model_lag in (("seasonal_naive_day", 48), ("seasonal_naive_week", 336)):
                prediction = seasonal_naive(train, horizon, model_lag)
                metrics = forecast_metrics(
                    actual,
                    prediction,
                    training=train,
                    seasonal_lag=reference_lag,
                )
                issue_time = ordered[origin - 1].interval_datetime
                target_start = ordered[origin].interval_datetime
                results.append(
                    {
                        "market": "NEM",
                        "region": region,
                        "issue_time_source": issue_time,
                        "origin_index": origin,
                        "fold_id": fold["fold_id"],
                        "split": fold["split"],
                        "target_start_source": target_start,
                        "training_start_source": ordered[0].interval_datetime,
                        "training_end_source": issue_time,
                        "horizon": horizon,
                        "model_id": model_id,
                        "model_version": "seasonal-naive-v1",
                        "evaluation_policy": "retrospective_source_order; availability_unverified",
                        "reference_model_id": "seasonal_naive_day",
                        "reference_seasonal_lag": reference_lag,
                        **metrics,
                    }
                )
                for lead, (record, observed, predicted) in enumerate(
                    zip(ordered[origin : origin + horizon], actual, prediction),
                    start=1,
                ):
                    error = predicted - observed
                    forecasts.append(
                        {
                            "market": "NEM",
                            "region": region,
                            "issue_time_source": issue_time,
                            "target_time_source": record.interval_datetime,
                            "fold_id": fold["fold_id"],
                            "split": fold["split"],
                            "horizon": lead,
                            "actual_mw": observed,
                            "forecast_mw": predicted,
                            "model_id": model_id,
                            "model_version": "seasonal-naive-v1",
                            "source_csv": record.source_csv,
                            "source_member": record.source_member,
                            "signed_error_mw": error,
                            "absolute_error_mw": abs(error),
                        }
                    )
    return {
        "schema_version": "forecast-evaluation-v2",
        "market": "NEM",
        "source_timestamp_contract": "AEMO source timestamp retained; timezone and publication availability unverified",
        "origins_per_region": (
            len({item["fold_id"] for item in origin_manifest}) // len(by_region)
            if origin_manifest
            else origins
        ),
        "results": results,
        "forecasts": forecasts,
    }


def write_r_input(records: Iterable[DemandRecord], output: Path) -> None:
    """Write the smallest canonical chronological dataset needed by R."""
    import csv

    ordered = sorted(
        records,
        key=lambda record: (record.region_id, datetime.strptime(record.interval_datetime, "%Y/%m/%d %H:%M:%S")),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["region", "index", "timestamp_source", "demand_mw"])
        current_region = None
        index = 0
        for record in ordered:
            if record.region_id != current_region:
                current_region = record.region_id
                index = 0
            writer.writerow([record.region_id, index, record.interval_datetime, record.operational_demand])
            index += 1


def write_origin_manifest(manifest: list[dict[str, object]], output: Path) -> None:
    """Write the shared fold contract for R and independent inspection."""
    import csv

    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "fold_id", "split", "region", "origin_index", "issue_time_source",
        "target_start_source", "target_end_source", "horizon",
        "training_start_source", "training_end_source",
    ]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded NEM seasonal baselines")
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--r-input", type=Path)
    parser.add_argument("--origins", type=int, default=3)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Explicit project-local directory for generated multi-archive manifests",
    )
    args = parser.parse_args(argv)
    try:
        records = []
        for input_path in args.input:
            records.extend(load_nem_records(input_path))
        manifest = None
        if args.manifest:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        elif len(args.input) > 1:
            if args.output_dir is None:
                raise ValueError("--output-dir is required when multiple input archives are supplied")
            output_dir = args.output_dir.resolve()
            if not output_dir.is_dir():
                raise ValueError(f"--output-dir must already exist: {output_dir}")
            manifest = build_origin_manifest(records)
            args.manifest = output_dir / "nem_origin_manifest.json"
            args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            write_origin_manifest(manifest, output_dir / "nem_origin_manifest.csv")
        result = evaluate_nem(records, origins=args.origins, origin_manifest=manifest)
        result["source_archives"] = [str(path) for path in args.input]
        if args.manifest:
            result["origin_manifest"] = str(args.manifest)
        if args.r_input:
            write_r_input(records, args.r_input)
    except (OSError, ValueError) as error:
        print(f"forecast evaluation failed: {error}")
        return 2
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
