# -*- coding: utf-8 -*-
"""
Adds a minimal <qbp:processSimulationInfo> block to a SplitMiner-generated BPMN
so that BIMP (qbp-simulator-engine.jar) can run it.

Why this is needed:
    DeepSimulator's seq_generator.py calls _modify_simulation_model() which
    modifies qbp:processSimulationInfo.processInstances and startDateTime.
    SplitMiner output has no qbp: block, so items[0] throws IndexError.

What this script adds:
    - One 24/7 default resource (QBP_DEFAULT_RESOURCE)
    - FIXED mean=0 duration for every <task> (DeepSimulator overwrites with LSTM)
    - Equal execution probabilities for outgoing flows of Diverging gateways
    - A 24/7 arrival timetable
    - processInstances=1 and startDateTime placeholders (overwritten at runtime)

Usage:
    python add_bimp_params.py <input.bpmn> [output.bpmn]
    If output is omitted, the input file is overwritten in-place.
"""

import sys
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict

BPMN_NS = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
QBP_NS  = 'http://www.qbp-simulator.com/Schema201212'


def _tag(ns, local):
    return f'{{{ns}}}{local}'


def _b(local):  # BPMN tag
    return _tag(BPMN_NS, local)


def _q(local):  # QBP tag
    return _tag(QBP_NS, local)


def add_bimp_params(input_path: str, output_path: str) -> None:
    # Register namespaces so they are preserved in output
    ET.register_namespace('',      BPMN_NS)
    ET.register_namespace('dc',    'http://www.omg.org/spec/DD/20100524/DC')
    ET.register_namespace('bpmndi','http://www.omg.org/spec/BPMN/20100524/DI')
    ET.register_namespace('di',    'http://www.omg.org/spec/DD/20100524/DI')
    ET.register_namespace('xsi',   'http://www.w3.org/2001/XMLSchema-instance')
    ET.register_namespace('qbp',   QBP_NS)

    tree = ET.parse(input_path)
    root = tree.getroot()

    process = root.find(_b('process'))
    if process is None:
        raise ValueError('No <process> element found.')

    # --- Check if qbp block already exists -----------------------------------
    existing = root.find(_q('processSimulationInfo'))
    if existing is not None:
        print('qbp:processSimulationInfo already present — nothing to add.')
        return

    # --- Collect task IDs ----------------------------------------------------
    tasks = process.findall(_b('task'))
    task_ids = [(t.get('id'), t.get('name', '')) for t in tasks]
    print(f'Found {len(task_ids)} tasks.')

    # --- Collect diverging gateway outgoing sequence flows -------------------
    # We need to assign execution probabilities to outgoing flows of gateways
    diverging_gates = []
    for gtype in ('exclusiveGateway', 'inclusiveGateway', 'parallelGateway'):
        for gw in process.findall(_b(gtype)):
            if gw.get('gatewayDirection') == 'Diverging':
                diverging_gates.append(gw.get('id'))

    # Map gateway_id -> list of outgoing sequenceFlow IDs
    all_seq_flows = process.findall(_b('sequenceFlow'))
    gate_outflows = defaultdict(list)
    for sf in all_seq_flows:
        src = sf.get('sourceRef')
        if src in diverging_gates:
            gate_outflows[src].append(sf.get('id'))

    print(f'Found {len(diverging_gates)} diverging gateways.')

    # --- Build <qbp:processSimulationInfo> -----------------------------------
    sim_info = ET.Element(_q('processSimulationInfo'))
    sim_info.set('xmlns:qbp', QBP_NS)
    sim_info.set('id',               'qbp_' + str(uuid.uuid4()).replace('-', '_'))
    sim_info.set('processInstances', '1')          # overwritten at runtime
    sim_info.set('startDateTime',    '2000-01-01T00:00:00.000000+00:00')  # overwritten
    sim_info.set('currency',         'EUR')

    # Arrival rate
    arr = ET.SubElement(sim_info, _q('arrivalRateDistribution'))
    arr.set('type', 'FIXED')
    arr.set('mean', '3600')
    arr.set('arg1', '0')
    arr.set('arg2', '0')
    ET.SubElement(arr, _q('timeUnit')).text = 'seconds'

    # Timetables
    timetables = ET.SubElement(sim_info, _q('timetables'))
    tt = ET.SubElement(timetables, _q('timetable'))
    tt.set('id',      'QBP_DEFAULT_TIMETABLE')
    tt.set('default', 'true')
    tt.set('name',    '24/7')
    rules = ET.SubElement(tt, _q('rules'))
    rule = ET.SubElement(rules, _q('rule'))
    rule.set('fromTime',    '00:00:00.000+00:00')
    rule.set('toTime',      '23:59:59.999+00:00')
    rule.set('fromWeekDay', 'MONDAY')
    rule.set('toWeekDay',   'SUNDAY')

    # Resources
    resources = ET.SubElement(sim_info, _q('resources'))
    res = ET.SubElement(resources, _q('resource'))
    res.set('id',          'QBP_DEFAULT_RESOURCE')
    res.set('name',        'DEFAULT')
    res.set('totalAmount', '10')
    res.set('costPerHour', '1')
    res.set('timetableId', 'QBP_DEFAULT_TIMETABLE')

    # Elements — one per task, FIXED duration = 0
    elements = ET.SubElement(sim_info, _q('elements'))
    for task_id, task_name in task_ids:
        elem = ET.SubElement(elements, _q('element'))
        elem.set('id',        'qbp_' + str(uuid.uuid4()).replace('-', '_'))
        elem.set('elementId', task_id)
        dur = ET.SubElement(elem, _q('durationDistribution'))
        dur.set('type', 'FIXED')
        dur.set('mean', '0')
        dur.set('arg1', '0')
        dur.set('arg2', '0')
        ET.SubElement(dur, _q('timeUnit')).text = 'seconds'
        res_ids = ET.SubElement(elem, _q('resourceIds'))
        ET.SubElement(res_ids, _q('resourceId')).text = 'QBP_DEFAULT_RESOURCE'

    # Sequence flows — equal probability for diverging gateway outgoing flows
    if gate_outflows:
        seq_flows_elem = ET.SubElement(sim_info, _q('sequenceFlows'))
        for gate_id, flow_ids in gate_outflows.items():
            if not flow_ids:
                continue
            prob = round(1.0 / len(flow_ids), 4)
            for flow_id in flow_ids:
                sf_elem = ET.SubElement(seq_flows_elem, _q('sequenceFlow'))
                sf_elem.set('elementId',           flow_id)
                sf_elem.set('executionProbability', str(prob))

    # Append to root (after <process> and diagram elements)
    root.append(sim_info)

    tree.write(output_path, encoding='UTF-8', xml_declaration=True)
    print(f'Saved to: {output_path}')
    print(f'  Tasks with qbp:element entries : {len(task_ids)}')
    print(f'  Gateway outflows with prob      : {sum(len(v) for v in gate_outflows.values())}')


if __name__ == '__main__':
    if len(sys.argv) == 3:
        add_bimp_params(sys.argv[1], sys.argv[2])
    elif len(sys.argv) == 2:
        add_bimp_params(sys.argv[1], sys.argv[1])
    else:
        path = r'input_files\bpmn_models\RequestForPayment_two_ts.bpmn'
        add_bimp_params(path, path)
