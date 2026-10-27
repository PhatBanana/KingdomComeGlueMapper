"""Portable developer reports: JSON evidence, JUnit and a searchable HTML page."""
from html import escape
import json
from pathlib import Path
import xml.etree.ElementTree as E

CSS = '''body{font:16px system-ui;background:#101820;color:#e3eaf0;max-width:1200px;margin:40px auto;padding:0 24px}h1,h2{letter-spacing:-.025em}h1{font-size:36px}.intro{color:#b3c5d1;max-width:920px;line-height:1.6}section{border:1px solid #344652;padding:24px;border-radius:12px;margin:28px 0}table{border-collapse:collapse;width:100%;margin:14px 0}td,th{padding:8px 10px;border-bottom:1px solid #344652;vertical-align:top;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;font-size:13px}summary{cursor:pointer;padding:10px 0}.PASS,.NO_FINDINGS_IN_MODELLED_SCOPE{color:#78dfae}.FAIL,.ERROR,.error{color:#ff9993}.UNSUPPORTED,.INCOMPLETE,.REVIEW,.review{color:#ffd477}input{padding:12px;background:#1d2e3b;color:white;border:1px solid #607783;border-radius:6px;width:calc(100% - 26px)}'''
FILTER = '''<script>document.getElementById('filter').addEventListener('input',e=>{const q=e.target.value.toLowerCase();document.querySelectorAll('tbody tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q));});</script>'''


def table(rows, header=None):
    head = '<thead><tr>' + ''.join('<th>' + escape(h) + '</th>' for h in header) + '</tr></thead>' if header else ''
    return '<table>' + head + '<tbody>' + ''.join(
        '<tr>' + ''.join('<td>' + (c if isinstance(c, _Raw) else escape(str(c))) + '</td>' for c in row) + '</tr>'
        for row in rows) + '</tbody></table>'


class _Raw(str):
    pass


def pre(value):
    return _Raw('<pre>' + escape(json.dumps(value, indent=2, ensure_ascii=False)) + '</pre>')


def junit(checks, name):
    suite = E.Element('testsuite', name=name, tests=str(len(checks)),
                      failures=str(sum(c['status'] == 'FAIL' for c in checks)),
                      errors=str(sum(c['status'] == 'ERROR' for c in checks)),
                      skipped=str(sum(c['status'] in ('UNSUPPORTED', 'REVIEW') for c in checks)))
    for c in checks:
        case = E.SubElement(suite, 'testcase', name=c['id'], classname='asset_lab')
        text = '\n'.join(f'{f["code"]}: {f["subject"]}: {f["detail"]}' for f in c['findings'][:50])
        if c['status'] == 'FAIL': E.SubElement(case, 'failure', type='FAIL', message=c['title']).text = text
        elif c['status'] == 'ERROR': E.SubElement(case, 'error', type='ERROR', message=c['title']).text = text
        elif c['status'] in ('UNSUPPORTED', 'REVIEW'):
            E.SubElement(case, 'skipped', message=c['status'] + ': ' + '; '.join(c.get('skipped') or [c['title']])[:500])
    E.indent(suite)
    return E.ElementTree(suite)


def write_audit(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'audit.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    junit(report['checks'], 'Asset contract gate').write(output / 'junit.xml', encoding='utf-8', xml_declaration=True)
    sections = []
    for c in report['checks']:
        counts = table([(f['severity'], f['code'], f['count']) for f in c['counts']], ('Severity', 'Code', 'Count')) if c['counts'] else ''
        findings = table([(f['severity'], f['code'], f['subject'], f['detail']) for f in c['findings']],
                         ('Severity', 'Code', 'Subject', 'Detail')) if c['findings'] else ''
        more = f'<p>{c["findings_truncated"]} further findings counted but not listed.</p>' if c['findings_truncated'] else ''
        skipped = '<ul>' + ''.join('<li>' + escape(s) + '</li>' for s in c['skipped']) + '</ul>' if c['skipped'] else ''
        sections.append(f'<section><h2><span class="{c["status"]}">{c["status"]}</span> {escape(c["title"])}</h2>'
                        f'<p class="intro">{escape(c["scope"])}</p>{skipped}{counts}{findings}{more}'
                        f'<details><summary>Thresholds and details</summary>{table([("thresholds", pre(c["thresholds"])), ("details", pre(c["details"]))])}</details></section>')
    hot = next((c['details'].get('hot_spots') for c in report['checks'] if c['id'] == 'dds_piece_budget'), None)
    hot_html = ''
    if hot:
        hot_html = '<section><h2>Largest streaming pieces</h2>' + table(
            [(i + 1, h['mib'], h['family'], h['piece'], h['pak']) for i, h in enumerate(hot)],
            ('#', 'MiB', 'Texture family', 'Piece', 'Pak')) + '</section>'
    contracts = table([(c['id'], c['status'], c['reason']) for c in report['contracts']], ('Contract', 'Status', 'Not modelled'))
    html = (f'<!doctype html><html lang="en"><meta charset="utf-8"><title>Asset contract gate</title><style>{CSS}</style>'
            f'<h1>Asset contract gate</h1><p class="intro">Developer report. Verdict <b class="{report["verdict"]}">{report["verdict"]}</b>. '
            'It states that modelled structural and retail-derived contracts were or were not met. Thresholds are observed in retail '
            'data and are not proven engine limits. This is not native-runtime verification and never a PASS for the package.</p>'
            f'<label>Filter rows <input id="filter" placeholder="Search a texture, material, code or pak"></label>'
            f'{hot_html}{"".join(sections)}<section><h2>Explicit contracts (UNSUPPORTED)</h2>{contracts}</section>'
            f'<section><h2>Sources</h2>{table([("package", pre(report["package"])), ("target", pre(report["target"]))])}</section>{FILTER}</html>')
    (output / 'audit.html').write_text(html, encoding='utf-8')


def write_run(reports, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    payload = dict(schema=1, native_runtime_verified=False, results=reports)
    (output / 'results.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    suite = E.Element('testsuite', name='Asset contract scenarios', tests=str(len(reports)),
                      failures=str(sum(r['status'] == 'FAIL' for r in reports)),
                      errors=str(sum(r['status'] in ('ERROR', 'UNSUPPORTED') for r in reports)))
    sections = []
    for r in reports:
        case = E.SubElement(suite, 'testcase', name=r['name'], classname='asset_lab')
        if r['status'] != 'PASS':
            E.SubElement(case, 'failure' if r['status'] == 'FAIL' else 'error', type=r['status'],
                         message=r.get('error') or '; '.join(a['label'] for a in r['assertions'] if not a['ok'])[:500])
        sections.append(f'<section><h2><span class="{r["status"]}">{r["status"]}</span> {escape(r["name"])}</h2>'
                        + (f'<p class="error">{escape(r["error"])}</p>' if r.get('error') else '')
                        + table([(a['label'], 'ok' if a['ok'] else 'FAILED', pre(a['observed'])) for a in r['assertions']],
                                ('Assertion', 'Result', 'Observed')) + '</section>')
    html = (f'<!doctype html><html lang="en"><meta charset="utf-8"><title>Asset scenarios</title><style>{CSS}</style>'
            '<h1>Asset contract scenarios</h1><p class="intro">PASS means every assertion about the modelled contract held. '
            'Contracts not modelled are never inferred to pass.</p>'
            f'<label>Filter rows <input id="filter" placeholder="Search"></label>{"".join(sections)}{FILTER}</html>')
    (output / 'report.html').write_text(html, encoding='utf-8')
    E.indent(suite)
    E.ElementTree(suite).write(output / 'junit.xml', encoding='utf-8', xml_declaration=True)
