"""Local MLflow logging for the bounded forecast evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def log_baseline_experiments(
    evaluation_path: Path,
    tracking_path: Path,
    r_evaluation_path: Path | None = None,
) -> list[str]:
    import mlflow

    payload = json.loads(evaluation_path.read_text(encoding="utf-8"))
    tracking_path = tracking_path.resolve()
    tracking_path.parent.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(tracking_path.as_uri())
    experiment_name = "gridpulse-local-nem-baselines"
    mlflow.set_experiment(experiment_name)
    source_hash = hashlib.sha256(evaluation_path.read_bytes()).hexdigest()
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in payload["results"]:
        grouped[str(row["model_id"])].append(row)
    run_ids: list[str] = []
    for model_id, rows in sorted(grouped.items()):
        key = f"{source_hash}:{model_id}"
        existing = mlflow.search_runs(
            filter_string=f"tags.gridpulse_run_key = '{key}'",
            max_results=1,
        )
        if not existing.empty:
            run_ids.append(str(existing.iloc[0]["run_id"]))
            continue
        with mlflow.start_run(run_name=model_id, tags={"gridpulse_run_key": key}) as run:
            mlflow.log_params(
                {
                    "market": "NEM",
                    "model_id": model_id,
                    "origins_per_region": payload["origins_per_region"],
                    "horizon_intervals": 48,
                    "evaluation_policy": "retrospective_source_order; availability_unverified",
                    "input_sha256": source_hash,
                    "metric_version": "metrics-v1",
                }
            )
            for metric_name in ("mae_mw", "rmse_mw", "mape_percent", "mase", "rmsse"):
                values = [float(row[metric_name]) for row in rows if row[metric_name] is not None]
                if values:
                    mlflow.log_metric(metric_name, sum(values) / len(values))
            mlflow.log_metric("matched_valid_count", sum(int(row["matched_valid_count"]) for row in rows))
            mlflow.log_metric("mape_valid_count", sum(int(row["mape_valid_count"]) for row in rows))
            mlflow.log_artifact(str(evaluation_path), artifact_path="evaluation")
            run_ids.append(run.info.run_id)
    if r_evaluation_path is not None:
        r_payload = json.loads(r_evaluation_path.read_text(encoding="utf-8"))
        r_hash = hashlib.sha256(r_evaluation_path.read_bytes()).hexdigest()
        model_id = str(r_payload["model_id"])
        key = f"{r_hash}:{model_id}"
        existing = mlflow.search_runs(
            filter_string=f"tags.gridpulse_run_key = '{key}'",
            max_results=1,
        )
        if not existing.empty:
            run_ids.append(str(existing.iloc[0]["run_id"]))
        else:
            folds = r_payload["folds"]
            with mlflow.start_run(run_name=model_id, tags={"gridpulse_run_key": key}) as run:
                mlflow.log_params(
                    {
                        "market": "NEM",
                        "model_id": model_id,
                        "fold_count": len(folds),
                        "evaluation_policy": "retrospective_source_order; availability_unverified",
                        "input_sha256": r_hash,
                    }
                )
                for metric_name in ("mae_mw", "rmse_mw", "mape_percent", "mase", "rmsse"):
                    values = [float(row[metric_name]) for row in folds if row[metric_name] is not None]
                    if values:
                        mlflow.log_metric(metric_name, sum(values) / len(values))
                mlflow.log_metric("mape_valid_count", sum(int(row["mape_valid_count"]) for row in folds))
                mlflow.log_artifact(str(r_evaluation_path), artifact_path="evaluation")
                run_ids.append(run.info.run_id)
    return run_ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Log local GridPulse MLflow experiments")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--tracking", type=Path, default=Path("data/mlruns"))
    parser.add_argument("--r-evaluation", type=Path)
    args = parser.parse_args(argv)
    try:
        run_ids = log_baseline_experiments(args.input, args.tracking, args.r_evaluation)
    except (OSError, ValueError, ImportError) as error:
        print(f"MLflow logging failed: {error}")
        return 2
    print(json.dumps({"run_ids": run_ids, "tracking_uri": args.tracking.resolve().as_uri()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
