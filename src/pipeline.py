"""Owner-friendly local GridPulse core pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from forecasting import build_origin_manifest, evaluate_nem, write_origin_manifest, write_r_input
from gridpulse import load_nem_records, validate_nem_collection
from mlflow_tracking import log_baseline_experiments
from monitoring import monitoring_decision

LOGGER = logging.getLogger("gridpulse.pipeline")


def _find_rscript(override: Path | None = None) -> Path:
    candidates = []
    if override:
        candidates.append(override)
    if value := os.environ.get("GRIDPULSE_RSCRIPT"):
        candidates.append(Path(value))
    if found := shutil.which("Rscript"):
        candidates.append(Path(found))
    candidates.extend(Path(r"C:\Program Files\R").glob(r"R-*\bin\Rscript.exe"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("Rscript is unavailable; set --rscript or GRIDPULSE_RSCRIPT")


def _validate_r_output(
    output: Path,
    manifest: list[dict[str, object]],
    python_forecasts: list[dict[str, object]],
) -> dict[str, object]:
    import csv

    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    expected = {
        (str(item["region"]), str(item["fold_id"]), lead)
        for item in manifest
        for lead in range(1, int(item["horizon"]) + 1)
    }
    actual = {(row["region"], row["fold_id"], int(row["horizon"])) for row in rows}
    if len(actual) != len(rows):
        raise RuntimeError("R output contains duplicate region/fold/horizon keys")
    if actual != expected:
        raise RuntimeError(f"R output key mismatch: expected {len(expected)}, received {len(actual)}")
    python_actual = {
        (row["region"], row["fold_id"], int(row["horizon"])): float(row["actual_mw"])
        for row in python_forecasts
        if row["model_id"] == "seasonal_naive_day"
    }
    actual_differences = [
        abs(float(row["actual_mw"]) - python_actual[(row["region"], row["fold_id"], int(row["horizon"]))])
        for row in rows
    ]
    max_actual_difference = max(actual_differences, default=0.0)
    if max_actual_difference > 1e-9:
        raise RuntimeError(f"Python/R target actual mismatch: {max_actual_difference}")
    return {
        "status": "PASS",
        "join_keys": ["region", "fold_id", "horizon"],
        "r_rows": len(rows),
        "expected_rows": len(expected),
        "max_target_actual_difference_mw": max_actual_difference,
        "forecast_numeric_difference": None,
        "forecast_numeric_difference_note": "R ARIMA and Python seasonal-naive models are distinct estimators",
    }


def run_pipeline(root: Path, rscript: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    if not (root / "src").is_dir() or not (root / "data").is_dir():
        raise ValueError(f"not a GridPulse project root: {root}")
    raw = root / "data" / "raw"
    processed = root / "data" / "processed"
    archives = sorted(raw.glob("PUBLIC_ACTUAL_OPERATIONAL_DEMAND_DAILY_*.zip"))
    if not archives:
        raise ValueError("no retained NEM archives found")
    calendar_audit = validate_nem_collection(archives)
    records = []
    for archive in archives:
        records.extend(load_nem_records(archive))
    manifest = build_origin_manifest(records)
    processed.mkdir(parents=True, exist_ok=True)
    rscript_path = _find_rscript(rscript)
    targets = {
        "manifest_json": processed / "nem_origin_manifest.json",
        "manifest_csv": processed / "nem_origin_manifest.csv",
        "evaluation": processed / "nem_pipeline_evaluation.json",
        "r_input": processed / "nem_pipeline_r_input.csv",
        "r_output": processed / "nem_pipeline_r_forecasts.csv",
        "parity": processed / "nem_pipeline_parity.json",
    }
    with tempfile.TemporaryDirectory(prefix="gridpulse-run-", dir=processed) as staging_name:
        staging = Path(staging_name)
        manifest_json = staging / "nem_origin_manifest.json"
        manifest_csv = staging / "nem_origin_manifest.csv"
        evaluation = staging / "nem_pipeline_evaluation.json"
        r_input = staging / "nem_pipeline_r_input.csv"
        r_output = staging / "nem_pipeline_r_forecasts.csv"
        parity = staging / "nem_pipeline_parity.json"
        manifest_json.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        write_origin_manifest(manifest, manifest_csv)
        write_r_input(records, r_input)
        evaluation_payload = evaluate_nem(records, origin_manifest=manifest)
        evaluation_payload["source_archives"] = [str(path) for path in archives]
        evaluation_payload["origin_manifest"] = str(targets["manifest_json"])
        evaluation.write_text(json.dumps(evaluation_payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        completed = subprocess.run(
            [str(rscript_path), str(root / "R" / "forecast.R"), str(r_input), str(r_output), str(manifest_csv)],
            cwd=root, check=False, capture_output=True, text=True,
        )
        if completed.returncode:
            raise RuntimeError(f"R forecast failed: {completed.stderr.strip()}")
        parity_payload = _validate_r_output(r_output, manifest, evaluation_payload["forecasts"])
        parity.write_text(json.dumps(parity_payload, indent=2) + "\n", encoding="utf-8")
        mlflow_input = staging / "mlflow-evaluation.json"
        shutil.copy2(evaluation, mlflow_input)
        run_ids = log_baseline_experiments(mlflow_input, root / "data" / "mlruns")
        for name, target in targets.items():
            os.replace(staging / target.name, target)
    return {
        "status": "PASS",
        "calendar_records": calendar_audit["total_records"],
        "origin_count": len(manifest),
        "python_result_rows": len(evaluation_payload["results"]),
        "python_forecast_rows": len(evaluation_payload["forecasts"]),
        "r_forecast_rows": parity_payload["r_rows"],
        "parity": parity_payload,
        "mlflow_run_ids": run_ids,
        "monitoring_decision": monitoring_decision(
            recent_mae=None,
            baseline_mae=None,
            recent_mase=None,
            baseline_mase=None,
            coverage=1.0,
            quality_failures=0,
            freshness_hours=None,
        ),
        "evaluation_sha256": hashlib.sha256(targets["evaluation"].read_bytes()).hexdigest(),
        "outputs": [str(targets[name]) for name in ("manifest_json", "manifest_csv", "evaluation", "r_input", "r_output", "parity")],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local GridPulse scientific core")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--rscript", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        print(json.dumps(run_pipeline(args.root.resolve(), args.rscript), indent=2))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        LOGGER.error("pipeline failed: %s", error)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
