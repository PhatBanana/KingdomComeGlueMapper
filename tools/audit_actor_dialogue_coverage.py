"""Preflight all production dialogue belonging to selected retail actors.

Keep every source event kind in the receipt. Unsupported kinds, missing text,
quest dependencies and participant adapters are blockers, never skipped success.
This command writes a small audit only and never mutates the playable package.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as E

from campaign_actor_dialogues import branch_catalog
from campaign_sources import RetailSourceReader
from campaign_dependency_adapters import SourceTables
from campaign_dialogue import TABLES, index_tables, resolve, emit
from campaign_dialogue_selection import SelectionCompiler, load_contract
from upgrade_map import read
from world_item_definitions import native_items, native_item_registry


def audit(source, target, package, people, quest_models, output):
    with RetailSourceReader(source) as reader:
        tables=SourceTables(source,reader)
        souls=[tables.row('rpg/soul','soul_name',name) for name in people]
        data={n:tables.get('text/'+n)['rows'] for n in (*TABLES,'dialogue_functions')}
        data['role']=tables.get('rpg/role')['rows']
        catalog=branch_catalog(data['v_branch'],data['topictorole'],tables.get('rpg/soul2role')['rows'],
            data['role'],tables.get('rpg/metarole')['rows'],[s['soul_id'] for s in souls])
        provenance={k:v['provenance'] for k,v in tables.cache.items()}
    with zipfile.ZipFile(source/'Localization/English_xml.pak') as z:
        text=E.fromstring(read(z,'text_ui_dialog.xml'))
    strings={r.findall('Cell')[0].text:''.join(r.findall('Cell')[2].itertext()) for r in text.findall('Row')}
    item_tables=[]
    for p in (package/'Data').glob('*.pak'):
        with zipfile.ZipFile(p) as z:
            item_tables.extend(read(z,n) for n in z.namelist() if n.lower().startswith('libs/tables/item/item__') and n.endswith('.xml'))
    items=native_item_registry(native_items(target,item_tables))
    contract=load_contract(source,target,{'threaten':'might'})
    contract['preserve_reputation_caps']=True
    indexes=index_tables(data)
    results=[]
    output.mkdir(parents=True,exist_ok=True)
    for record in catalog['branches']:
        tid=record['source']['start_topic'];kind=record['source']['branch_type_id']
        result=dict(record,blockers=[])
        try:
            model=resolve(data,start_topic=tid,indexes=indexes)
            model['roles']={r['role_id']:r for r in data['role']}
            keys={s['source']['ui_prompt'] for t in model['topics'].values() for s in t['sequences']}
            keys.update(l['response']['string_name'] for t in model['topics'].values() for s in t['sequences'] for l in s['lines'] if l['response'])
            keys.discard('')
            missing=sorted(keys-strings.keys())
            if missing:result['blockers'].append('Missing source localization: '+', '.join(missing))
            model['strings']={k:strings[k] for k in keys if k in strings}
            result.update(topics=len(model['topics']),sequences=sum(len(t['sequences']) for t in model['topics'].values()),
                recorded_lines=sum(bool(l['voices']) for t in model['topics'].values() for s in t['sequences'] for l in s['lines']),
                quest_effect_ids=sorted({e['quest_id'] for t in model['topics'].values() for s in t['sequences'] for e in s['effects']}))
            if kind not in ('0','6'):
                result['blockers'].append('Source branch kind requires native event/service adapter: '+kind)
            else:
                try:
                    blob,receipt=emit(model,'audit_actor_'+tid,quest_models,
                        selection_compiler=SelectionCompiler(**contract),registered_items=items,
                        kind='Dialog' if kind=='6' else 'FaderDialog')
                    if not missing:
                        (output/('dialogue-'+tid+'.xml')).write_bytes(blob)
                        result['emitted']=True
                except ValueError as error:result['blockers'].append(str(error))
        except (ValueError,KeyError) as error:result['blockers'].append(str(error))
        results.append(result)
    report=dict(people=[dict(name=s['soul_name'],soul=s['soul_id']) for s in souls],branches=results,
        excluded_test_branches=catalog['excluded_test_branches'],provenance=provenance,
        counts=dict(production=len(results),excluded_tests=len(catalog['excluded_test_branches']),
                    blocked=sum(bool(r['blockers']) for r in results),
                    by_kind=dict(Counter(r['source']['branch_type_id'] for r in results))),
        installed=False,runtime_verified=False,
        note='Emission alone does not validate actor registration, event invocation, quest lifecycle or recorded media.')
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report['counts']),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source','target','package','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--person',action='append',required=True)
    p.add_argument('--quest-ir',type=Path,action='append',default=[])
    a=p.parse_args()
    audit(a.source,a.target,a.package,a.person,[json.loads(n.read_text(encoding='utf8')) for n in a.quest_ir],a.output)
