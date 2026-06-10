#!/usr/bin/env python
"""Mine a BPMN model from an XES log using the repo's SplitMiner tools.

This is a bootstrap helper for new logs: it creates the BPMN file in the exact
location the main pipeline expects, so later pipeline runs can use
``--no-update_gen`` or at least start from an existing BPMN artifact.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from datetime import datetime, timezone
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

from lxml import etree
from lxml.builder import ElementMaker
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from support_modules.writers import xml_writer

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
NS = {"bpmn": BPMN_NS}
QBP_NS = "http://www.qbp-simulator.com/Schema201212"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mine a BPMN model from an XES event log."
    )
    parser.add_argument(
        "--file",
        required=True,
        help="XES filename inside input_files/event_logs, or a direct path to an XES file.",
    )
    parser.add_argument(
        "--mining-alg",
        default="sm1",
        choices=["sm1", "sm2", "sm3"],
        help="Mining algorithm to use.",
    )
    parser.add_argument(
        "--epsilon",
        type=float,
        default=0.5,
        help="SplitMiner epsilon parameter for sm1/sm3.",
    )
    parser.add_argument(
        "--eta",
        type=float,
        default=0.5,
        help="SplitMiner eta parameter for sm1/sm3.",
    )
    parser.add_argument(
        "--concurrency",
        type=float,
        default=0.5,
        help="SplitMiner concurrency parameter for sm2.",
    )
    return parser.parse_args()


def load_properties(repo_root: Path) -> dict:
    with open(repo_root / "properties.yml", "r", encoding="utf-8") as handle:
        properties = yaml.load(handle, Loader=yaml.FullLoader)
    paths = {
        key: repo_root / Path(*value.split("\\"))
        for key, value in properties["paths"].items()
    }
    return {**properties, "paths": paths}


def resolve_input_log(repo_root: Path, file_arg: str) -> Path:
    candidate = Path(file_arg)
    if candidate.exists():
        return candidate.resolve()
    return (repo_root / "input_files" / "event_logs" / file_arg).resolve()


def build_output_base(repo_root: Path, stem: str) -> Path:
    output_dir = repo_root / "input_files" / "bpmn_models"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / stem


def build_command(props: dict, input_log: Path, output_base: Path, args: argparse.Namespace) -> list[str]:
    paths = props["paths"]
    system = platform.system().lower()
    sep = ";" if system == "windows" else ":"

    if args.mining_alg == "sm1":
        return [
            "java",
            "-jar",
            str(paths["sm1_path"]),
            str(args.epsilon),
            str(args.eta),
            str(input_log),
            str(output_base),
        ]
    if args.mining_alg == "sm2":
        command = ["java"]
        if system != "windows":
            command.append("-Xmx2G")
        command.extend(
            [
                "-cp",
                str(paths["sm2_path"]) + sep + os.path.join("external_tools", "splitminer2", "lib", "*"),
                "au.edu.unimelb.services.ServiceProvider",
                "SM2",
                str(input_log),
                str(output_base),
                str(args.concurrency),
            ]
        )
        return command

    command = ["java"]
    if system != "windows":
        command.extend(["-Xmx2G", "-Xss8G"])
    command.extend(
        [
            "-cp",
            str(paths["sm3_path"]) + sep + os.path.join("external_tools", "splitminer3", "lib", "*"),
            "au.edu.unimelb.services.ServiceProvider",
            "SMD",
            str(args.epsilon),
            str(args.eta),
            "false",
            "false",
            "false",
            str(input_log),
            str(output_base),
        ]
    )
    return command


def qname(tag: str) -> str:
    return f"{{{BPMN_NS}}}{tag}"


def local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def parse_xes_datetime(raw_value: str) -> datetime:
    normalized = raw_value.replace("Z", "+00:00")
    dt_value = datetime.fromisoformat(normalized)
    if dt_value.tzinfo is None:
        return dt_value.replace(tzinfo=timezone.utc)
    return dt_value


def extract_log_statistics(xes_path: Path) -> dict:
    tree = ET.parse(xes_path)
    root = tree.getroot()

    task_durations = defaultdict(list)
    trace_starts = []
    num_traces = 0

    for trace in root.iter():
        if local_name(trace.tag) != "trace":
            continue
        num_traces += 1
        events = []
        for event in trace:
            if local_name(event.tag) != "event":
                continue
            payload = {}
            for attr in event:
                key = attr.attrib.get("key")
                value = attr.attrib.get("value")
                if key is not None:
                    payload[key] = value
            if "concept:name" not in payload or "time:timestamp" not in payload:
                continue
            events.append(
                {
                    "task": payload["concept:name"],
                    "lifecycle": payload.get("lifecycle:transition", "complete").lower(),
                    "timestamp": parse_xes_datetime(payload["time:timestamp"]),
                }
            )
        if not events:
            continue

        lifecycle_order = {"start": 0, "complete": 1}
        events.sort(key=lambda item: (item["timestamp"], lifecycle_order.get(item["lifecycle"], 2)))
        trace_starts.append(events[0]["timestamp"])
        open_events = defaultdict(deque)
        for event in events:
            if event["lifecycle"] == "start":
                open_events[event["task"]].append(event["timestamp"])
                continue
            if open_events[event["task"]]:
                start_time = open_events[event["task"]].popleft()
                duration = max((event["timestamp"] - start_time).total_seconds(), 0.0)
                task_durations[event["task"]].append(duration)

    trace_starts.sort()
    if len(trace_starts) > 1:
        inter_arrivals = [
            max((curr - prev).total_seconds(), 1.0)
            for prev, curr in zip(trace_starts, trace_starts[1:])
        ]
        arrival_mean = sum(inter_arrivals) / len(inter_arrivals)
    else:
        arrival_mean = 3600.0

    return {
        "arrival_mean": max(arrival_mean, 1.0),
        "task_durations": {
            task: max(sum(values) / len(values), 0.0)
            for task, values in task_durations.items()
            if values
        },
        "num_traces": max(num_traces, 1),
        "start_time": (
            trace_starts[0].isoformat(timespec="microseconds")
            if trace_starts
            else datetime.now(timezone.utc).isoformat(timespec="microseconds")
        ),
    }


def ensure_start_end_tasks(bpmn_path: Path) -> None:
    tree = ET.parse(bpmn_path)
    root = tree.getroot()
    process = root.find("bpmn:process", NS)
    if process is None:
        raise ValueError(f"No BPMN process found in {bpmn_path}")

    tasks = process.findall("bpmn:task", NS)
    has_start_task = any(task.get("name") == "Start" for task in tasks)
    has_end_task = any(task.get("name") == "End" for task in tasks)
    if has_start_task and has_end_task:
        return

    start_event = process.find("bpmn:startEvent", NS)
    end_event = process.find("bpmn:endEvent", NS)
    if start_event is None or end_event is None:
        raise ValueError("BPMN must contain both startEvent and endEvent")

    sequence_flows = process.findall("bpmn:sequenceFlow", NS)
    start_outgoing = [
        flow for flow in sequence_flows if flow.get("sourceRef") == start_event.get("id")
    ]
    end_incoming = [
        flow for flow in sequence_flows if flow.get("targetRef") == end_event.get("id")
    ]
    if not start_outgoing or not end_incoming:
        raise ValueError("BPMN start/end events do not have expected sequence flows")

    start_task_id = "script_added_start_task"
    end_task_id = "script_added_end_task"

    if not has_start_task:
        start_task = ET.Element(qname("task"), {"id": start_task_id, "name": "Start"})
        process.insert(list(process).index(start_event) + 1, start_task)
        for flow in start_outgoing:
            flow.set("sourceRef", start_task_id)
        process.append(
            ET.Element(
                qname("sequenceFlow"),
                {
                    "id": "script_added_start_flow",
                    "name": "",
                    "sourceRef": start_event.get("id"),
                    "targetRef": start_task_id,
                },
            )
        )

    if not has_end_task:
        end_task = ET.Element(qname("task"), {"id": end_task_id, "name": "End"})
        process.insert(list(process).index(end_event), end_task)
        for flow in end_incoming:
            flow.set("targetRef", end_task_id)
        process.append(
            ET.Element(
                qname("sequenceFlow"),
                {
                    "id": "script_added_end_flow",
                    "name": "",
                    "sourceRef": end_task_id,
                    "targetRef": end_event.get("id"),
                },
            )
        )

    tree.write(bpmn_path, encoding="UTF-8", xml_declaration=True)


def remove_existing_simulation_info(bpmn_path: Path) -> None:
    tree = etree.parse(str(bpmn_path))
    root = tree.getroot()
    qbp_nodes = root.xpath("//*[local-name()='processSimulationInfo' and namespace-uri()=$ns]", ns=QBP_NS)
    for node in qbp_nodes:
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
    tree.write(str(bpmn_path), encoding="UTF-8", pretty_print=True, xml_declaration=True)


def build_default_timetables():
    qbp = ElementMaker(namespace=QBP_NS, nsmap={"qbp": QBP_NS})
    return qbp.timetables(
        qbp.timetable(
            qbp.rules(
                qbp.rule(
                    fromTime="00:00:00.000+00:00",
                    toTime="23:59:59.999+00:00",
                    fromWeekDay="MONDAY",
                    toWeekDay="SUNDAY",
                )
            ),
            id="ARRIVAL_TIMETABLE",
            default="true",
            name="ARRIVAL_TIMETABLE",
        ),
        qbp.timetable(
            qbp.rules(
                qbp.rule(
                    fromTime="00:00:00.000+00:00",
                    toTime="23:59:59.999+00:00",
                    fromWeekDay="MONDAY",
                    toWeekDay="SUNDAY",
                )
            ),
            id="QBP_RES_DEFAULT_TIMETABLE",
            default="false",
            name="24/7",
        ),
    )


def collect_bpmn_simulation_inputs(bpmn_path: Path, log_stats: dict) -> dict:
    tree = ET.parse(bpmn_path)
    root = tree.getroot()
    process = root.find("bpmn:process", NS)
    if process is None:
        raise ValueError(f"No BPMN process found in {bpmn_path}")

    task_tags = {
        "task",
        "userTask",
        "manualTask",
        "serviceTask",
        "scriptTask",
        "sendTask",
        "receiveTask",
        "businessRuleTask",
    }
    tasks = []
    for elem in process:
        if local_name(elem.tag) in task_tags and elem.attrib.get("id"):
            tasks.append({"id": elem.attrib["id"], "name": elem.attrib.get("name", elem.attrib["id"])})

    flows = []
    outgoing_counts = defaultdict(int)
    for elem in process:
        if local_name(elem.tag) == "sequenceFlow" and elem.attrib.get("id"):
            flow = {
                "id": elem.attrib["id"],
                "sourceRef": elem.attrib.get("sourceRef"),
                "targetRef": elem.attrib.get("targetRef"),
            }
            flows.append(flow)
            outgoing_counts[flow["sourceRef"]] += 1

    elements_data = []
    for task in tasks:
        duration = log_stats["task_durations"].get(task["name"], 0.0)
        elements_data.append(
            {
                "id": f"qbp_el_{task['id']}",
                "elementid": task["id"],
                "type": "FIXED",
                "mean": str(round(duration, 4)),
                "arg1": "0",
                "arg2": "0",
                "resource": "QBP_DEFAULT_RESOURCE",
            }
        )

    sequences = []
    for flow in flows:
        fan_out = max(outgoing_counts[flow["sourceRef"]], 1)
        sequences.append(
            {
                "elementid": flow["id"],
                "prob": round(1.0 / fan_out, 4),
            }
        )

    return {
        "arrival_rate": {
            "dname": "FIXED",
            "dparams": {
                "mean": round(log_stats["arrival_mean"], 4),
                "arg1": 0,
                "arg2": 0,
            },
        },
        "resource_pool": [
            {
                "id": "QBP_DEFAULT_RESOURCE",
                "name": "SYSTEM",
                "total_amount": "1",
                "costxhour": "20",
                "timetable_id": "QBP_RES_DEFAULT_TIMETABLE",
            }
        ],
        "elements_data": elements_data,
        "sequences": sequences,
        "instances": log_stats["num_traces"],
        "start_time": log_stats["start_time"],
        "time_table": build_default_timetables(),
    }


def ensure_simulation_parameters(bpmn_path: Path, xes_path: Path) -> None:
    log_stats = extract_log_statistics(xes_path)
    parameters = collect_bpmn_simulation_inputs(bpmn_path, log_stats)
    remove_existing_simulation_info(bpmn_path)
    xml_writer.print_parameters(str(bpmn_path), str(bpmn_path), parameters)


def write_meta_file(output_base: Path) -> None:
    metadata_path = output_base.with_name(f"{output_base.name}_meta.json")
    metadata = {
        "alg_manag": "replacement",
        "gate_management": "equiprobable",
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "similarity": 0.0,
    }
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=4)
        handle.write("\n")


def main() -> None:
    args = parse_args()
    repo_root = REPO_ROOT
    props = load_properties(repo_root)
    input_log = resolve_input_log(repo_root, args.file)
    if not input_log.exists():
        raise FileNotFoundError(f"Input log not found: {input_log}")

    output_base = build_output_base(repo_root, input_log.stem)
    command = build_command(props, input_log, output_base, args)

    print(f"Mining BPMN for: {input_log.name}")
    print(f"Output BPMN base: {output_base}")
    subprocess.run(command, check=True, cwd=repo_root)

    bpmn_path = output_base.with_suffix(".bpmn")
    if not bpmn_path.exists():
        raise FileNotFoundError(
            f"Mining command finished but BPMN was not created: {bpmn_path}"
        )
    ensure_start_end_tasks(bpmn_path)
    ensure_simulation_parameters(bpmn_path, input_log)
    write_meta_file(output_base)
    print(f"Created BPMN: {bpmn_path}")


if __name__ == "__main__":
    main()
