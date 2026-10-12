"""Convert authored KCD1 bench places to individual native KCD2 sitting slots."""
import copy
import xml.etree.ElementTree as ET

from chairs import inventory, existing_group
from cooking_pots import rotate, vector
from entity_visuals import world_transform, quaternion_product as qmul
from campaign_entity_links import append_links
from seating_animations import install
from upgrade_map import read


def convert(files, source, native, source_helpers, guid, area=None, incremental=False):
    entities, benches, deferred = inventory(source, 'Bench')
    helper_root = ET.fromstring(source_helpers)
    native_entities = {e.get('EntityId'): e for e in ET.fromstring(read(native, 'objects_mission0.xml')).iter('Entity')}
    donors = {}
    for e in native_entities.values():
        p = e.find('Properties')
        if e.get('EntityClass') != 'StanceSmartObject' or p is None: continue
        family = p.get('soclass_SmartObjectHelpers', '')
        if not family.startswith('Sit_1Place_Bench_'): continue
        for link in e.findall('EntityLinks/Link'):
            t = native_entities.get(link.get('TargetId'))
            if link.get('Name') == '' and t is not None and t.find("Properties/Click[@UseMessage='@ui_use_sit']") is not None:
                donors.setdefault(family, (e, t))
    root = ET.fromstring(files['objects_mission0.xml'])
    if not incremental and any(e.get('Name', '').startswith('gm_bench_') for e in root.iter('Entity')):
        raise ValueError('Benches already converted; use the pre-conversion baseline')
    next_id = max(int(e.get('EntityId', '0')) for e in root.iter('Entity')) + 1
    records, network, unsupported = [], [], []
    for bench in benches:
        bp, bq, bs = world_transform(bench, entities)
        if area and sum((bp[i]-area[i])**2 for i in range(3)) > area[3]**2: continue
        source_family = bench.find('Properties').get('soclasses_SmartObjectHelpers')
        places = [h for h in helper_root.findall('Helper') if h.get('className') == source_family and 'Category(Sit)' in h.get('description', '')]
        places.sort(key=lambda h: float(h.get('pos').split(',')[0]))
        if not places:
            unsupported.append({'source_id': bench.get('EntityId'), 'family': source_family}); continue
        prefix = f"gm_bench_{bench.get('EntityId')}_"
        expected = {f'{prefix}{i}_{kind}' for i in range(len(places)) for kind in ('StanceSmartObject', 'ActionTrigger')}
        if incremental and existing_group(root, prefix, expected):
            continue
        misc = bench.find('Properties/Script')
        table = 'hasTable:true' in (misc.get('Misc', '') if misc is not None else '')
        group = []
        for index, helper in enumerate(places):
            family = 'Sit_1Place_Bench_Low'
            if table:
                family += '_Table_' + ('Right' if index == 0 else 'Left' if index == len(places)-1 else 'BothBack')
            elif 'Front' in source_family: family += '_FrontOnly'
            owner, trigger = donors[family]
            dp, dq, _ = world_transform(owner, native_entities)
            hp = tuple(map(float, helper.get('pos').split(',')))
            hq = tuple(map(float, helper.get('rot', '1,0,0,0').split(',')))
            offset = rotate(bq, tuple(hp[i]*bs[i] for i in range(3)))
            sp = tuple(bp[i]+offset[i] for i in range(3)); sq = qmul(bq, hq)
            delta = qmul(sq, (dq[0], -dq[1], -dq[2], -dq[3]))
            pair = []
            for original in (owner, trigger):
                node = copy.deepcopy(original)
                for attr in ('Prefab', 'EditorLayer', 'Layer', 'ParentId', 'ParentGuid'): node.attrib.pop(attr, None)
                for child in list(node):
                    if child.tag == 'EntityLinks': node.remove(child)
                node.set('EntityId', str(next_id)); next_id += 1
                node.set('EntityGuid', guid(f"bench/{bench.get('EntityId')}/{helper.get('name')}/{original.get('EntityClass')}"))
                node.set('Name', f"gm_bench_{bench.get('EntityId')}_{index}_{original.get('EntityClass')}")
                p, q, _ = world_transform(original, native_entities)
                relative = rotate(delta, tuple(p[i]-dp[i] for i in range(3)))
                node.set('Pos', vector(tuple(sp[i]+relative[i] for i in range(3))))
                node.set('Rotate', vector(qmul(delta, q)))
                node.find('Properties').set('bOwnedByHome', '0')
                ET.SubElement(node, 'EntityLinks')
                pair.append(node)
            def link(a, b, label):
                ET.SubElement(a.find('EntityLinks'), 'Link', TargetId=b.get('EntityId'), TargetGuid=b.get('EntityGuid'), Name=label)
                if label: network.append((a.get('EntityGuid'), b.get('EntityGuid'), label))
            link(pair[0], pair[1], ''); link(pair[1], pair[0], '')
            if table: link(pair[0], pair[0], 'withTable')
            for previous in group:
                link(pair[0], previous, 'neighbor'); link(previous, pair[0], 'neighbor')
            group.append(pair[0]); root.extend(pair)
        records.append({'source_id': bench.get('EntityId'), 'family': source_family, 'places': len(group), 'position': list(bp), 'table': table})
    updated = dict(files)
    updated['objects_mission0.xml'] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    updated['waitinglinks.xml'] = append_links(files.get('waitinglinks.xml'), network)
    updated, animations = install(updated, native)
    return updated, {'converted_benches': len(records), 'places': sum(r['places'] for r in records),
                     'records': records, 'unsupported': unsupported, 'inactive': deferred, 'animation_contract': animations, 'test_area': area}
