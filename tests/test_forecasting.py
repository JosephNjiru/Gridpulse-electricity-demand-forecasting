import math
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from metrics import forecast_metrics, seasonal_scale
from monitoring import monitoring_decision
from wa import load_wa_records


class MetricsTests(unittest.TestCase):
    def test_golden_metrics_and_positive_mape_mask(self):
        result = forecast_metrics([100, 0, -20, 50], [90, 10, -10, 60])
        self.assertEqual(result["mae_mw"], 10)
        self.assertEqual(result["rmse_mw"], 10)
        self.assertEqual(result["bias_mw"], 5)
        self.assertEqual(result["mape_valid_count"], 2)
        self.assertEqual(result["mape_excluded_zero_count"], 1)
        self.assertEqual(result["mape_excluded_negative_count"], 1)
        self.assertAlmostEqual(result["mape_percent"], 15)
        self.assertAlmostEqual(result["wape_percent"], 100 * 40 / 170)
        self.assertAlmostEqual(
            result["smape_percent"],
            200 * (10 / 190 + 10 / 10 + 10 / 30 + 10 / 110) / 4,
        )

    def test_scaled_metrics_use_training_only(self):
        result = forecast_metrics(
            [18, 20], [16, 19], training=[10, 14, 12, 16], seasonal_lag=2
        )
        self.assertEqual(seasonal_scale([10, 14, 12, 16], 2), (2.0, None))
        self.assertAlmostEqual(result["mase"], 0.75)
        self.assertAlmostEqual(result["rmsse"], math.sqrt(2.5) / 2)

    def test_undefined_and_nonfinite_values_are_explicit(self):
        result = forecast_metrics([0, 0, float("nan")], [0, 1, 4], training=[5, 5], seasonal_lag=1)
        self.assertIsNone(result["mape_percent"])
        self.assertIsNone(result["wape_percent"])
        self.assertIsNone(result["mase"])
        self.assertEqual(result["nonfinite_count"], 1)
        self.assertEqual(result["undefined_mase_reason"], "zero training seasonal scale")

    def test_outlier_rmse_exceeds_mae(self):
        result = forecast_metrics([1, 1, 1], [1, 1, 11])
        self.assertGreater(result["rmse_mw"], result["mae_mw"])

    def test_monitoring_actions_are_explicit(self):
        self.assertEqual(
            monitoring_decision(
                recent_mae=12, baseline_mae=10, recent_mase=1.2, baseline_mase=1,
                coverage=1, quality_failures=0, freshness_hours=1,
            )["action"],
            "RETRAIN_CANDIDATE",
        )
        self.assertEqual(
            monitoring_decision(
                recent_mae=10, baseline_mae=10, recent_mase=1, baseline_mase=1,
                coverage=1, quality_failures=1, freshness_hours=1,
            )["action"],
            "REVIEW_DATA",
        )
        with self.assertRaises(ValueError):
            monitoring_decision(
                recent_mae=1, baseline_mae=1, recent_mase=1, baseline_mase=1,
                coverage=1.1, quality_failures=0, freshness_hours=1,
            )
        with self.assertRaises(ValueError):
            monitoring_decision(
                recent_mae=float("nan"), baseline_mae=1, recent_mase=1, baseline_mase=1,
                coverage=1, quality_failures=0, freshness_hours=1,
            )

    def test_mismatched_lengths_rejected(self):
        with self.assertRaises(ValueError):
            forecast_metrics([1], [1, 2])

    def test_wa_native_schema_and_cadence_are_enforced(self):
        content = (
            "Dispatch Interval,Operational Demand,Unscheduled Operational Demand,"
            "Operational Withdrawal,Extracted At\n"
            "01/01/2025 08:00:00,10,5,-5,\n"
            "01/01/2025 08:05:00,11,6,-5,\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wa.csv"
            path.write_text(content, encoding="utf-8")
            records = load_wa_records(path)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["operational_withdrawal_mw"], -5)
        self.assertEqual(records[0]["source_order"], "ascending")

    def test_wa_rejects_mixed_source_order(self):
        content = (
            "Dispatch Interval,Operational Demand,Unscheduled Operational Demand,"
            "Operational Withdrawal,Extracted At\n"
            "01/01/2025 08:00:00,10,5,-5,\n"
            "01/01/2025 08:05:00,11,6,-5,\n"
            "01/01/2025 08:00:10,12,7,-5,\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wa.csv"
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                load_wa_records(path)

    def test_comparators_share_reference_scale(self):
        import forecasting
        import gridpulse
        from datetime import datetime, timedelta

        records = [
            gridpulse.DemandRecord(
                "NSW1",
                (datetime(2026, 9, 1, 4, 30) + timedelta(minutes=30 * index)).strftime(
                    "%Y/%m/%d %H:%M:%S"
                ),
                float(index % 100),
                0,
                0,
                "2026/09/01 04:30:01",
                "m",
                "c",
            )
            for index in range(480)
        ]
        rows = forecasting.evaluate_nem(records)["results"]
        self.assertEqual({row["reference_seasonal_lag"] for row in rows}, {48})

    def test_origin_manifest_is_weekly_and_reserves_holdout(self):
        import forecasting
        import gridpulse
        from datetime import datetime, timedelta

        records = [
            gridpulse.DemandRecord(
                "NSW1",
                (datetime(2026, 1, 1, 4, 30) + timedelta(minutes=30 * index)).strftime(
                    "%Y/%m/%d %H:%M:%S"
                ),
                float(index),
                0,
                0,
                "2026/01/01 04:30:01",
                "m",
                "c",
            )
            for index in range(1600)
        ]
        manifest = forecasting.build_origin_manifest(records)
        self.assertGreater(len(manifest), 1)
        self.assertTrue(all(item["origin_index"] % 336 == 0 for item in manifest))
        self.assertEqual(manifest[0]["split"], "development")
        self.assertLess(manifest[-1]["origin_index"] + 48, len(records) - 672)


if __name__ == "__main__":
    unittest.main()
