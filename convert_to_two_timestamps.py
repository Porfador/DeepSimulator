# Note: This code created by Claude to change .xes files with single timestamp to double timestamp by putting the time both start and end.
# -*- coding: utf-8 -*-
"""
Converts a one-timestamp XES event log to a two-timestamp format
compatible with DeepSimulator by duplicating each event as
'start' and 'complete' with the same timestamp.

Usage:
    python convert_to_two_timestamps.py <input_xes> <output_xes>

Example:
    python convert_to_two_timestamps.py \
        input_files/event_logs/RequestForPayment.xes \
        input_files/event_logs/RequestForPayment_two_ts.xes
"""

import sys
import copy
import xml.etree.ElementTree as ET


def convert_one_to_two_timestamps(input_path: str, output_path: str) -> None:
    print(f"Reading: {input_path}")

    ET.register_namespace('', 'http://www.xes-standard.org')
    tree = ET.parse(input_path)
    root = tree.getroot()

    # Detect namespace prefix (e.g. '{http://www.xes-standard.org}')
    ns = ''
    if root.tag.startswith('{'):
        ns = root.tag.split('}')[0] + '}'

    tag_trace = f'{ns}trace'
    tag_event = f'{ns}event'
    tag_string = f'{ns}string'

    total_original = 0
    total_converted = 0

    for trace in root.findall(tag_trace):
        events = trace.findall(tag_event)
        total_original += len(events)

        # Remove existing events from trace
        for event in events:
            trace.remove(event)

        # Re-insert each event twice: start + complete
        for event in events:
            for lifecycle in ('start', 'complete'):
                new_event = copy.deepcopy(event)
                lc_elem = ET.SubElement(new_event, tag_string)
                lc_elem.set('key', 'lifecycle:transition')
                lc_elem.set('value', lifecycle)
                trace.append(new_event)
                total_converted += 1

    print(f"Writing: {output_path}")
    tree.write(output_path, encoding='UTF-8', xml_declaration=True)

    print("Done.")
    print(f"  Original events : {total_original}")
    print(f"  Converted events: {total_converted} (x2 — start + complete per event)")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        convert_one_to_two_timestamps(sys.argv[1], sys.argv[2])
    else:
        input_xes  = "input_files/event_logs/RequestForPayment.xes"
        output_xes = "input_files/event_logs/RequestForPayment_two_ts.xes"
        convert_one_to_two_timestamps(input_xes, output_xes)
