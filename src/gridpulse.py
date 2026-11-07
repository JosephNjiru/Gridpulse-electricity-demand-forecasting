"""Read-only validation of the AEMO NEM operational-demand archive."""

from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import io
import json
import logging
import sys
import zipfile
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

LOGGER = logging.getLogger(__name__)
EXPECTED_REGIONS = frozenset({"NSW1", "QLD1", "SA1", "TAS1", "VIC1"})
MAX_MEMBER_COMPRESSED_BYTES = 1_000_000
MAX_MEMBER_UNCOMPRESSED_BYTES = 5_000_000
MAX_ARCHIVE_MEMBERS = 366
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 100_000_000
REQUIRED_FIELDS = (
    "REGIONID",
    "INTERVAL_DATETIME",
    "OPERATIONAL_DEMAND",
    "OPERATIONAL_DEMAND_ADJUSTMENT",
    "WDR_ESTIMATE",
    "LASTCHANGED",
)


class ValidationError(ValueError):
    """Raised when an archive violates the source contract."""


@dataclass(frozen=True)
class DemandRecord:
    region_id: str
    interval_datetime: str
    operational_demand: int
    operational_demand_adjustment: int
    wdr_estimate: int
    lastchanged: str
    source_member: str
    source_csv: str


def _safe_member_name(name: str) -> None:
    normalised = name.replace("\\", "/")
    path = Path(normalised)
    if (
        path.is_absolute()
        or Path(name).drive
        or ".." in path.parts
        or normalised.startswith("/")
    ):
        raise ValidationError(f"unsafe archive member path: {name}")


def _read_bounded(
    zfile: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    remaining_uncompressed: int,
) -> bytes:
    _safe_member_name(info.filename)
    if info.flag_bits & 0x1:
        raise ValidationError(f"encrypted archive member: {info.filename}")
    if info.file_size > MAX_MEMBER_UNCOMPRESSED_BYTES:
        raise ValidationError(f"member exceeds uncompressed limit: {info.filename}")
    if info.compress_size > MAX_MEMBER_COMPRESSED_BYTES:
        raise ValidationError(f"member exceeds compressed limit: {info.filename}")
    if info.file_size > remaining_uncompressed:
        raise ValidationError(f"archive exceeds aggregate uncompressed limit at {info.filename}")
    try:
        return zfile.read(info)
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile) as error:
        raise ValidationError(f"cannot read archive member {info.filename}") from error


def _parse_integer(value: str, field: str, member: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"invalid integer {field} in {member}: {value!r}") from error


def _parse_csv_member(
    content: bytes,
    member: str,
    source_csv: str,
    expected_records: int | None = None,
) -> list[DemandRecord]:
    try:
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    except (UnicodeDecodeError, csv.Error) as error:
        raise ValidationError(f"invalid CSV in {member}") from error
    schema_rows = [row for row in rows if row and row[0] == "I"]
    if len(schema_rows) != 1:
        raise ValidationError(f"{member} must contain exactly one I schema row")
    schema = schema_rows[0][4:]
    if tuple(schema) != REQUIRED_FIELDS:
        raise ValidationError(f"unexpected schema in {member}: {schema}")
    if not rows or rows[-1][:2] != ["C", "END OF REPORT"]:
        raise ValidationError(f"{member} has no end-of-report record")
    records: list[DemandRecord] = []
    for row_number, row in enumerate(rows, start=1):
        if not row or row[0] != "D":
            continue
        if len(row) != 4 + len(schema):
            raise ValidationError(f"malformed D row {row_number} in {member}")
        values = row[4:]
        try:
            datetime.strptime(values[1], "%Y/%m/%d %H:%M:%S")
            datetime.strptime(values[5], "%Y/%m/%d %H:%M:%S")
        except ValueError as error:
            raise ValidationError(
                f"invalid interval timestamp at {member}:{row_number}: {values[1]!r}"
            ) from error
        records.append(
            DemandRecord(
                region_id=values[0],
                interval_datetime=values[1],
                operational_demand=_parse_integer(values[2], schema[2], member),
                operational_demand_adjustment=_parse_integer(values[3], schema[3], member),
                wdr_estimate=_parse_integer(values[4], schema[4], member),
                lastchanged=values[5],
                source_member=member,
                source_csv=source_csv,
            )
        )
        if any(value.strip() == "" for value in values):
            raise ValidationError(f"blank required field at {member}:{row_number}")
    if expected_records is not None and len(records) != expected_records:
        raise ValidationError(f"{member} has {len(records)} records; expected {expected_records}")
    by_region: dict[str, list[str]] = defaultdict(list)
    for record in records:
        by_region[record.region_id].append(record.interval_datetime)
    if any(intervals != sorted(intervals) for intervals in by_region.values()):
        raise ValidationError(f"out-of-order interval records in {member}")
    return records


def _validate_records(records: Iterable[DemandRecord]) -> dict[str, object]:
    records = list(records)
    if not records:
        raise ValidationError("archive contains no data records")
    regions = Counter(record.region_id for record in records)
    unknown = set(regions) - EXPECTED_REGIONS
    if unknown:
        raise ValidationError(f"unexpected regions: {sorted(unknown)}")
    keys = [(record.region_id, record.interval_datetime) for record in records]
    duplicate_count = len(keys) - len(set(keys))
    if duplicate_count:
        raise ValidationError(f"duplicate region/interval keys: {duplicate_count}")
    by_region: dict[str, list[DemandRecord]] = defaultdict(list)
    for record in records:
        by_region[record.region_id].append(record)
    cadence_errors: list[str] = []
    ranges: dict[str, dict[str, str]] = {}
    values: dict[str, dict[str, int]] = {}
    negative_records: list[dict[str, object]] = []
    missing_fields = 0
    adjustment_nonzero = 0
    wdr_nonzero = 0
    for region, region_records in by_region.items():
        ordered = sorted(region_records, key=lambda record: record.interval_datetime)
        dates = [datetime.strptime(r.interval_datetime, "%Y/%m/%d %H:%M:%S") for r in ordered]
        steps = {(right - left).total_seconds() / 60 for left, right in zip(dates, dates[1:])}
        if steps - {30.0}:
            cadence_errors.append(f"{region}: {sorted(steps)}")
        ranges[region] = {
            "first": ordered[0].interval_datetime,
            "last": ordered[-1].interval_datetime,
        }
        demand_values = [record.operational_demand for record in ordered]
        values[region] = {"min_mw": min(demand_values), "max_mw": max(demand_values)}
        for record in ordered:
            if any(
                value == ""
                for value in (
                    record.region_id,
                    record.interval_datetime,
                    record.operational_demand,
                    record.operational_demand_adjustment,
                    record.wdr_estimate,
                    record.lastchanged,
                )
            ):
                missing_fields += 1
            adjustment_nonzero += record.operational_demand_adjustment != 0
            wdr_nonzero += record.wdr_estimate != 0
            if record.operational_demand < 0:
                negative_records.append(
                    {"region": region, "interval": record.interval_datetime, "mw": record.operational_demand}
                )
    if cadence_errors:
        raise ValidationError(f"non-30-minute cadence: {cadence_errors}")
    return {
        "total_records": len(records),
        "records_by_region": dict(sorted(regions.items())),
        "duplicate_keys": duplicate_count,
        "missing_required_fields": missing_fields,
        "negative_observations": negative_records,
        "zero_demand_observations": sum(record.operational_demand == 0 for record in records),
        "nonzero_adjustment_records": adjustment_nonzero,
        "nonzero_wdr_records": wdr_nonzero,
        "time_ranges_by_region": dict(sorted(ranges.items())),
        "demand_range_mw_by_region": dict(sorted(values.items())),
    }


def validate_nem_archive(
    input_path: Path,
    *,
    complete_month: bool = False,
    allow_truncated: bool = False,
) -> dict[str, object]:
    """Validate a NEM monthly archive without writing or extracting files."""
    if not input_path.is_file():
        raise ValidationError(f"input archive does not exist: {input_path}")
    try:
        digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
        with zipfile.ZipFile(input_path) as outer:
            members = outer.infolist()
            if not members or len(members) > MAX_ARCHIVE_MEMBERS:
                raise ValidationError(f"invalid archive member count: {len(members)}")
            if complete_month and len(members) not in {28, 29, 30, 31}:
                raise ValidationError(f"expected 30 daily members, found {len(members)}")
            remaining_uncompressed = MAX_ARCHIVE_UNCOMPRESSED_BYTES
            remaining_csv_uncompressed = MAX_ARCHIVE_UNCOMPRESSED_BYTES
            records: list[DemandRecord] = []
            schema_members: set[tuple[str, ...]] = set()
            for info in members:
                if info.is_dir():
                    raise ValidationError(f"unexpected directory member: {info.filename}")
                nested_bytes = _read_bounded(outer, info, remaining_uncompressed)
                remaining_uncompressed -= info.file_size
                try:
                    with zipfile.ZipFile(io.BytesIO(nested_bytes)) as nested:
                        csv_members = [item for item in nested.infolist() if not item.is_dir()]
                        if len(csv_members) != 1 or not csv_members[0].filename.lower().endswith(".csv"):
                            raise ValidationError(f"unexpected nested structure: {info.filename}")
                        csv_info = csv_members[0]
                        csv_bytes = _read_bounded(
                            nested, csv_info, min(
                                MAX_MEMBER_UNCOMPRESSED_BYTES,
                                remaining_csv_uncompressed,
                            )
                        )
                        remaining_csv_uncompressed -= csv_info.file_size
                        parsed = _parse_csv_member(csv_bytes, info.filename, csv_info.filename)
                        records.extend(parsed)
                        schema_row = next(
                            row
                            for row in csv.reader(io.StringIO(csv_bytes.decode("utf-8-sig")))
                            if row and row[0] == "I"
                        )
                        schema_members.add(tuple(schema_row[4:]))
                except zipfile.BadZipFile as error:
                    raise ValidationError(f"invalid nested ZIP: {info.filename}") from error
    except (OSError, zipfile.BadZipFile) as error:
        raise ValidationError(f"cannot open NEM archive: {input_path}") from error
    if allow_truncated:
        summary = _validate_records_with_truncated_gaps(records)
    else:
        summary = _validate_records(records)
    if complete_month and len(records) not in {len(EXPECTED_REGIONS) * 48 * days for days in (28, 29, 30, 31)}:
        raise ValidationError(f"unexpected complete-month record count: {len(records)}")
    if complete_month:
        expected_per_region = len(members) * 48
        if any(
            summary["records_by_region"].get(region, 0) != expected_per_region
            for region in EXPECTED_REGIONS
        ):
            raise ValidationError("complete month does not contain 48 intervals per region per day")
    summary.update(
        {
            "input": str(input_path),
            "sha256": digest,
            "archive_members": len(members),
            "schema_variants": len(schema_members),
            "source_timestamps_only": True,
            "writes_performed": False,
        }
    )
    return summary


def _validate_records_with_truncated_gaps(records: list[DemandRecord]) -> dict[str, object]:
    """Validate a deliberately small fixture without treating gaps as cadence errors."""
    by_region: dict[str, list[DemandRecord]] = defaultdict(list)
    for record in records:
        by_region[record.region_id].append(record)
    if any(len(values) < 1 for values in by_region.values()):
        raise ValidationError("truncated fixture contains an empty region")
    keys = [(record.region_id, record.interval_datetime) for record in records]
    if len(keys) != len(set(keys)):
        raise ValidationError("duplicate region/interval keys")
    return {
        "total_records": len(records),
        "records_by_region": dict(sorted(Counter(record.region_id for record in records).items())),
        "duplicate_keys": 0,
        "missing_required_fields": 0,
        "negative_observations": [
            {"region": record.region_id, "interval": record.interval_datetime, "mw": record.operational_demand}
            for record in records if record.operational_demand < 0
        ],
        "zero_demand_observations": sum(record.operational_demand == 0 for record in records),
        "nonzero_adjustment_records": sum(record.operational_demand_adjustment != 0 for record in records),
        "nonzero_wdr_records": sum(record.wdr_estimate != 0 for record in records),
        "time_ranges_by_region": {
            region: {"first": min(record.interval_datetime for record in values),
                     "last": max(record.interval_datetime for record in values)}
            for region, values in sorted(by_region.items())
        },
        "demand_range_mw_by_region": {
            region: {"min_mw": min(record.operational_demand for record in values),
                     "max_mw": max(record.operational_demand for record in values)}
            for region, values in sorted(by_region.items())
        },
    }


def load_nem_records(input_path: Path) -> list[DemandRecord]:
    """Load validated NEM records in memory without writing extracted files."""
    validate_nem_archive(input_path)
    with zipfile.ZipFile(input_path) as outer:
        records: list[DemandRecord] = []
        for info in outer.infolist():
            nested_bytes = _read_bounded(outer, info, MAX_ARCHIVE_UNCOMPRESSED_BYTES)
            with zipfile.ZipFile(io.BytesIO(nested_bytes)) as nested:
                csv_info = next(item for item in nested.infolist() if not item.is_dir())
                csv_bytes = _read_bounded(nested, csv_info, MAX_MEMBER_UNCOMPRESSED_BYTES)
                records.extend(_parse_csv_member(csv_bytes, info.filename, csv_info.filename))
    return records


def _trading_date(interval: datetime) -> datetime.date:
    """Map the 04:30 market-day boundary to its source trading date."""
    if interval.time() < datetime.strptime("04:30", "%H:%M").time():
        return (interval - timedelta(days=1)).date()
    return interval.date()


def validate_nem_collection(input_paths: Iterable[Path]) -> dict[str, object]:
    """Validate an ordered set of monthly archives and their boundaries."""
    paths = sorted(input_paths, key=lambda path: path.name)
    if not paths:
        raise ValidationError("no NEM archives supplied")
    monthly: list[dict[str, object]] = []
    all_records: list[DemandRecord] = []
    previous_last: dict[str, datetime] = {}
    for path in paths:
        match = re.search(r"_(\d{4})(\d{2})01\.zip$", path.name)
        if not match:
            raise ValidationError(f"cannot derive archive month from filename: {path.name}")
        year, month = int(match.group(1)), int(match.group(2))
        records = load_nem_records(path)
        parsed = [datetime.strptime(r.interval_datetime, "%Y/%m/%d %H:%M:%S") for r in records]
        trading_dates = {_trading_date(value) for value in parsed}
        expected_days = calendar.monthrange(year, month)[1]
        expected_dates = {
            date(year, month, day) for day in range(1, expected_days + 1)
        }
        outside = sorted(str(value) for value in trading_dates - expected_dates)
        missing = sorted(str(value) for value in expected_dates - trading_dates)
        by_region = Counter(record.region_id for record in records)
        for region in EXPECTED_REGIONS:
            region_times = sorted(
                datetime.strptime(r.interval_datetime, "%Y/%m/%d %H:%M:%S")
                for r in records if r.region_id == region
            )
            if len(region_times) != expected_days * 48:
                raise ValidationError(
                    f"{path.name} {region} has {len(region_times)} records; "
                    f"expected {expected_days * 48}"
                )
            if region in previous_last and region_times[0] - previous_last[region] != timedelta(minutes=30):
                raise ValidationError(
                    f"interarchive cadence gap for {region}: "
                    f"{previous_last[region]} to {region_times[0]}"
                )
            previous_last[region] = region_times[-1]
        if outside or missing:
            raise ValidationError(
                f"{path.name} trading-date completeness failed; missing={missing}, outside={outside}"
            )
        monthly.append(
            {
                "archive": path.name,
                "month": f"{year:04d}-{month:02d}",
                "expected_calendar_days": expected_days,
                "nested_daily_members": len({r.source_member for r in records}),
                "distinct_trading_dates": len(trading_dates),
                "first_interval": min(parsed).strftime("%Y/%m/%d %H:%M:%S"),
                "last_interval": max(parsed).strftime("%Y/%m/%d %H:%M:%S"),
                "records": len(records),
                "records_by_region": dict(sorted(by_region.items())),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
        all_records.extend(records)
    keys = [(r.region_id, r.interval_datetime) for r in all_records]
    if len(keys) != len(set(keys)):
        raise ValidationError("duplicate region/interval keys across NEM archives")
    return {
        "archives": monthly,
        "total_records": len(all_records),
        "expected_records": sum(item["expected_calendar_days"] * 48 * 5 for item in monthly),
        "continuous_boundaries": True,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate GridPulse source evidence")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-nem", help="validate an AEMO NEM monthly archive")
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--complete-month", action="store_true")
    validate.add_argument("--allow-truncated", action="store_true")
    collection = commands.add_parser("validate-nem-collection", help="validate monthly archive continuity")
    collection.add_argument("--input", type=Path, nargs="+", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "validate-nem":
            summary = validate_nem_archive(
                args.input,
                complete_month=args.complete_month,
                allow_truncated=args.allow_truncated,
            )
        else:
            summary = validate_nem_collection(args.input)
    except ValidationError as error:
        print(f"validation failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
