"""Repair lesson authorization and scene release without changing authored places."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from upgrade_map import read, xml


def preparation_release(blob):
    """Migrate the owned lifecycle's recognized pre-scene-release preparation."""
    from campaign_quest_graph import edge
    from setup_quest_invitation import graph_digest
    root = E.fromstring(blob); nodes = root.find('Skald/Module/Nodes')
    if nodes is None: raise ValueError('Missing training lifecycle module')
    prepare = nodes.find("If[@Name='authorized_preparation']")
    condition = None if prepare is None else prepare.find("Edge[@To='Condition']")
    if condition is None: raise ValueError('Missing training preparation guard')
    expected = E.Element('Function', Name='may_prepare_1',
                         MethodName='math::boolean::And', DeclaringType='math::boolean')
    edge(expected, 'may_prepare_0.bool', 'A'); edge(expected, 'not_talking.bool', 'B')
    gate = nodes.find("*[@Name='may_prepare_1']")
    events = {e.get('From') for e in prepare.findall("Edge[@To='Exec']")}
    original = {'arrived_order.C', 'authorization_changed'}
    if condition.get('From') == 'may_prepare_1.bool':
        if (gate is None or graph_digest(gate) != graph_digest(expected)
                or events != original | {'dialogue_finished'}):
            raise ValueError('Conflicting training scene release guard')
        return blob, False
    if condition.get('From') != 'may_prepare_0.bool' or gate is not None or events != original:
        raise ValueError('Unrecognized training preparation guard')
    busy = nodes.find("Function[@Name='not_talking'][@MethodName='math::boolean::Not']")
    if busy is None or busy.find("Edge[@From='dialogue_busy'][@To='Value']") is None:
        raise ValueError('Missing training scene occupancy binding')
    nodes.append(expected); condition.set('From', 'may_prepare_1.bool')
    edge(prepare, 'dialogue_finished', 'Exec')
    return xml(root), True


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
    lifecycle = 'Quests/GlueTravel/'+stem+'/'+stem+'_lifecycle.xml'
    fixed, released = preparation_release(graphs[lifecycle])
    changes = {lifecycle:fixed} if released else {}
    if changed: changes[ENTRY] = xml(entry)
    files = {}
    if changes:
        graphs.update(changes)
        validate_references(entry,graphs,stem)
        rewrite(package,travel,changes)
        files[travel] = digest(package/travel)
        for node in nodes:
            if node.get('Name','').startswith(stem):
                report['graph_nodes'][node.get('Name')] = graph_digest(node)
        report['runtime_verified'] = False
        report['host']['authorization_requires_arrival'] = True
        report['host']['preparation_requires_scene_release'] = True
        if released: report['resources'][travel][lifecycle] = hashlib.sha256(fixed).hexdigest()
        pending = package/(RECORD+'.pending')
        pending.write_text(json.dumps(report,indent=2),encoding='utf-8')
        pending.replace(package/RECORD); files[RECORD] = digest(package/RECORD)
    validate(package)
    return files, dict(version=2, changed=bool(changes), preparation_requires_scene_release=True,
        authorization_requires_arrival=True, source_objectives=report['source']['objectives'],
        runtime_verified=False)
