"""Portable developer reports: JSON evidence, JUnit and an HTML timeline."""
from html import escape
import json
from pathlib import Path
import xml.etree.ElementTree as E


def write(reports, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    payload = dict(schema=1, native_runtime_verified=False, results=reports)
    (output / 'results.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    suite = E.Element('testsuite', name='Quest and NPC emulator', tests=str(len(reports)),
        failures=str(sum(r['status'] in ('FAIL','TIMEOUT') for r in reports)),
        errors=str(sum(r['status'] in ('ERROR','UNSUPPORTED') for r in reports)))
    sections = []
    for r in reports:
        case = E.SubElement(suite, 'testcase', name=r['name'], classname='quest_lab')
        if r['status'] != 'PASS':
            E.SubElement(case, 'failure' if r['status'] in ('FAIL','TIMEOUT') else 'error',
                type=r['status'], message=r.get('error') or r['status']).text = json.dumps(r.get('graph',{}).get('unsupported',[]))
        def table(rows):
            return '<table><tbody>' + ''.join('<tr><td>'+escape(str(a))+'</td><td><pre>'+escape(json.dumps(b,ensure_ascii=False,indent=2))+'</pre></td></tr>' for a,b in rows) + '</tbody></table>'
        sections.append('<section><h2><span class="'+r['status']+'">'+r['status']+'</span> '+escape(r['name'])+'</h2>'
            + ('<p class="error">'+escape(r['error'])+'</p>' if r.get('error') else '')
            + '<h3>Assertions</h3>' + table((a['label'], a) for a in r['assertions'])
            + '<details><summary>Coverage, source hashes and external contracts</summary>'
            + table([('Graph',r.get('graph',{})),('Behaviors',r.get('behaviors',{}))]) + '</details>'
            + '<details open><summary>Execution timeline</summary><div class="timeline">'
            + table((f"{e['time_us']/1000000:g}s · {e['kind']}", e) for e in r['timeline'])+'</div></details></section>')
    html = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Quest & NPC Tests</title>
<style>body{font:16px system-ui;background:#101820;color:#e3eaf0;max-width:1200px;margin:40px auto;padding:0 24px}h1,h2{letter-spacing:-.025em}h1{font-size:36px}.intro{color:#b3c5d1;max-width:920px;line-height:1.6}section{border:1px solid #344652;padding:24px;border-radius:12px;margin:28px 0}table{border-collapse:collapse;width:100%;margin:14px 0}td{padding:10px;border-bottom:1px solid #344652;vertical-align:top}td:first-child{width:28%}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;font-size:13px}summary{cursor:pointer;padding:12px 0}.PASS{color:#78dfae}.FAIL,.ERROR,.TIMEOUT,.error{color:#ff9993}.UNSUPPORTED{color:#ffd477}.timeline{max-height:650px;overflow:auto}input{padding:12px;background:#1d2e3b;color:white;border:1px solid #607783;border-radius:6px;width:calc(100% - 26px)}</style>
<h1>Quest & NPC Tests</h1><p class="intro">Developer emulator report. PASS means the modeled converted logic satisfied this scenario. Engine outcomes are explicit test inputs; native navigation, animation, scheduler arbitration and save-file compatibility are not verified. Unsupported operations prevent PASS.</p>
<label>Filter timeline rows <input id="filter" placeholder="Search a node, event, condition or value"></label>'''
    html += ''.join(sections)
    html += '''<script>document.getElementById('filter').addEventListener('input',e=>{const q=e.target.value.toLowerCase();document.querySelectorAll('.timeline tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q));});</script></html>'''
    (output / 'report.html').write_text(html, encoding='utf-8')
    E.indent(suite)
    E.ElementTree(suite).write(output/'junit.xml', encoding='utf-8', xml_declaration=True)
