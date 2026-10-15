"""Add event-only native logging to generated combat graphs for a test build.

Does not force quest state, skip tool cleanup, or start combat. The native
ExecuteConsoleString contract is shipped in utils/debug/DelayedConsoleExecution.
"""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from campaign_quest_graph import xml, edge, constant
from build_horse_trader_test import rewrite, digest


def log(nodes, name, event, message):
    if nodes.find("*[@Name='" + name + "']") is not None:
        raise ValueError('Diagnostic already exists: ' + name)
    n = E.SubElement(nodes, 'Function', Name=name,
        MethodName='wh::conceptmodule::ExecuteConsoleString', DeclaringType='wh::conceptmodule')
    edge(n, event, 'Exec')
    constant(n, 'Command', '#System.LogAlways(' + json.dumps('GM_COMBAT ' + message) + ')')


def instrument(files):
    changes, events = {}, []
    for path, data in files.items():
        root = E.fromstring(data)
        host = root.find('./Skald/Module')
        if host is None or not host.get('Name', '').startswith('gm_combat_'):
            continue
        nodes = host.find('Nodes')
        if nodes.find("State[@Name='pending']") is None:
            continue
        sources = ['request', 'accept.True', 'accept.False', 'dialogue_finished', 'begin.True',
                   'begin.False', 'begin_after_dialogue.True', 'begin_after_dialogue.False',
                   'initialize.A', 'initialize.D', 'cancel', 'take_won.True', 'take_lost.True',
                   'take_distance_lost.True', 'all_stopped_order.B', 'combat_history.OnCombatHistoryBegins']
        if nodes.find("State[@Name='preparing']") is not None:
            sources += ['prepare_order.B', 'prepared', 'prepared_pending.True',
                        'prepared_pending.False', 'prepared_finish.True', 'prepared_finish.False']
        for index, event in enumerate(sources):
            log(nodes, 'gm_trace_' + str(index), event, host.get('Name') + ' ' + event)
        # Sample each gate separately at request/release. An event trace alone
        # cannot distinguish a stale dialogue latch from an already active fight.
        for index, value in enumerate(['dialogue_busy', 'pending.State', 'fighting.State', 'stopping.State']):
            n = E.SubElement(nodes, 'If', Name='gm_trace_gate_' + str(index))
            edge(n, 'request', 'Exec'); edge(n, 'dialogue_finished', 'Exec')
            edge(n, value, 'Condition')
            for result in ('True', 'False'):
                log(nodes, n.get('Name') + '_' + result, n.get('Name') + '.' + result,
                    host.get('Name') + ' ' + value + '=' + result)
        changes[path] = xml(root)
        events += sources
    if not changes:
        raise ValueError('No generated combat lifecycle found')
    # The container trace verifies source effects actually reach the quest,
    # independently of whether that objective was already Started.
    for path, data in files.items():
        root = E.fromstring(data)
        for kind in ('Project', 'Level'):
            host = root.find('./Skald/' + kind)
            if host is None: continue
            nodes = host.find('Nodes')
            if nodes is None: continue
            stems = [n.get('Name') for n in nodes if n.tag.startswith('gm_combat_')
                     and n.find("Edge[@To='request']") is not None]
            if not stems: continue
            sources = set()
            for stem in stems:
                instance = nodes.find("*[@Name='" + stem + "']")
                request = instance.find("Edge[@To='request']").get('From')
                sources.add(request)
                for n in nodes:
                    if n.get('Name', '').startswith(stem + '_busy_') and n.tag == 'State':
                        sources.update(e.get('From') for e in n.findall('Edge'))
                sources.update(stem + '.' + p for p in ['requested', 'prepare', 'started', 'engaged'])
                for phase in ('prepare', 'privacy', 'routine'):
                    sources.update(stem + '_work_' + phase + '_enable.' + result for result in ('Success', 'Fail'))
                quest_name, _, port = request.partition('.')
                if port.startswith('combat_start_'):
                    quest = nodes.find("*[@Name='" + quest_name + "']")
                    start = 'start_' + port.removeprefix('combat_start_')
                    sources.update(e.get('From') for e in quest.findall('Edge') if e.get('To') == start)
            for index, event in enumerate(sorted(sources)):
                log(nodes, 'gm_trace_container_' + str(index), event, host.get('Name') + ' ' + event)
            changes[path] = xml(root)
    return changes, events


def build(archive, output):
    if output.exists(): raise FileExistsError(output)
    with zipfile.ZipFile(archive) as z:
        files = {n: z.read(n) for n in z.namelist() if n.startswith('Quests/') and n.endswith('.xml')}
    changes, events = instrument(files)
    output.mkdir(parents=True)
    target = output / archive.name
    rewrite(archive, target, changes)
    with zipfile.ZipFile(target) as z:
        if z.testzip(): raise ValueError('Diagnostic archive CRC failure')
    report = dict(baseline=digest(archive), package=digest(target), files=sorted(changes),
                  events=events, runtime_verified=False, diagnostic_only=True)
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(build(a.archive, a.output), indent=2))
