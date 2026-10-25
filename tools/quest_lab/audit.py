"""Read-only package-wide diagnostics, with missing coverage kept explicit.

Public-port probes are isolated stimuli, not a synthetic campaign playthrough.
No actor, inventory, dialogue or navigation outcome is supplied implicitly.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path

from . import BudgetExceeded, Unsupported
from .graph import Graph
from .source import Source


def definitions(source):
    return [(path, node) for path, root in sorted(source.files.items()) if root is not None
            for node in root.findall('./Skald/*') if node.get('Name')]


def structural_checks(source):
    """Check node identities and custom interfaces without guessing native ports."""
    entries = definitions(source)
    by_name = defaultdict(list)
    for path, node in entries:
        by_name[node.get('Name')].append((path, node))
    findings, external_inputs = [], []
    edges_checked = 0
    for path, host in entries:
        nodes = {n.get('Name'): n for n in host.findall('Nodes/*')}
        ports = {p.get('Name') for p in host.findall('Ports/*')}
        includes = set()
        for dep in host.findall('Definitions/Definition'):
            try: includes.add(source.reference(dep.get('File', ''), path))
            except Unsupported: pass  # May be an engine-owned dependency outside this package.
        for name, count in Counter(n.get('Name') for n in host.findall('Nodes/*')).items():
            if count > 1 or not name:
                findings.append(dict(file=path, host=host.get('Name'), node=name,
                                     reason='Duplicate or missing node identity'))
        for node in nodes.values():
            for edge in node.findall('Edge'):
                edges_checked += 1
                ref = edge.get('From', '')
                name, sep, port = ref.partition('.')
                evidence = dict(file=path, host=host.get('Name'), node=node.get('Name'), source=ref)
                if not sep:
                    if ref not in ports:
                        external_inputs.append(dict(**evidence, reason='Implicit host/engine input; not classified as a fault'))
                    continue
                if name not in nodes:
                    findings.append(dict(**evidence, reason='Source node does not exist in this definition'))
                    continue
                candidates = by_name[nodes[name].tag]
                local = [(p, d) for p, d in candidates if p in includes]
                if local: candidates = local
                # A port is certainly absent only if every possible custom definition
                # has an explicit interface and none exposes it. Engine ports are unknown.
                if candidates and all(d.find('Ports') is not None for _, d in candidates):
                    allowed = {p.get('Name') for _, d in candidates for p in d.findall('Ports/*')
                               if p.get('Direction') == 'Out'}
                    if port not in allowed:
                        external_inputs.append(dict(**evidence, reason='Custom output not declared; requires native inherited-port review'))
    return dict(definitions=len(entries), edges_checked=edges_checked, findings=findings,
                unresolved_interfaces=external_inputs)


def probe(graph, initial, name, events, advance_hours=0):
    graph.stack.clear()
    graph.restore(initial)
    graph.trace.clear(); graph.events.clear(); graph.visited.clear(); graph.steps = 0
    error = None
    status = 'EXECUTED'
    try:
        for event in events:
            graph.fire(event)
            graph.advance_to(graph.now)
        if advance_hours: graph.advance_to(graph.now + advance_hours * 3600 * 1000000)
    except Unsupported as exc: status, error = 'UNSUPPORTED', str(exc)
    except BudgetExceeded as exc: status, error = 'BUDGET_LIMIT', str(exc)
    except (ValueError, KeyError, TypeError, ZeroDivisionError, OverflowError) as exc:
        status, error = 'ERROR', str(exc)
    return dict(name=name, events=events, advance_hours=advance_hours, status=status, error=error,
                visited=sorted(graph.visited), states=dict(graph.states), time_us=graph.now,
                trace_tail=graph.trace[-12:], trace_events=len(graph.trace))


def quest_audit(source, path, host):
    name = host.get('Name')
    result = dict(name=name, file=path, source_sha256=source.hashes[path],
                  status='NOT_EXECUTABLE', probes=[], native_runtime_verified=False)
    # Journal-only quests sometimes receive progress from a separate same-name
    # module. Diagnose that module too; never count the journal shell as a pass.
    entry_path = path
    if not any(p.get('Type') == 'trigger' and p.get('Direction') == 'In' for p in host.findall('Ports/*')):
        modules = [(p, d) for p, d in source.definitions.get(name, []) if d.tag == 'Module']
        if len(modules) == 1:
            entry_path, _ = modules[0]
            result['logic_file'] = entry_path
    try:
        graph = Graph(source, name, entry_file=entry_path)
        initial = graph.snapshot()
        ports = sorted(p for p in graph.event_ports if '.' not in p)
        result.update(unsupported=graph.unsupported, inputs=ports, nodes=len(graph.nodes),
                      files={p: source.hashes[p] for p in sorted(graph.used_files)})
        startup = [p for p in ('activate', 'start') if p in ports]
        if startup:
            result['probes'].append(probe(graph, initial, 'startup and 24 game hours', startup, 24))
        for port in ports:
            if port in startup: continue
            setup = list(startup)
            # Check each termination callback after its corresponding public start
            # when available. This only tests the local state machinery.
            action, _, objective = port.partition('_')
            begin = 'start_' + objective
            if action in ('complete', 'fail', 'cancel') and objective and begin in ports:
                setup.append(begin)
            result['probes'].append(probe(graph, initial, 'public callback: ' + port, [*setup, port]))
        if not result['probes']:
            result['status'] = 'NO_PUBLIC_TRIGGER'
        elif graph.unsupported or any(p['status'] != 'EXECUTED' for p in result['probes']):
            result['status'] = 'PARTIAL_UNSUPPORTED'
        else:
            result['status'] = 'LOCAL_PROBES_EXECUTED'
        result['probe_counts'] = dict(Counter(p['status'] for p in result['probes']))
        result['visited_nodes'] = len(set(n for p in result['probes'] for n in p['visited']))
    except (Unsupported, ValueError) as exc:
        result.update(status='LOAD_BLOCKED', error=str(exc))
    return result


def audit(source, source_rows=()):
    quests = [quest_audit(source, p, d) for p, d in definitions(source) if d.tag == 'Quest']
    installed = {q['name'] for q in quests}
    source_inventory = [dict(name=r['quest_name'], group=r.get('group', ''), quest_id=r['quest_id'],
                             status='DEFINITION_PRESENT' if r['quest_name'] in installed else 'NOT_PRESENT_IN_PACKAGE')
                        for r in sorted(source_rows, key=lambda r: (r.get('group', ''), r['quest_name']))]
    starts = []
    for path, host in definitions(source):
        if host.tag != 'Project': continue
        for node in host.findall('Nodes/GameStart'):
            result = dict(project=host.get('Name'), file=path, event=node.get('Name') + '.OnStart')
            try:
                g = Graph(source, host.get('Name'), entry_file=path)
                result.update(probe(g, g.snapshot(), 'new-game event', [result['event']]),
                              unsupported=g.unsupported, native_runtime_verified=False,
                              nodes=len(g.nodes), visited_nodes=len(g.visited),
                              unresolved_native_bindings=g.report()['unresolved_native_bindings'],
                              pending_native_calls=g.native.pending)
                result['probe_status'] = result['status']
                if result['status'] == 'EXECUTED' and g.unsupported:
                    result['status'] = 'PARTIAL_UNSUPPORTED'
            except (Unsupported, ValueError) as exc: result.update(status='LOAD_BLOCKED', error=str(exc))
            starts.append(result)
    return dict(schema=1, created_utc=datetime.now(timezone.utc).isoformat(), source=str(source.path),
                scope='All Quest definitions in the supplied package; isolated public callback probes and structural checks',
                limits=['No native rendering, physics, NPC scheduling or engine outcomes are simulated automatically.',
                        'EXECUTED means a diagnostic stimulus ran without an interpreter exception, not a quest pass.',
                        'Public objective callbacks are hypothetical inputs; they do not prove gameplay reaches them.',
                        'Missing source definitions are coverage gaps; source records include test/development content.',
                        'Only the supplied package is audited; NOT_PRESENT does not assert absence from other packages.'],
                quests=quests, new_game=starts, source_inventory=source_inventory,
                source_groups={group: dict(Counter(r['status'] for r in source_inventory if r['group'] == group))
                               for group in sorted({r['group'] for r in source_inventory})},
                structure=structural_checks(source), invalid_xml=[p for p,r in source.files.items() if r is None])


def write(report, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    (output / 'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    e = lambda value: escape(str(value))
    def compact(q):
        data = {k:v for k,v in q.items() if k not in ('probes','files','emitted_files','source_graph_provenance',
                                                     'converter_unsupported','unsupported')}
        if q.get('unsupported'):
            data['unsupported_summary'] = dict(Counter(x['reason'] for x in q['unsupported']))
        if q.get('probes'):
            data['blocked_probe_reasons'] = dict(Counter(p['error'] for p in q['probes'] if p['error']))
        if 'project' in q:
            data['state_snapshot_count'] = len(data.pop('states', {}))
            bindings = data.pop('unresolved_native_bindings', [])
            data['unresolved_native_input_counts'] = dict(Counter(b['port'] for b in bindings))
        return data
    rows = ''.join('<tr><td>' + e(q['name']) + '</td><td>' + e(q['status']) + '</td><td>'
                   + e(q.get('probe_counts', {})) + '</td><td>' + e(len(q.get('unsupported', []))) + '</td></tr>'
                   for q in report['quests'])
    details = ''.join('<details><summary>' + e(q['name']) + '</summary><pre>'
                      + e(json.dumps(compact(q), indent=2)) + '</pre></details>' for q in report['quests'])
    inventory = ''.join('<tr><td>' + e(q['name']) + '</td><td>' + e(q['group']) + '</td><td>'
                        + e(q['status']) + '</td></tr>' for q in report['source_inventory'])
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Quest campaign audit</title>
<style>body{font:16px system-ui;background:#14202b;color:#e9f0f5;max-width:1200px;margin:40px auto;padding:24px}
table{width:100%;border-collapse:collapse}td,th{text-align:left;border-bottom:1px solid #435466;padding:9px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:640px;overflow:auto;background:#0b151f;padding:16px}
summary{cursor:pointer;padding:12px}input{font:inherit;padding:10px;width:90%;margin:20px 0}</style>
<h1>Quest campaign audit</h1><p>''' + e(report['created_utc']) + '</p><p>' + e(report['source']) + '</p><ul>'
    page += ''.join('<li>' + e(x) + '</li>' for x in report['limits']) + '</ul>'
    page += '<p><a style="color:#7bd7ff" href="audit.json">Complete machine-readable evidence and every probe</a></p>'
    page += '<h2>Installed quests</h2><table><tr><th>Quest</th><th>Coverage</th><th>Isolated probes</th><th>Unsupported entries</th></tr>' + rows + '</table>'
    page += '<h2>New-game chain</h2><pre>' + e(json.dumps([compact(g) for g in report['new_game']], indent=2)) + '</pre>'
    structure = report['structure']
    structure_summary = {k:v for k,v in structure.items() if k!='unresolved_interfaces'}
    structure_summary['unresolved_interface_reasons'] = dict(Counter(x['reason'] for x in structure['unresolved_interfaces']))
    page += '<h2>Structure checks</h2><pre>' + e(json.dumps(structure_summary, indent=2)) + '</pre>'
    page += '<h2>Per-quest evidence</h2>' + details
    if report.get('source_graphs'):
        source_graphs = report['source_graphs']
        page += '<h2>Source graph conversion dry runs</h2><p>' + e(source_graphs['scope']) + '</p><ul>'
        page += ''.join('<li>' + e(x) + '</li>' for x in source_graphs['limits']) + '</ul>'
        page += '<pre>' + e(json.dumps(source_graphs['statuses'], indent=2)) + '</pre>'
        for item in source_graphs['quests']:
            page += '<details><summary>' + e(item['name'] + ' — ' + item['status']) + '</summary><pre>'
            page += e(json.dumps(compact(item), indent=2)) + '</pre></details>'
    page += '<h2>Every source quest record</h2><p>Includes development/test records; group labels are from KCD1.</p>'
    page += '<input id="search" aria-label="Filter source quest records" placeholder="Filter by name, group or status"><table id="inventory"><tr><th>Source quest</th><th>Source group</th><th>Coverage</th></tr>' + inventory + '</table>'
    page += '''<script>document.getElementById('search').addEventListener('input',e=>{const q=e.target.value.toLowerCase();document.querySelectorAll('#inventory tr').forEach((r,i)=>{if(i)r.hidden=!r.textContent.toLowerCase().includes(q)})})</script></html>'''
    (output / 'audit.html').write_text(page, encoding='utf-8')


def run(source_path, output, kcd1=None, source_graphs=False):
    rows = []
    if kcd1:
        from campaign_sources import RetailSourceReader
        from campaign_dependency_adapters import SourceTables
        with RetailSourceReader(Path(kcd1)) as reader:
            rows = SourceTables(reader.game, reader).get('quest/quest')['rows']
    report = audit(Source(source_path), rows)
    if source_graphs:
        from .source_audit import run as audit_source
        report['source_graphs'] = audit_source(kcd1, progress=lambda done,total,name,status:
            print(f'Source quest {done}/{total}: {name}: {status}', flush=True))
    write(report, output)
    return report
