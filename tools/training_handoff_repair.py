"""Repair premature lesson conversations without changing authored places."""
import json
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from upgrade_map import read, xml


def upgrade(package, source=None, target=None):
    from setup_gameplay import ENTRY
    from setup_training_upgrade import validate, conversations, validate_references, RECORD
    from setup_quest_invitation import graph_digest
    from setup_campaign import digest
    from setup_package_upgrade import rewrite
    from campaign_training_host import guard_authorization
    package = Path(package)
    report = validate(package)
    quest = report['selection']['quest']; stem = 'gm_training_'+quest
    travel = 'Data/gluemappertravel.pak'
    with zipfile.ZipFile(package/travel) as archive:
        graphs = {n:read(archive,n) for n in archive.namelist()
                  if n.startswith('Quests/') and n.endswith('.xml')}
    entry = E.fromstring(graphs[ENTRY]); nodes = entry.find('Skald/Level/Nodes')
    speech = conversations(nodes,graphs,stem+'_speech_')
    changed = guard_authorization(nodes,stem,quest,report['source']['objectives'],speech)
    files = {}
    if changed:
        graphs[ENTRY] = xml(entry)
        validate_references(entry,graphs,stem)
        rewrite(package,travel,{ENTRY:graphs[ENTRY]})
        files[travel] = digest(package/travel)
        for node in nodes:
            if node.get('Name','').startswith(stem):
                report['graph_nodes'][node.get('Name')] = graph_digest(node)
        report['runtime_verified'] = False
        report['host']['authorization_requires_arrival'] = True
        pending = package/(RECORD+'.pending')
        pending.write_text(json.dumps(report,indent=2),encoding='utf-8')
        pending.replace(package/RECORD); files[RECORD] = digest(package/RECORD)
    validate(package)
    return files, dict(version=1, changed=changed,
        authorization_requires_arrival=True, source_objectives=report['source']['objectives'],
        runtime_verified=False)
