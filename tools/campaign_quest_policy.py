"""Lower the source completion policies the emitter leaves in its report.

Call after quest emission. Only untracked objectives are handled here; counted
tracking belongs to campaign_quest_tracking. Two shapes are accepted:

- condition '0' with no timeout never completes by itself. Nothing is emitted;
  the objective keeps its source completion path (script or dialogue).
- condition '1' with an autocomplete timeout that names its clock. The emitter
  already accepts '<n>[smh] #GT'; this adds the other retail-supported units
  and the world clock ('#WT'), using the same guarded native Timer.

A timeout without a clock suffix, any expiration timeout and any expression
stay pending. Not runtime-verified.
"""
import re
import xml.etree.ElementTree as ET

from campaign_objective_conditions import counted_asset
from campaign_quest_graph import constant, edge, xml

PREFIX = 'lowered_policy_'
UNSET = ('', '-1', None)
# Whole numbers only: retail Durations are '<n>ms|s|m|h|d' and no fractional
# native duration has been observed.
TIMEOUT = re.compile(r'\s*(\d+)\s*(ms|s|m|h|d)\s*#(GT|WT)\s*')
CLOCK = dict(GT='GameTime', WT='WorldTime')


def plan(model):
    tracked = model['tables'].get('quest_tracked_asset', {}).get('rows', [])
    converted, pending = [], []
    for row in model['tables']['quest_objective']['rows']:
        oid = row['objective_id']
        if any(t['objective_id'] == oid and counted_asset(t) for t in tracked):
            continue
        condition = (row.get('condition') or '').strip()
        timeout, expiration = row.get('autocomplete_timeout_str'), row.get('expiration_timeout_str')
        record = dict(objective_id=oid, objective=row['objective_name'])
        if expiration not in UNSET or row.get('time', '0') not in ('', '0'):
            pending.append(dict(record, reason='expiration timeout')); continue
        if timeout in UNSET:
            if condition == '0':
                converted.append(dict(record, policy='never_automatic'))
            continue
        match = TIMEOUT.fullmatch(timeout)
        if condition != '1':
            pending.append(dict(record, reason='timeout without a constant-true condition'))
        elif match is None:
            pending.append(dict(record, reason='timeout without a named clock: ' + timeout))
        else:
            converted.append(dict(record, policy='timed', duration=match[1] + match[2], clock=CLOCK[match[3]]))
    return dict(converted=converted, pending=pending, runtime_verified=False)


def bind(blob, model):
    report = plan(model)
    root = ET.fromstring(blob)
    quest = root.find('./Skald/Quest')
    if quest is None or quest.get('Name') != model['quest']:
        raise ValueError('Destination quest identity mismatch')
    nodes = quest.find('Nodes')
    if any(n.get('Name', '').startswith(PREFIX) for n in nodes):
        raise ValueError('Completion policy already lowered')
    changed = False
    for record in report['converted']:
        if record['policy'] != 'timed':
            continue
        oid = record['objective_id']; state_name = 'objective_' + oid
        state = nodes.find("State[@Name='" + state_name + "']")
        if state is None:
            raise ValueError('Missing native objective state ' + oid)
        if nodes.find("Timer[@Name='complete_" + oid + "_queued']") is not None:
            record['policy'] = 'timed_by_emitter'
            continue
        timer = ET.SubElement(nodes, 'Timer', Name=PREFIX + oid + '_timer')
        constant(timer, 'Duration', record['duration']); constant(timer, 'TimeType', record['clock'])
        edge(timer, state_name + '.OnStarted', 'SetRunning')
        for status in ('Completed', 'Failed', 'Canceled', 'Unchanged'):
            edge(timer, state_name + '.On' + status, 'SetStopped')
        gate = ET.SubElement(nodes, 'If', Name=PREFIX + oid + '_if_started')
        edge(gate, state_name + '.Started', 'Condition')
        edge(gate, PREFIX + oid + '_timer.OnFinished', 'Exec')
        edge(state, PREFIX + oid + '_if_started.True', 'SetCompleted')
        changed = True
    return (xml(root) if changed else blob), report
