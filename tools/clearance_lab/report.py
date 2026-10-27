"""JSON evidence, searchable HTML and JUnit (UNSUPPORTED is a JUnit error)."""
from html import escape
import json
from pathlib import Path
import xml.etree.ElementTree as E

COLUMNS = ('severity', 'category', 'x', 'y', 'z', 'interaction', 'entity_class', 'surface', 'penetration_m', 'gap_m', 'volume', 'road')


def junit(cases, output, suite_name):
    suite = E.Element('testsuite', name=suite_name, tests=str(len(cases)),
                      failures=str(sum(c['status'] == 'FAIL' for c in cases)),
                      errors=str(sum(c['status'] in ('UNSUPPORTED', 'ERROR') for c in cases)))
    for c in cases:
        case = E.SubElement(suite, 'testcase', name=c['name'], classname='clearance_lab')
        if c['status'] in ('FAIL', 'UNSUPPORTED', 'ERROR'):
            E.SubElement(case, 'failure' if c['status'] == 'FAIL' else 'error', type=c['status'],
                         message=c.get('message') or c['status']).text = json.dumps(c.get('detail', ''))[:4000]
        elif c['status'] == 'REVIEW':
            E.SubElement(case, 'system-out').text = c.get('message') or 'review findings (see report)'
    E.indent(suite)
    E.ElementTree(suite).write(Path(output) / 'junit.xml', encoding='utf-8', xml_declaration=True)


def _rows(findings):
    out = []
    for f in findings:
        cells = ''.join('<td>' + escape(str(f.get(k, '') if f.get(k) is not None else '')) + '</td>' for k in COLUMNS)
        out.append(f'<tr class="{escape(f["severity"])}">{cells}<td><details><summary>all</summary><pre>'
                   + escape(json.dumps(f, indent=1)) + '</pre></details></td></tr>')
    return ''.join(out)


def html(report, title):
    parts = [f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>{escape(title)}</title>
<style>body{{font:15px system-ui;background:#101820;color:#e3eaf0;max-width:1300px;margin:32px auto;padding:0 16px}}
section{{border:1px solid #344652;border-radius:10px;padding:16px;margin:20px 0}}table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{padding:6px;border-bottom:1px solid #344652;text-align:left;vertical-align:top}}pre{{white-space:pre-wrap;margin:0}}
.PASS{{color:#78dfae}}.FAIL,.ERROR,.defect td:first-child{{color:#ff9993}}.UNSUPPORTED,.REVIEW,.inspect td:first-child{{color:#ffd477}}
input{{padding:10px;width:calc(100% - 22px);background:#1d2e3b;color:#fff;border:1px solid #607783;border-radius:6px}}</style>
<h1>{escape(title)}</h1><p>Overall: <b class="{report['status']}">{report['status']}</b>. Offline emulator; shapes approximate
native helpers and nothing here is native-runtime verification. World x, y are level coordinates.</p>
<label>Filter rows <input id="filter" placeholder="category, class, surface, coordinate..."></label>''']
    for c in report['checks']:
        meta = {k: v for k, v in c.items() if k not in ('findings', 'name', 'status')}
        parts.append(f'<section><h2><span class="{c["status"]}">{c["status"]}</span> {escape(c["name"])} '
                     f'({len(c["findings"])} findings)</h2><pre>{escape(json.dumps(meta, indent=1))}</pre>'
                     '<table class="f"><thead><tr>' + ''.join(f'<th>{k}</th>' for k in COLUMNS) + '<th></th></tr></thead><tbody>'
                     + _rows(c['findings'][:5000]) + '</tbody></table></section>')
    rest = {k: report[k] for k in ('assumptions', 'not_modelled', 'unsupported', 'unknown_surfaces', 'inventory', 'surface_table', 'hashes') if k in report}
    parts.append('<section><h2>Assumptions, unmodelled behaviour, inventory and source hashes</h2><pre>'
                 + escape(json.dumps(rest, indent=1)) + '</pre></section>')
    parts.append('''<script>document.getElementById('filter').addEventListener('input',e=>{const q=e.target.value.toLowerCase();
document.querySelectorAll('table.f tbody tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q));});</script></html>''')
    return ''.join(parts)


def write_audit(report, output, title='Clearance audit'):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    (output / 'audit.json').write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding='utf-8')
    (output / 'report.html').write_text(html(report, title), encoding='utf-8')
    junit([dict(name=c['name'], status=('PASS' if c['status'] == 'INFO' else c['status']),
                message=f"{len(c['findings'])} findings", detail=c.get('unsupported_reason') or [
                    f for f in c['findings'] if f['severity'] == 'defect'][:20])
           for c in report['checks']], output, 'Clearance audit')
