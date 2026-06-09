#!/usr/bin/env python
"""Create prepared event logs from one-timestamp XES or CSV inputs.

For XES input, the script turns each original event into a pair of lifecycle
events and also injects synthetic ``Start`` and ``End`` activities per trace.

- ``start`` at the original timestamp
- ``complete`` at a random timestamp 30 to 60 minutes later

For CSV input, the script keeps the original timestamp as ``start_timestamp``
and adds an artificial ``end_timestamp`` 30 to 60 minutes later.
"""

from __future__ import annotations

import argparse
import copy
import random
from datetime import timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

import pandas as pd


XES_NS = ""
LIFECYCLE_URI = "http://www.xes-standard.org/lifecycle.xesext"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a one-timestamp XES log or CSV log into a prepared "
            "two-timestamp version."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the source XES or CSV log.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Path to the converted XES log. Defaults to the input filename "
            "with '_prepared' appended before the extension."
        ),
    )
    parser.add_argument(
        "--min-minutes",
        type=int,
        default=30,
        help="Minimum artificial processing time in minutes.",
    )
    parser.add_argument(
        "--max-minutes",
        type=int,
        default=60,
        help="Maximum artificial processing time in minutes.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible artificial durations.",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help=(
            "Optional limit on the number of cases/traces to keep. For XES, "
            "this keeps only the first N traces. For CSV, it keeps only the "
            "first N case ids if a 'caseid' column exists, otherwise the "
            "first N rows."
        ),
    )
    return parser.parse_args()


def ensure_lifecycle_extension(root: ET.Element) -> None:
    has_lifecycle = any(
        child.tag == "extension" and child.attrib.get("prefix") == "lifecycle"
        for child in root.findall("extension")
    )
    if not has_lifecycle:
        extension = ET.Element(
            "extension",
            {
                "name": "Lifecycle",
                "prefix": "lifecycle",
                "uri": LIFECYCLE_URI,
            },
        )
        insert_at = 0
        for index, child in enumerate(list(root)):
            if child.tag == "extension":
                insert_at = index + 1
            else:
                break
        root.insert(insert_at, extension)


def find_timestamp(event: ET.Element) -> ET.Element:
    for child in event.findall("date"):
        if child.attrib.get("key") == "time:timestamp":
            return child
    raise ValueError("Event is missing required 'time:timestamp' attribute")


def format_timestamp(dt) -> str:
    text = dt.isoformat(timespec="milliseconds")
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text


def add_lifecycle_event_pair(
    event: ET.Element,
    rng: random.Random,
    min_minutes: int,
    max_minutes: int,
) -> list[ET.Element]:
    timestamp_node = find_timestamp(event)
    start_dt = parse_xes_timestamp(timestamp_node.attrib["value"])
    duration_minutes = rng.randint(min_minutes, max_minutes)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    start_event = copy.deepcopy(event)
    complete_event = copy.deepcopy(event)

    find_timestamp(start_event).set("value", format_timestamp(start_dt))
    find_timestamp(complete_event).set("value", format_timestamp(end_dt))

    ET.SubElement(
        start_event,
        "string",
        {"key": "lifecycle:transition", "value": "start"},
    )
    ET.SubElement(
        complete_event,
        "string",
        {"key": "lifecycle:transition", "value": "complete"},
    )

    return [start_event, complete_event]


def build_boundary_event(
    template_event: ET.Element,
    activity_name: str,
    lifecycle_value: str,
    timestamp_value: str,
) -> ET.Element:
    event = ET.Element("event")
    for child in template_event:
        key = child.attrib.get("key")
        if child.tag == "date" and key == "time:timestamp":
            ET.SubElement(event, "date", {"key": key, "value": timestamp_value})
        elif child.tag == "string" and key == "concept:name":
            ET.SubElement(event, "string", {"key": key, "value": activity_name})
        elif child.tag == "string" and key == "lifecycle:transition":
            ET.SubElement(event, "string", {"key": key, "value": lifecycle_value})
        elif child.tag == "string" and key == "org:resource":
            ET.SubElement(event, "string", {"key": key, "value": "SYSTEM"})
        elif child.tag == "string" and key == "org:role":
            ET.SubElement(event, "string", {"key": key, "value": "SYSTEM"})
        else:
            ET.SubElement(event, child.tag, dict(child.attrib))
    if not any(
        child.tag == "string" and child.attrib.get("key") == "lifecycle:transition"
        for child in event
    ):
        ET.SubElement(
            event,
            "string",
            {"key": "lifecycle:transition", "value": lifecycle_value},
        )
    return event


def add_boundary_events(transformed_events: list[ET.Element]) -> list[ET.Element]:
    if not transformed_events:
        return transformed_events

    first_event = transformed_events[0]
    last_event = transformed_events[-1]
    first_timestamp = parse_xes_timestamp(find_timestamp(first_event).attrib["value"])
    last_timestamp = parse_xes_timestamp(find_timestamp(last_event).attrib["value"])

    start_start = first_timestamp - timedelta(minutes=2)
    start_complete = first_timestamp - timedelta(minutes=1)
    end_start = last_timestamp + timedelta(minutes=1)
    end_complete = last_timestamp + timedelta(minutes=2)

    boundary_events = [
        build_boundary_event(first_event, "Start", "start", format_timestamp(start_start)),
        build_boundary_event(first_event, "Start", "complete", format_timestamp(start_complete)),
        *transformed_events,
        build_boundary_event(last_event, "End", "start", format_timestamp(end_start)),
        build_boundary_event(last_event, "End", "complete", format_timestamp(end_complete)),
    ]
    return boundary_events


def parse_xes_timestamp(value: str):
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    from datetime import datetime

    return datetime.fromisoformat(normalized)


def convert_log(
    input_path: Path,
    output_path: Path,
    min_minutes: int,
    max_minutes: int,
    seed: int,
    max_cases: int | None,
) -> None:
    if min_minutes <= 0 or max_minutes <= 0:
        raise ValueError("Processing-time bounds must be positive integers.")
    if min_minutes > max_minutes:
        raise ValueError("min-minutes cannot be greater than max-minutes.")
    if max_cases is not None and max_cases <= 0:
        raise ValueError("max-cases must be a positive integer when provided.")

    tree = ET.parse(input_path)
    root = tree.getroot()
    ensure_lifecycle_extension(root)

    rng = random.Random(seed)
    traces = root.findall("trace")
    if max_cases is not None:
        for trace in traces[max_cases:]:
            root.remove(trace)

    for trace in root.findall("trace"):
        original_events = list(trace.findall("event"))
        for event in original_events:
            trace.remove(event)

        transformed_events = []
        for event in original_events:
            transformed_events.extend(
                add_lifecycle_event_pair(event, rng, min_minutes, max_minutes)
            )
        transformed_events = add_boundary_events(transformed_events)

        for event in transformed_events:
            trace.append(event)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_path, encoding="UTF-8", xml_declaration=True)


def resolve_csv_timestamp_column(dataframe: pd.DataFrame) -> str:
    candidates = ["start_timestamp", "time:timestamp", "timestamp"]
    for column in candidates:
        if column in dataframe.columns:
            return column
    raise ValueError(
        "CSV input must contain one of these timestamp columns: "
        "'start_timestamp', 'time:timestamp', or 'timestamp'."
    )


def convert_csv(
    input_path: Path,
    output_path: Path,
    min_minutes: int,
    max_minutes: int,
    seed: int,
    max_cases: int | None,
) -> None:
    dataframe = pd.read_csv(input_path)
    if max_cases is not None:
        if max_cases <= 0:
            raise ValueError("max-cases must be a positive integer when provided.")
        if "caseid" in dataframe.columns:
            case_order = pd.Index(pd.unique(dataframe["caseid"]))
            keep_cases = set(case_order[:max_cases].tolist())
            dataframe = dataframe[dataframe["caseid"].isin(keep_cases)].copy()
        else:
            dataframe = dataframe.head(max_cases).copy()
    timestamp_column = resolve_csv_timestamp_column(dataframe)

    rng = random.Random(seed)
    start_series = pd.to_datetime(dataframe[timestamp_column], utc=False)
    durations = [
        timedelta(minutes=rng.randint(min_minutes, max_minutes))
        for _ in range(len(dataframe))
    ]

    dataframe["start_timestamp"] = start_series
    dataframe["end_timestamp"] = [
        start + duration for start, duration in zip(start_series, durations)
    ]
    dataframe.to_csv(output_path, index=False)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = (
        Path(args.output)
        if args.output is not None
        else input_path.with_name(f"{input_path.stem}_prepared{input_path.suffix}")
    )
    if input_path.suffix.lower() == ".xes":
        convert_log(
            input_path=input_path,
            output_path=output_path,
            min_minutes=args.min_minutes,
            max_minutes=args.max_minutes,
            seed=args.seed,
            max_cases=args.max_cases,
        )
    elif input_path.suffix.lower() == ".csv":
        convert_csv(
            input_path=input_path,
            output_path=output_path,
            min_minutes=args.min_minutes,
            max_minutes=args.max_minutes,
            seed=args.seed,
            max_cases=args.max_cases,
        )
    else:
        raise ValueError("Unsupported input type. Use a .xes or .csv file.")
    print(f"Prepared log written to: {output_path}")


if __name__ == "__main__":
    main()
