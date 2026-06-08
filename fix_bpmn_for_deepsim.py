#This code created by Claude. This is for fixing semi-manually (splitminer was runned by me not by code itself) created .bpmn model for RequestForPayment_two_ts.xes
# -*- coding: utf-8 -*-
"""
Fixes a SplitMiner-generated BPMN so that DeepSimulator can read it.

Problem:
    DeepSimulator's process_structure.py looks for a <task name="Start"/> and
    <task name="End"/> to build the process graph. SplitMiner produces standard
    BPMN with <startEvent> / <endEvent> instead. This mismatch causes:
        IndexError: list index out of range  (no 'start' node found in graph)

Fix:
    1. Find the <startEvent> and its outgoing sequenceFlow target (first real node).
    2. Add <task name="Start"/> and a sequenceFlow Start → first real node.
    3. Find the <endEvent> and its incoming sequenceFlow source (last real node).
    4. Add <task name="End"/> and a sequenceFlow last real node → End.
    The original <startEvent>/<endEvent> are kept so that process_structure.py
    line 66 (edge exclusion logic) continues to work correctly.

Usage:
    python fix_bpmn_for_deepsim.py <input.bpmn> [output.bpmn]
    If output path is omitted, the input file is overwritten in-place.
"""

import sys
import uuid
import xml.etree.ElementTree as ET


BPMN_NS = 'http://www.omg.org/spec/BPMN/20100524/MODEL'


def _tag(local):
    return f'{{{BPMN_NS}}}{local}'


def fix_bpmn(input_path: str, output_path: str) -> None:
    ET.register_namespace('', BPMN_NS)
    ET.register_namespace('dc', 'http://www.omg.org/spec/DD/20100524/DC')
    ET.register_namespace('bpmndi', 'http://www.omg.org/spec/BPMN/20100524/DI')
    ET.register_namespace('di', 'http://www.omg.org/spec/DD/20100524/DI')
    ET.register_namespace('xsi', 'http://www.w3.org/2001/XMLSchema-instance')
    ET.register_namespace('qbp', 'http://www.qbp-simulator.com/Schema201212')

    tree = ET.parse(input_path)
    root = tree.getroot()

    # Locate the <process> element
    process = root.find(_tag('process'))
    if process is None:
        raise ValueError('No <process> element found in BPMN.')

    # --- Collect existing IDs (startEvent, endEvent, sequenceFlows) ----------
    start_event = process.find(_tag('startEvent'))
    end_event   = process.find(_tag('endEvent'))

    if start_event is None or end_event is None:
        print('No <startEvent> or <endEvent> found — nothing to fix.')
        return

    start_event_id = start_event.get('id')
    end_event_id   = end_event.get('id')

    # Find all sequenceFlows
    seq_flows = process.findall(_tag('sequenceFlow'))

    # Edge: startEvent → first_real_node
    start_targets = [sf.get('targetRef')
                     for sf in seq_flows
                     if sf.get('sourceRef') == start_event_id]

    # Edge: last_real_node → endEvent
    end_sources = [sf.get('sourceRef')
                   for sf in seq_flows
                   if sf.get('targetRef') == end_event_id]

    if not start_targets:
        raise ValueError(f'No outgoing sequenceFlow from startEvent ({start_event_id}).')
    if not end_sources:
        raise ValueError(f'No incoming sequenceFlow to endEvent ({end_event_id}).')

    first_real_node = start_targets[0]
    last_real_node  = end_sources[0]

    print(f'startEvent ({start_event_id}) → {first_real_node}')
    print(f'{last_real_node} → endEvent ({end_event_id})')

    # --- Check if Start/End tasks already exist ------------------------------
    existing_task_names = {t.get('name') for t in process.findall(_tag('task'))}
    if 'Start' in existing_task_names and 'End' in existing_task_names:
        print('Start and End tasks already present — nothing to fix.')
        return

    # --- Add <task name="Start"/> and its sequenceFlow -----------------------
    if 'Start' not in existing_task_names:
        start_task_id = 'node_' + str(uuid.uuid4())
        start_task = ET.Element(_tag('task'))
        start_task.set('id', start_task_id)
        start_task.set('name', 'Start')
        process.insert(0, start_task)          # Insert at the top for clarity

        sf_start = ET.SubElement(process, _tag('sequenceFlow'))
        sf_start.set('id', 'node_' + str(uuid.uuid4()))
        sf_start.set('name', '')
        sf_start.set('sourceRef', start_task_id)
        sf_start.set('targetRef', first_real_node)
        print(f'Added <task name="Start" id="{start_task_id}"/> → {first_real_node}')

    # --- Add <task name="End"/> and its sequenceFlow -------------------------
    if 'End' not in existing_task_names:
        end_task_id = 'node_' + str(uuid.uuid4())
        end_task = ET.Element(_tag('task'))
        end_task.set('id', end_task_id)
        end_task.set('name', 'End')
        process.append(end_task)

        sf_end = ET.SubElement(process, _tag('sequenceFlow'))
        sf_end.set('id', 'node_' + str(uuid.uuid4()))
        sf_end.set('name', '')
        sf_end.set('sourceRef', last_real_node)
        sf_end.set('targetRef', end_task_id)
        print(f'{last_real_node} → Added <task name="End" id="{end_task_id}"/>')

    # --- Write output --------------------------------------------------------
    tree.write(output_path, encoding='UTF-8', xml_declaration=True)
    print(f'Saved fixed BPMN to: {output_path}')


if __name__ == '__main__':
    if len(sys.argv) == 3:
        fix_bpmn(sys.argv[1], sys.argv[2])
    elif len(sys.argv) == 2:
        fix_bpmn(sys.argv[1], sys.argv[1])   # in-place
    else:
        # Default: fix the RequestForPayment BPMN in-place
        path = r'input_files\bpmn_models\RequestForPayment_two_ts.bpmn'
        fix_bpmn(path, path)
