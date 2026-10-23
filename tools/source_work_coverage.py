"""Audit profile ownership of authored work; discovery is not job activation.

Profile membership is authoritative. A globally loaded area does not establish
that its selected workplaces belong to the actor's currently selected profile.
Unknown ownership stays unknown; coordinates and actor names are never gates.
"""
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from campaign_bindings import parse_link_labels
from character_station_work import unquote
from upgrade_map import read


def path_key(path):
    return path.replace('\\', '/').lower()


class Ownership:
    def __init__(self, profiles, documents):
        self.profiles = {}
        for profile in profiles.iter('GameProfile'):
            name = profile.findtext('Name')
            for layer in profile.findall('GameLayers/GameLayer'):
                self.profiles.setdefault('layers/' + layer.text.lower() + '.xml', set()).add(name)
        self.by_guid, self.by_id = {}, {}
        for path, blob in documents.items():
            root = blob if isinstance(blob, E.Element) else E.fromstring(blob)
            for entity in root.iter('Entity'):
                guid = entity.get('EntityGuid')
                if not guid: continue
                record = dict(guid=guid, entity_id=entity.get('EntityId'), name=entity.get('Name'),
                              source=path_key(path), profiles=sorted(self.profiles.get(path_key(path), ())),
                              position=entity.get('Pos'))
                self.by_guid.setdefault(int(guid, 16), []).append(record)
                self.by_id.setdefault(entity.get('EntityId'), []).append(record)

    def target(self, guid=None, entity_id=None):
        records = self.by_guid.get(int(guid, 16), []) if guid not in (None, '', '0') else self.by_id.get(entity_id, [])
        if len(records) != 1:
            raise ValueError('Missing or ambiguous source workplace ownership')
        record = records[0]
        if entity_id not in (None, '', '0') and record['entity_id'] != entity_id:
            raise ValueError('Workplace source ID and GUID disagree')
        return dict(record)

    def availability(self, record, selected):
        record = dict(record)
        owners = set(record['profiles'])
        if owners:
            record['availability'] = 'selected_profile' if owners.intersection(selected) else 'outside_selected_profiles'
        elif record['source'] == 'objects_mission0.xml':
            record['availability'] = 'global_mission'
        else:
            record['availability'] = 'unowned_layer_unknown'
        return record


def compound_targets(entry, controller):
    """Reproduce the source's one-hop compWork source-behavior filter only.

    This resolves candidate ownership, not reservation, requestability or timing.
    Those native lifecycle contracts are deliberately not replaced by a seat.
    """
    root = controller.find("BehaviorTree[@name='CompoundWork2_main']/Root")
    searches = [] if root is None else [n for n in root.iter('GraphSearch')
                                        if unquote(n.get('SubGraph', '')) == 'compWork']
    if len(searches) != 1:
        raise ValueError('Compound work requires one supported source search')
    search = searches[0]
    filter_node = search.find('Gen2HasBehaviorFilter')
    if (unquote(search.get('depth', '')) != '1'
            or unquote(search.get('Origin', '')) != 't_compoundWorkplace'
            or filter_node is None
            or unquote(filter_node.get('Condition', '')) != '$compWork.srcBeh == $__behaviorName'
            or unquote(filter_node.get('BehaviorList', '')) != '$compWork.behavior'):
        raise ValueError('Unsupported compound workplace selection contract')
    behavior = entry['behavior']['sa_behaviour_tag_name']
    result = []
    for link in entry['target_links']:
        if not link.get('Name', '').strip(): continue
        for label in parse_link_labels(link['Name']):
            if label['tag'] != 'compWork': continue
            if label['named'].get('srcBeh') == behavior:
                result.append(dict(link))
    return result


def assess(entry, ownership, selected_profiles, *, compound=None):
    selected = set(selected_profiles)
    area = ownership.availability(ownership.target(entry['area'].get('EntityGuid'), entry['area'].get('EntityId')), selected)
    resources = []
    if compound is not None:
        resources = [ownership.availability(ownership.target(l.get('TargetGuid'), l.get('TargetId')), selected)
                     for l in compound_targets(entry, compound)]
    if area['availability'] == 'outside_selected_profiles':
        status = 'outside_selected_profiles'
        reason = 'The authored work area belongs exclusively to other source profiles.'
    elif resources and all(r['availability'] == 'outside_selected_profiles' for r in resources):
        status = 'outside_selected_profiles'
        reason = 'Every selected source workplace belongs exclusively to other source profiles.'
    elif area['availability'] == 'selected_profile':
        status = 'selected_profile_assignment'
        reason = 'The source work area belongs to a selected profile; lifecycle coverage is assessed separately.'
    else:
        status = 'ownership_unresolved'
        reason = 'Global or unowned areas do not prove local job ownership; no distance/name heuristic was applied.'
    return dict(activity=entry['activity'], behavior=entry['behavior'], area=area,
                source_link=entry['source_link'], resources=resources, ownership_status=status,
                reason=reason, runtime_verified=False, activates_job=False)


def audit(source, profiles, source_level='rataje'):
    from build_profile_systems import source_world
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    from profile_population_upgrade import discover
    from character_schedule import plan
    source = Path(source)
    with zipfile.ZipFile(source / 'Data/Levels' / source_level / 'level.pak') as archive:
        documents, _ = source_world(archive)
        ownership = Ownership(E.fromstring(read(archive, 'whdata_1')), documents)
    jobs, pending = [], []
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        roster, people, _ = discover(source, source_level, profiles, tables)
        compound = None
        for name, person in sorted(people.items()):
            schedule = plan(person, tables)
            pending.extend(dict(person=name, **row) for row in schedule['pending'])
            for entry in schedule['resolved']:
                is_compound = (path_key(entry['behavior']['tree_file']), entry['behavior']['tree_name']) == (
                    'final/sa_compoundworkcamp.xml', 'CompoundWorkCamping')
                if is_compound and compound is None:
                    blob = reader(source, {'compound': ('Scripts.pak', 'Libs/AI/final/sa_compoundwork.xml')})
                    compound = E.fromstring(blob['compound']['data'])
                jobs.append(dict(person=name, **assess(entry, ownership, profiles,
                                                      compound=compound if is_compound else None)))
    return dict(version=1, source_level=source_level, selected_profiles=list(profiles),
                actor_count=len(roster), assignments=jobs, pending=pending,
                ownership_counts=dict(Counter(j['ownership_status'] for j in jobs)),
                scope='Source profile ownership audit only; assignments are not completed job adapters.',
                runtime_verified=False)


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--profile', required=True, action='append')
    parser.add_argument('--source-level', default='rataje')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.source, args.profile, args.source_level)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result['ownership_counts']))
