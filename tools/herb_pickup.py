"""Register generated vegetation models with native KCD2 harvesting descriptors."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from audit_herb_pickup import normalize, table_rows
from compiled_terrain import parse
from upgrade_map import read, xml
from vegetation_gi import upgrade_group


def recover_report_model_map(source_game, terrain_pak, vegetation_report, instances_report):
    """Replay group selection for a legacy build and verify its output records."""
    from merged_vegetation import inventory
    from vegetation import read_all_instances
    from entity_visuals import initial_layer
    old = json.loads(Path(vegetation_report).read_text())
    completed = json.loads(Path(instances_report).read_text())
    with zipfile.ZipFile(Path(source_game) / 'Data/Levels/rataje/level.pak') as archive:
        source = parse(read(archive, 'terrain/terrain.dat'))
        _, merged, _ = inventory(archive, len(source.tables['vegetation']['paths']))
        layers = ET.fromstring(read(archive, 'leveldata.xml')).find('Layers')
        allowed = {0} | {int(e.get('Id')) for e in layers if initial_layer(e.get('Name'))}
    inherited = old['selected_instances']
    offsets = {r['offset'] for r in inherited}
    old_groups = sorted({r['group'] for r in inherited} | merged)
    records, _ = read_all_instances(source)
    additions = {r['group'] for r in records if r['offset'] not in offsets and r['layer'] in allowed}
    failures = {int(g) for g in completed['failures']}
    groups = old_groups + sorted(additions - set(old_groups) - failures)
    with zipfile.ZipFile(terrain_pak) as archive:
        target = parse(read(archive, 'terrain/terrain.dat'))
    if len(groups) != len(target.tables['vegetation']['paths']):
        raise ValueError('Legacy report does not match installed vegetation group count')
    mappings = []
    for i, g in enumerate(groups):
        def signature(terrain, index):
            start = terrain.tables['vegetation']['offset'] + index * 360
            record = upgrade_group(terrain.data[start:start+360])
            return record[256:320]+record[324:336]+record[340:]
        expected = 'glueveg/' + (old['level'] if i < len(old_groups) else completed['level']) + '/mesh' + str(i) + '.cgf'
        actual = normalize(target.tables['vegetation']['paths'][i])
        if signature(source, g) != signature(target, i) or actual != expected:
            raise ValueError('Legacy report group identity mismatch: ' + actual)
        mappings.append({'source': source.tables['vegetation']['paths'][g], 'target': actual})
    return mappings


def recover_model_map(source_game, terrain_pak):
    """Recover old-build provenance only when preserved group fields agree.

    Both vegetation stages preserve these bytes, as checked by complete_instances.
    Ambiguous source identities are reported, never guessed from mesh numbers.
    """
    with zipfile.ZipFile(Path(source_game) / 'Data/Levels/rataje/level.pak') as archive:
        source = parse(read(archive, 'terrain/terrain.dat'))
    with zipfile.ZipFile(terrain_pak) as archive:
        target = parse(read(archive, 'terrain/terrain.dat'))
    def rows(terrain):
        start = terrain.tables['vegetation']['offset']
        for i, path in enumerate(terrain.tables['vegetation']['paths']):
            record = terrain.data[start+i*360:start+(i+1)*360]
            record = upgrade_group(record)
            yield normalize(path), record[256:320]+record[324:336]+record[340:]
    identities = {}
    for name, signature in rows(source):
        identities.setdefault(signature, set()).add(name)
    mappings, unresolved = [], []
    for name, signature in rows(target):
        candidates = identities.get(signature, set())
        if len(candidates) == 1:
            mappings.append({'source': next(iter(candidates)), 'target': name})
        else:
            unresolved.append({'target': name, 'source_candidates': sorted(candidates),
                               'reason': 'ambiguous_or_missing_preserved_group_identity'})
    return mappings, unresolved


def registration(source_game, target_game, mappings):
    source_models, _ = table_rows(Path(source_game), 'pickable_area_material')
    source_desc, _ = table_rows(Path(source_game), 'pickable_area_desc')
    target_desc, _ = table_rows(Path(target_game), 'pickable_area_desc')
    target_items, _ = table_rows(Path(target_game), 'item')
    source_models = {normalize(r['material_name']): r for r in source_models}
    source_desc = {r['id']: r for r in source_desc}
    target_desc = {r['id']: r for r in target_desc}
    target_items = {normalize(r['Id']) for r in target_items}
    root = ET.Element('database', name='barbora')
    rows = ET.SubElement(root, 'pickable_area_materials', version='1')
    emitted, registered, missing = {}, [], []
    for mapping in mappings:
        src, dst = normalize(mapping['source']), normalize(mapping['target'])
        entry = source_models.get(src)
        if entry is None:
            continue  # Decorative vegetation must not become pickable.
        ident = entry['pickable_area_id']
        original, native = source_desc.get(ident), target_desc.get(ident)
        if (original is None or native is None or
                normalize(original['guid_item_picked']) != normalize(native['guid_item_picked']) or
                normalize(native['guid_item_picked']) not in target_items):
            missing.append(dict(mapping, descriptor_id=ident, reason='missing_or_conflicting_native_item_contract'))
            continue
        if dst in emitted and emitted[dst] != ident:
            raise ValueError('Conflicting herb descriptor for ' + dst)
        if dst not in emitted:
            ET.SubElement(rows, 'pickable_area_material', material_name=dst, pickable_area_id=ident)
            emitted[dst] = ident
            registered.append(dict(mapping, descriptor_id=ident, item_id=native['guid_item_picked'], name=native['name']))
    mapped_sources = {normalize(m['source']) for m in mappings}
    absent = [dict(row, reason='source_model_not_present_in_converted_model_map')
              for path, row in source_models.items() if path not in mapped_sources]
    return xml(root), {'registered': registered, 'unresolved': missing,
                      'source_models_not_imported': absent, 'runtime_verified': False}


def build_registration(source_game, target_game, converted_data, terrain_pak):
    mapping_file = Path(converted_data) / 'herb-model-map.json'
    if mapping_file.exists():
        mappings, unresolved = json.loads(mapping_file.read_text()), []
        provenance = 'builder_model_map'
    else:
        mappings, unresolved = recover_model_map(source_game, terrain_pak)
        provenance = 'preserved_terrain_group_fields'
    payload, report = registration(source_game, target_game, mappings)
    report.update(mapping_provenance=provenance, unresolved_group_identities=unresolved)
    return payload, report
