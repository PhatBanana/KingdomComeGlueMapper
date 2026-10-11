"""Source-driven Skalitz inventory and read-only live MCP acceptance probes.

This does not start quests, spawn substitute actors, or mistake registration for
working gameplay. Runtime probes cover nearby authored interactive entities;
distant entities are excluded so normal streaming is not reported as a failure.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from campaign_behavior import CONTRACTS
from campaign_linker import discover_entry
from campaign_quest_bridge import OPERATIONS
from campaign_sources import RetailSourceReader


INTERACTIVE = {
    'NPC': 'people', 'NPC_Female': 'people', 'AnimDoor': 'doors',
    'Bed': 'beds', 'Shop': 'shops', 'Horse': 'horses', 'Stash': 'containers',
    'PickableItem': 'items', 'Grindstone': 'grindstones',
    'DiceMinigameCup': 'dice',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def position(text):
    if not text:
        return None
    try:
        values = [float(value) for value in text.split(',')]
    except ValueError:
        return None
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        return None
    return dict(zip(('x', 'y', 'z'), values))


def source_inventory(profiles_data, souls_data, documents, profile_name):
    """Keep authored identities, transforms, soul fields and entity links."""
    profiles = ET.fromstring(profiles_data)
    matches = [p for p in profiles.iter('GameProfile') if p.findtext('Name') == profile_name]
    if len(matches) != 1:
        raise ValueError('Source profile missing or ambiguous: ' + profile_name)
    docs = {}
    for name, data in documents.items():
        key = name.replace('\\', '/').lower()
        if key in docs:
            raise ValueError('Duplicate normalized source layer: ' + key)
        docs[key] = data
    souls = {}
    for soul in ET.fromstring(souls_data).findall('./SoulList/Souls/Soul'):
        souls.setdefault(soul.findtext('EntityGuid'), []).append(soul)
    entities, layers, unresolved = [], [], []
    identities = {}
    for layer in matches[0].findall('./GameLayers/GameLayer'):
        name = layer.text
        path = 'layers/' + name.lower() + '.xml'
        if path not in docs:
            unresolved.append(dict(kind='missing_layer', layer=name))
            continue
        data = docs[path]
        layers.append(dict(name=name, path=path, sha256=sha(data)))
        for ordinal, ent in enumerate(ET.fromstring(data).iter('Entity')):
            attrs = dict(ent.attrib)
            record = dict(source_id=path + '#' + str(ordinal), layer=name,
                          name=attrs.get('Name'), source_class=attrs.get('EntityClass'),
                          source_guid=attrs.get('EntityGuid'), position=position(attrs.get('Pos')),
                          rotation=attrs.get('Rotate'), scale=attrs.get('Scale'),
                          attributes=attrs,
                          links=[dict(link.attrib) for link in ent.findall('./EntityLinks/Link')],
                          properties_xml=ET.tostring(ent.find('Properties'), encoding='unicode')
                              if ent.find('Properties') is not None else None)
            if record['source_guid']:
                identities.setdefault(record['source_guid'].lower(), []).append(record['source_id'])
            if record['source_class'] in ('NPC', 'NPC_Female', 'Horse'):
                try:
                    soul_key = str(int((record['source_guid'] or '').replace('-', ''), 16))
                except ValueError:
                    soul_key = None
                candidates = souls.get(soul_key, [])
                if len(candidates) == 1:
                    soul = candidates[0]
                    record['soul'] = {
                        'guid': soul.findtext('Guid'), 'shared_guid': soul.findtext('SharedSoulGuid'),
                        'name': soul.findtext('Name'),
                        'fields': {'/'.join(path): value for path, value in leaf_fields(soul)},
                        'xml': ET.tostring(soul, encoding='unicode'),
                    }
                else:
                    unresolved.append(dict(kind='soul_join', entity=record['name'], matches=len(candidates)))
            entities.append(record)
    for guid, sites in identities.items():
        if len(sites) > 1:
            unresolved.append(dict(kind='duplicate_entity_guid', guid=guid, sites=sites))
    return dict(profile=profile_name, profile_xml=ET.tostring(matches[0], encoding='unicode'),
                layers=layers, entities=entities, unresolved=unresolved,
                counts=dict(Counter(e['source_class'] or '<no class>' for e in entities)),
                source_hashes={'whdata_0': sha(souls_data), 'whdata_1': sha(profiles_data)})


def leaf_fields(element, path=()):
    """Use repeated element indexes so schedules never lose multiple entries."""
    counts = Counter(child.tag for child in element)
    indexes = Counter()
    for child in element:
        indexes[child.tag] += 1
        label = child.tag if counts[child.tag] == 1 else f'{child.tag}[{indexes[child.tag] - 1}]'
        child_path = (*path, label)
        if len(child):
            yield from leaf_fields(child, child_path)
        else:
            yield child_path, child.text or ''


def controller_gaps(documents):
    """Report exact missing operation adapters, not guessed executable support."""
    result = []
    for document, data in documents.items():
        for tree in ET.fromstring(data).findall('BehaviorTree'):
            root = tree.find('Root')
            if root is None:
                continue
            missing = Counter(n.tag for n in root.iter()
                              if n.tag not in CONTRACTS and n.tag not in OPERATIONS)
            if missing:
                result.append(dict(document=document, tree=tree.get('name'),
                                   missing_operation_adapters=dict(sorted(missing.items()))))
    return result


def acceptance_cases(inventory):
    present = inventory['counts']
    cases = [
        ('level_load', 'Level loading and player body', 'Enter through the native New Game or travel lifecycle; inspect Henry while standing and moving.'),
        ('opening', 'Original New Game opening', 'Play the source-selected movie and cutscene, complete the mother dialogue, and start speakWithFather exactly once.'),
        ('terrain_collision', 'Terrain and building collision', 'Walk the home doorway and Skalitz roads; compare grounded movement and collision with source placements.'),
        ('rendering', 'Materials, vegetation and streaming', 'Inspect near and far assets while moving; check missing materials, HLOD timeouts and shader errors.'),
        ('quest_triggers', 'Quest state and trigger transitions', 'Exercise every reachable q_skalitz objective and branch, recording native objective state before and after.'),
        ('audio', 'Voice, subtitles and cutscene exit', 'Play dialogue with source speaker, voice and subtitle IDs; finish and skip cutscenes and verify input restoration.'),
        ('save_restore', 'Save, load and return travel', 'Save a partially completed quest; restart, Continue and repeat travel without duplication or lost progress.'),
        ('weather_time', 'Time and weather', 'Advance through the source time policy; verify weather and schedules outside intentionally paused cutscenes.'),
    ]
    groups = [
        (('NPC', 'NPC_Female'), 'npc_ai', 'NPC AI and Henry combat', 'Approach, talk, provoke, exchange attacks, flee and surrender; test native completion events and Henry input after each.'),
        (('NPC', 'NPC_Female'), 'crime_guards', 'Crime, witnesses and guards', 'Commit and resolve a witnessed crime, including pursuit, punishment and surrender without targeting locks.'),
        (('AnimDoor',), 'doors', 'Doors and locks', 'Open and close source doors; verify collision, lock, key and ownership behavior.'),
        (('Shop',), 'trade', 'Trading and haggling', 'Open the source shop, buy and sell, check stock and money deltas, haggle and verify dialogue cleanup.'),
        (('Horse',), 'horses', 'Horse ownership and calling', 'Call, mount, ride and dismount; verify ownership, tack, inventory, save/load and return travel.'),
        (('Bed',), 'beds', 'Sleeping', 'Use an owned and unowned bed and verify time, needs, crime policy and wake-up positioning.'),
        (('Stash', 'PickableItem'), 'inventory', 'Inventory and world items', 'Take, transfer and drop authored items; verify ownership, quantities and quest item requirements.'),
        (('Grindstone',), 'grindstone', 'Grindstone', 'Enter and exit sharpening, checking item condition changes and restored controls.'),
        (('DiceMinigameCup',), 'dice', 'Dice minigame', 'Start, finish and cancel a dice game; verify stakes and control restoration.'),
    ]
    cases += [(key, title, action) for classes, key, title, action in groups if any(present.get(c, 0) for c in classes)]
    return [dict(id=key, title=title, action=action, status='not_tested',
                 evidence_required=['runtime observations', 'before/after state', 'game log interval'])
            for key, title, action in cases]


def build_manifest(source, profile='q_skalitz_normal', quest='q_skalitz', destination='kcd1_rataje'):
    source = Path(source).resolve()
    with RetailSourceReader(source) as reader:
        records = reader(source, {
            'profiles': ('Levels/rataje/level.pak', 'whdata_1'),
            'souls': ('Levels/rataje/level.pak', 'whdata_0'),
            'new_game': ('GameData.pak', 'Libs/UI/UIActions/MM_NewGame.xml'),
            'quest_behavior': ('Scripts.pak', f'Libs/AI/quests/{quest}.xml'),
        })
        entry = discover_entry(records['new_game']['data'])['dispatch']
        records.update(reader(source, {'master': ('Scripts.pak', 'Libs/AI/quests/' + entry['entity_name'] + '.xml')}))
        profile_root = ET.fromstring(records['profiles']['data'])
        matching = [p for p in profile_root.iter('GameProfile') if p.findtext('Name') == profile]
        if len(matching) != 1:
            raise ValueError('Source profile missing or ambiguous: ' + profile)
        docs = {}
        for index, layer in enumerate(matching[0].findall('./GameLayers/GameLayer')):
            path = 'layers/' + layer.text.lower() + '.xml'
            record = reader(source, {'layer': ('Levels/rataje/level.pak', path)})['layer']
            docs[path] = record['data']
            records['layer_' + str(index)] = record
        inventory = source_inventory(records['profiles']['data'], records['souls']['data'], docs, profile)
        behavior_docs = {records[k]['entry']: records[k]['data'] for k in ('master', 'quest_behavior')}
        opening = dict(dispatch=entry,
                       ui_node_classes=[n.get('Class') for n in ET.fromstring(records['new_game']['data']).findall('./Nodes/Node')],
                       profile_operations=[dict(document=name, tree=tree.get('name'), arguments=dict(n.attrib))
                           for name, data in behavior_docs.items()
                           for tree in ET.fromstring(data).findall('BehaviorTree')
                           for n in tree.iter('EnableProfile') if profile in str(n.attrib)],
                       dispatch_must_not_be_called_by_acceptance_tests=True)
        return dict(schema=1, source_game=str(source), source_level='rataje', destination_level=destination,
                    quest=quest, inventory=inventory, opening=opening,
                    provenance={k: dict(entry=v['entry'], selected=v['candidates'][-1]) for k, v in records.items()},
                    controller_conversion_gaps=controller_gaps(behavior_docs),
                    acceptance=acceptance_cases(inventory), fully_verified=False,
                    limitations=['Profile is the authored selected slice; global and conditional profile closure remains separate.',
                                 'Missing adapters are conversion work, not permanently excluded content.',
                                 'Presence probes do not establish combat, dialogue, inventory, quest or save/load behavior.'])


def lua_string(value):
    """JSON string escapes are not all Lua escapes; emit decimal byte escapes."""
    return '"' + ''.join('\\%03d' % b for b in value.encode('utf-8')) + '"'


def probe_lua(manifest, start=0, count=32, radius=180):
    if not 0 <= start or not 1 <= count <= 64 or not math.isfinite(radius) or not 0 < radius <= 1000:
        raise ValueError('Invalid bounded runtime probe range/radius')
    entries = [e for e in manifest['inventory']['entities'] if e['source_class'] in INTERACTIVE]
    selected = entries[start:start + count]
    rows = []
    for entity in selected:
        p = entity['position']
        xyz = ',p={x=%.9g,y=%.9g,z=%.9g}' % (p['x'], p['y'], p['z']) if p else ''
        rows.append('{key=%s,name=%s,kind=%s%s}' %
                    (lua_string(entity['source_id']), lua_string(entity['name'] or ''),
                     lua_string(entity['source_class']), xyz))
    return """local expected={%s}
local player=System.GetEntityByName('Henry') or (g_localActorId and System.GetEntity(g_localActorId))
local map=tostring(System.GetCVar('sv_map') or '')
if not string.find(string.lower(map),%s,1,true) then
 return {ok=false,status='wrong_level',map=map,expected_level=%s}
end
if not player then return {ok=false,status='player_missing',map=map} end
local pos=player:GetWorldPos()
local observations={}
for _,row in ipairs(expected) do
 local out={source_id=row.key,name=row.name,source_class=row.kind}
 if not row.p then out.status='not_tested_missing_source_position'
 elseif (row.p.x-pos.x)^2+(row.p.y-pos.y)^2>%g then out.status='not_tested_outside_radius'
 else
  local ent=System.GetEntityByName(row.name)
  if not ent then out.status='missing_nearby_entity'
  else
   out.status='present';out.runtime_id=tostring(ent.id);out.actor=ent.actor~=nil
   out.inventory=ent.inventory~=nil;out.soul=ent.soul~=nil
   if ent.GetWorldPos then out.position=ent:GetWorldPos() end
   if ent.IsHidden then out.hidden=ent:IsHidden() end
  end
 end
 observations[#observations+1]=out
end
return {ok=true,check='source_entity_presence',map=map,player=pos,radius=%g,observations=observations,
 behavior_verified=false}
""" % (','.join(rows), lua_string(manifest['destination_level'].lower()),
        lua_string(manifest['destination_level']), radius * radius, radius)


def evaluate(manifest, results):
    """Never convert an absent/not-tested behavioral observation into a pass."""
    expected = {e['source_id'] for e in manifest['inventory']['entities'] if e['source_class'] in INTERACTIVE}
    observed, errors = {}, []
    for result in results:
        if not result.get('ok'):
            errors.append(result)
            continue
        for item in result.get('observations', []):
            identity = item.get('source_id')
            if identity not in expected or identity in observed:
                errors.append(dict(status='unexpected_or_duplicate_observation', source_id=identity))
            else:
                observed[identity] = item
    counts = Counter(item['status'] for item in observed.values())
    counts['not_tested_no_observation'] += len(expected - observed.keys())
    return dict(schema=1, profile=manifest['inventory']['profile'], presence_counts=dict(counts),
                errors=errors, observations=list(observed.values()), acceptance=manifest['acceptance'],
                fully_verified=False,
                note='Presence is not behavior. Out-of-radius entities must be inspected by travelling to their authored area.')


def run_probes(manifest, client, radius=180):
    """Use the MCP client's execute_lua path; no desktop input or quest mutation."""
    results = []
    count = sum(e['source_class'] in INTERACTIVE for e in manifest['inventory']['entities'])
    for start in range(0, count, 32):
        request = json.dumps({'code': probe_lua(manifest, start, 32, radius)}, separators=(',', ':'))
        process = subprocess.run([str(client), 'call', 'execute_lua', request],
                                 capture_output=True, text=True, timeout=30)
        if process.returncode:
            results.append(dict(ok=False, status='mcp_client_failed', stderr=process.stderr[-2000:]))
            break
        response = json.loads(process.stdout)
        # Client returns a transport envelope with the engine result in value.
        payload = response.get('value', response.get('result', response))
        if not isinstance(payload, dict):
            results.append(dict(ok=False, status='unrecognized_mcp_response', response=response))
            break
        results.append(payload)
        if payload.get('status') in ('wrong_level', 'player_missing'):
            break
    return evaluate(manifest, results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kcd1', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--profile', default='q_skalitz_normal')
    parser.add_argument('--quest', default='q_skalitz')
    parser.add_argument('--destination', default='kcd1_rataje')
    parser.add_argument('--probe-start', type=int)
    parser.add_argument('--radius', type=float, default=180)
    parser.add_argument('--client', type=Path)
    parser.add_argument('--results', type=Path)
    args = parser.parse_args()
    if args.kcd1:
        if args.manifest.exists():
            raise FileExistsError('Choose a new manifest path; existing evidence is preserved')
        manifest = build_manifest(args.kcd1, args.profile, args.quest, args.destination)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    else:
        manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    if args.probe_start is not None:
        print(probe_lua(manifest, args.probe_start, radius=args.radius))
    elif args.client:
        if not args.results or args.results.exists():
            raise ValueError('Supply a new --results file for live evidence')
        report = run_probes(manifest, args.client, args.radius)
        args.results.parent.mkdir(parents=True, exist_ok=True)
        args.results.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({k: report[k] for k in ('presence_counts', 'errors', 'fully_verified')}))
    else:
        print(json.dumps(dict(manifest=str(args.manifest), layers=len(manifest['inventory']['layers']),
                              counts=manifest['inventory']['counts'], unresolved=manifest['inventory']['unresolved'],
                              acceptance_cases=len(manifest['acceptance']), fully_verified=False), indent=2))


if __name__ == '__main__':
    main()
