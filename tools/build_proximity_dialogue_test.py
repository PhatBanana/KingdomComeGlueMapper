"""Attach a source proximity observer to an already staged dialogue package."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile
from campaign_proximity_dialogue import parse, install
from campaign_state_diagnostics import observe
from build_horse_trader_test import rewrite, digest
from upgrade_map import read


def build(a):
    tree = E.parse(a.source_program).find("BehaviorTree[@name='" + a.tree + "']")
    if tree is None: raise ValueError('Source behavior tree is missing')
    plan = parse(tree, a.objective)
    with zipfile.ZipFile(a.travel) as z:
        blob = read(z,a.quest)
        souls = [s for n in z.namelist() if n.startswith('Libs/Tables/rpg/soul__')
                 for s in E.fromstring(read(z,n)).iter('soul') if s.get('soul_name')==a.actor]
        if len(souls)!=1:raise ValueError('Missing or ambiguous imported speaker')
        player = E.fromstring(read(z,a.level)).find("./Skald/Level/Assets/SoulAsset[@Name='player']")
        if player is None:raise ValueError('Missing registered player asset')
        aliases = {d.get('Alias') for n in z.namelist() if n.startswith('Quests/') and n.endswith('.xml')
                   for d in E.fromstring(read(z,n)).iter('Decision')}
        if any(l['alias'] not in aliases for l in plan['lanes']):raise ValueError('Source greeting dialogue is not packaged')
    result = install(blob,plan,souls[0].get('soul_id'),player.get('SharedSoulGuids'))
    result,traces = observe(result,[a.objective,*a.observe])
    if a.output.exists():raise FileExistsError('Choose a fresh proximity output')
    a.output.mkdir(parents=True)
    rewrite(a.travel,a.output/'gluemappertravel.pak',{a.quest:result})
    report=dict(plan=plan,source_program=str(a.source_program),source_sha256=digest(a.source_program),
                baseline_sha256=digest(a.travel),traces=traces,installed=False,runtime_verified=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source-program','travel','output'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('tree','objective','actor','quest','level'):p.add_argument('--'+name,required=True)
    p.add_argument('--observe',action='append',default=[])
    build(p.parse_args())
