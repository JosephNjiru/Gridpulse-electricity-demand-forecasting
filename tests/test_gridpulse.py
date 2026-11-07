import io
import json
import sys
import unittest
from unittest import mock
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
import gridpulse
import forecasting


RAW = Path(__file__).parents[1] / "data" / "raw"
NEM_ARCHIVE = RAW / "PUBLIC_ACTUAL_OPERATIONAL_DEMAND_DAILY_20260901.zip"


def nested_archive(csv_text: str, name: str = "daily.csv") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, csv_text)
    return buffer.getvalue()


def sample_csv(region: str = "NSW1", timestamp: str = "2026/09/01 04:30:00") -> str:
    return (
        "C,NEMP.WORLD,ACTUAL_OPERATIONAL_DEMAND_DAILY,AEMO,PUBLIC,2026/09/02,04:40:01\n"
        "I,OPERATIONAL_DEMAND,ACTUAL,3,REGIONID,INTERVAL_DATETIME,OPERATIONAL_DEMAND,"
        "OPERATIONAL_DEMAND_ADJUSTMENT,WDR_ESTIMATE,LASTCHANGED\n"
        f"D,OPERATIONAL_DEMAND,ACTUAL,3,{region},\"{timestamp}\",10,0,0,\"2026/09/01 04:30:01\"\n"
        "C,\"END OF REPORT\",1\n"
    )


def monthly_archive(csv_text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index in range(30):
            daily = csv_text.replace(
                "2026/09/01 04:30:00",
                f"2026/09/{index + 1:02d} 04:30:00",
            )
            archive.writestr(f"day{index:02d}.zip", nested_archive(daily))
    return buffer.getvalue()


class GridPulseTests(unittest.TestCase):
    @unittest.skipUnless(NEM_ARCHIVE.is_file(), "real raw archive is not present")
    def test_verified_archive_summary(self) -> None:
        summary = gridpulse.validate_nem_archive(NEM_ARCHIVE)
        self.assertEqual(summary["total_records"], 7200)
        self.assertEqual(summary["records_by_region"], {region: 1440 for region in sorted(gridpulse.EXPECTED_REGIONS)})
        self.assertEqual(len(summary["negative_observations"]), 7)
        self.assertEqual(summary["duplicate_keys"], 0)
        self.assertEqual(summary["nonzero_adjustment_records"], 0)
        self.assertEqual(summary["nonzero_wdr_records"], 0)

    def test_malformed_schema_is_rejected(self) -> None:
        bad = sample_csv().replace("WDR_ESTIMATE", "WRONG_FIELD")
        with self.assertRaises(gridpulse.ValidationError):
            gridpulse._parse_csv_member(bad.encode(), "daily.zip", "daily.csv")

    def test_duplicate_interval_is_rejected(self) -> None:
        record = gridpulse.DemandRecord("NSW1", "2026/09/01 04:30:00", 10, 0, 0, "x", "m", "c")
        with self.assertRaises(gridpulse.ValidationError):
            gridpulse._validate_records([record, record])

    def test_path_traversal_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../daily.zip", nested_archive(sample_csv()))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.zip"
            path.write_bytes(buffer.getvalue())
            with self.assertRaises(gridpulse.ValidationError):
                gridpulse.validate_nem_archive(path)

    def test_cli_returns_nonzero_for_corrupt_archive(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "corrupt.zip"
            path.write_bytes(b"not a zip")
            self.assertEqual(gridpulse.main(["validate-nem", "--input", str(path)]), 2)

    def test_cli_summary_is_json(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "valid.zip"
            path.write_bytes(monthly_archive(sample_csv()))
            original = path.read_bytes()
            with mock.patch("builtins.print") as output:
                self.assertEqual(
                    gridpulse.main(
                        ["validate-nem", "--input", str(path), "--allow-truncated"]
                    ),
                    0,
                )
            json.loads(output.call_args.args[0])
            self.assertEqual(path.read_bytes(), original)

    def test_seasonal_naive_requires_history_and_preserves_horizon(self) -> None:
        values = list(range(48))
        with self.assertRaises(ValueError):
            forecasting.seasonal_naive(values, 48, 49)
        prediction = forecasting.seasonal_naive(values, 48, 48)
        self.assertEqual(len(prediction), 48)
        self.assertEqual(prediction, values)

    def test_backtest_uses_three_origins(self) -> None:
        records = []
        start = datetime(2026, 9, 1, 4, 30)
        for index in range(480):
            timestamp = (start + timedelta(minutes=30 * index)).strftime("%Y/%m/%d %H:%M:%S")
            records.append(
                gridpulse.DemandRecord("NSW1", timestamp, float(index), 0, 0, timestamp, "m", "c")
            )
        result = forecasting.evaluate_nem(records, origins=3)
        self.assertEqual(len(result["results"]), 6)
        self.assertEqual({row["horizon"] for row in result["results"]}, {48})


if __name__ == "__main__":
    unittest.main()
