"""Portable developer reports: audit.json, roles_by_soul.json, audit.html and junit.xml."""
from html import escape
import json
from pathlib import Path
import xml.etree.ElementTree as E

STYLE = ('body{font:16px system-ui;background:#101820;color:#e3eaf0;max-width:1200px;margin:40px auto;padding:0 24px}'
         'h1{font-size:36px;letter-spacing:-.025em}.intro{color:#b3c5d1;max-width:920px;line-height:1.6}'
         'section{border:1px solid #344652;padding:24px;border-radius:12px;margin:28px 0}'
         'table{border-collapse:collapse;width:100%;margin:14px 0}td,th{padding:8px;border-bottom:1px solid #344652;'
         'vertical-align:top;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;font-size:13px}'
         'summary{cursor:pointer;padding:12px 0}.PASS{color:#78dfae}.FAIL,.error{color:#ff9993}'
         '.UNSUPPORTED,.review,.PASS_WITH_REVIEW{color:#ffd477}input{padding:12px;background:#1d2e3b;color:white;'
         'border:1px solid #607783;border-radius:6px;width:calc(100% - 26px)}')


def _table(headers, rows):
    head = ''.join('<th>' + escape(h) + '</th>' for h in headers)
    body = ''.join('<tr>' + ''.join('<td>' + (c if isinstance(c, Markup) else escape(str(c))) + '</td>' for c in row)
                   + '</tr>' for row in rows)
    return '<table><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table>'


class Markup(str):
    pass


def _pre(value):
    return Markup('<pre>' + escape(json.dumps(value, indent=2, ensure_ascii=False)) + '</pre>')


def junit(cases, name):
    suite = E.Element('testsuite', name=name, tests=str(len(cases)),
                      failures=str(sum(c[1] == 'FAIL' for c in cases)),
                      errors=str(sum(c[1] in ('ERROR', 'UNSUPPORTED') for c in cases)))
    for case_name, status, message in cases:
        case = E.SubElement(suite, 'testcase', name=case_name, classname='storm_lab')
        if status != 'PASS':
            E.SubElement(case, 'failure' if status == 'FAIL' else 'error', type=status, message=message or status)
    E.indent(suite)
    return suite


def write_audit(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'audit.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    (output / 'roles_by_soul.json').write_text(json.dumps(dict(
        schema=1, native_runtime_verified=False,
        note='Observation fixture for quest_lab role-gated dialogue; roles under modeled Storm semantics only.',
        souls={n: dict(roles=r['roles'], metaroles=r['metaroles']) for n, r in report['roles_by_soul'].items()}),
        indent=2, ensure_ascii=False), encoding='utf-8')
    cases = [('contract %s %s' % (c['contract'], c['soul']), c['status'], c.get('detail') or json.dumps(
        {k: c.get(k) for k in ('missing', 'conditional', 'duplicate_trade')})) for c in report['contracts']]
    cases += [('finding %s %s' % (f['kind'], f['soul']), 'FAIL', f['detail'])
              for f in report['findings'] if f['severity'] == 'error']
    cases += [('unsupported %s' % k, 'UNSUPPORTED', '%d rule x soul evaluations' % n)
              for k, n in report['unsupported'].items()]
    if not cases: cases = [('audit', 'PASS', '')]
    E.ElementTree(junit(cases, 'Storm role evaluator')).write(output / 'junit.xml', encoding='utf-8', xml_declaration=True)
    v = report['verdict']
    html = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>Storm Role Audit</title><style>', STYLE,
            '</style><h1>Storm Role Audit</h1><p class="intro">Developer emulator report. Roles are computed from the '
            'mounted Storm program under the modeled selector semantics listed below; inferred semantics are named, and '
            'rules whose outcome depends on one are listed under Sensitivity. Unsupported selectors never pass. This is '
            'not native-runtime verification.</p>',
            '<p>Verdict: <b class="%s">%s</b> - %d errors, %d review findings, %d failing contracts.</p>' % (
                v['status'], v['status'], v['errors'], v['reviews'], v['contracts_failing'])]
    html.append('<section><h2>Service contracts</h2>' + _table(
        ['Status', 'Contract', 'Soul', 'Detail'],
        [(Markup('<span class="%s">%s</span>' % (c['status'], c['status'])), c['contract'], c['soul'],
          _pre({k: c.get(k) for k in ('missing', 'conditional', 'duplicate_trade', 'negotiation_metarole', 'detail')}))
         for c in report['contracts']]) + '</section>')
    html.append('<section><h2>Findings</h2><input id="f" placeholder="Filter findings">' + _table(
        ['Severity', 'Kind', 'Soul', 'Detail'],
        [(Markup('<span class="%s">%s</span>' % (f['severity'], f['severity'])), f['kind'], f['soul'] or '', f['detail'])
         for f in report['findings']]) + '</section>')
    html.append('<section><h2>Native role sources reaching converted souls</h2>' + _table(
        ['Source', 'Souls', 'Definite roles', 'Conditional roles'],
        [(f, a['souls'], ', '.join(a['definite_roles']), ', '.join(a['conditional_roles'])) for f, a in report['ambient'].items()])
        + '</section>')
    html.append('<section><h2>Sensitivity: rules false only under an inferred semantic</h2>' + ''.join(
        '<h3>%s</h3><p>%s</p>' % (escape(a), escape(report['assumptions'].get(a, {}).get('alternative', '')))
        + _table(['Source', 'Rule', 'Operations', 'Souls'],
                 [(r['file'], r['rule'], ', '.join(r['operations']), '%d: %s' % (len(r['souls']), ', '.join(r['souls'][:8])))
                  for r in rows]) for a, rows in report['sensitivity'].items()) + '</section>')
    html.append('<section><h2>Modeled semantics</h2>' + _table(
        ['Id', 'Kind', 'Rule', 'Evidence', 'Alternative'],
        [(k, a['kind'], a['rule'], a['evidence'], a.get('alternative', '')) for k, a in report['assumptions'].items()])
        + '</section>')
    html.append('<details><summary>Unsupported tally, program inventory and provenance</summary>' + _table(
        ['Item', 'Value'], [('Unsupported', _pre(report['unsupported'])), ('Rule evaluations', _pre(report['rule_evaluations'])),
                            ('Program', _pre(report['program'])), ('Souls', _pre(report['souls'])),
                            ('Native self-check', _pre(report.get('native_selfcheck'))),
                            ('Provenance', _pre(report['provenance']))]) + '</details>')
    html.append('<details><summary>Roles by soul</summary>' + _table(
        ['Soul', 'Roles'], [(n, _pre({k: v['status'] for k, v in r['roles'].items()})) for n, r in report['roles_by_soul'].items()])
        + '</details>')
    html.append("<script>document.getElementById('f').addEventListener('input',e=>{const q=e.target.value.toLowerCase();"
                "document.querySelectorAll('section:nth-of-type(2) tbody tr').forEach(r=>r.hidden=!r.textContent.toLowerCase()"
                ".includes(q));});</script></html>")
    (output / 'audit.html').write_text(''.join(html), encoding='utf-8')


def write_runs(results, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'results.json').write_text(json.dumps(dict(schema=1, native_runtime_verified=False, results=results),
                                                    indent=2, ensure_ascii=False), encoding='utf-8')
    E.ElementTree(junit([(r['name'], r['status'], r.get('error')) for r in results], 'Storm scenarios')).write(
        output / 'junit.xml', encoding='utf-8', xml_declaration=True)
    rows = [(Markup('<span class="%s">%s</span>' % (r['status'], r['status'])), r['name'], _pre(r['assertions']))
            for r in results]
    (output / 'report.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Storm Scenarios</title>'
                                        '<style>' + STYLE + '</style><h1>Storm Scenarios</h1><p class="intro">Assertion '
                                        'scenarios over modeled Storm semantics. Not native-runtime verification.</p>'
                                        + _table(['Status', 'Scenario', 'Assertions'], rows) + '</html>', encoding='utf-8')
