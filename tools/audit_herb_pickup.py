"""Compare installed herb pickup contracts without modifying either game.

Reports source descriptor/item identity separately from model registration.
Does not infer runtime harvesting success from matching records.
"""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from upgrade_map import read


def normalize(value):
    return value.replace('\\', '/').lower()


def table_rows(game, table):
    """Read base table, then source patch replacements in filename order."""
    wanted = 'libs/tables/item/' + table + '.xml'
    result, origins = [], []
    for pak in [game / 'Data/Tables.pak', *sorted((game / 'Data/patch').glob('*.pak'))]:
        with zipfile.ZipFile(pak) as archive:
            for name in archive.namelist():
                if normalize(name) != wanted:
                    continue
                root = ET.fromstring(read(archive, name))
                result = [dict(e.attrib) for e in root.iter()
                          if e.tag in ('row', table)]
                if table == 'item' and not result:
                    result = [dict(e.attrib, _type=e.tag) for e in root.iter() if e.get('Id')]
                origins.append(str(pak) + ':' + name)
    return result, origins


def compare(source_desc, target_desc, source_models, target_models, target_items):
    by_id = {r['id']: r for r in target_desc}
    items = {normalize(r['Id']): r for r in target_items}
    models = {normalize(r['material_name']): r for r in target_models}
    descriptors = []
    for row in source_desc:
        other = by_id.get(row['id'])
        item = items.get(normalize(row['guid_item_picked']))
        issues = []
        if other is None:
            issues.append('missing_target_descriptor')
        elif normalize(other['guid_item_picked']) != normalize(row['guid_item_picked']):
            issues.append('descriptor_item_mismatch')
        if item is None:
            issues.append('missing_target_item')
        differences = {k: {'source': row.get(k), 'target': other.get(k)}
                       for k in ('amount', 'respawn_time', 'anim_speed', 'anim_fragment', 'anim_tags')
                       if other is not None and row.get(k, '') != other.get(k, '')}
        descriptors.append({'source': row, 'target': other, 'item_type': item.get('_type') if item else None,
                            'item_name': item.get('Name') if item else None,
                            'issues': issues, 'setting_differences': differences})
    registrations = []
    for row in source_models:
        target = models.get(normalize(row['material_name']))
        registrations.append({'source': row, 'exact_target_registration': target,
                              'target_models_for_descriptor': [r['material_name'] for r in target_models
                                                              if r['pickable_area_id'] == row['pickable_area_id']],
                              'issues': ['source_model_path_not_registered'] if target is None else
                                        (['model_descriptor_mismatch'] if target['pickable_area_id'] != row['pickable_area_id'] else [])})
    return descriptors, registrations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--mod', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    tables, evidence = {}, {}
    for label, game in [('source', args.source), ('target', args.target)]:
        for name in ('pickable_area_desc', 'pickable_area_material', 'item'):
            tables[label, name], evidence[label + '/' + name] = table_rows(game, name)
    descriptors, models = compare(tables['source', 'pickable_area_desc'], tables['target', 'pickable_area_desc'],
                                  tables['source', 'pickable_area_material'], tables['target', 'pickable_area_material'],
                                  tables['target', 'item'])
    # Record overrides rather than silently treating the base database as the
    # effective modded database. Merge evaluation needs the engine's rules.
    overrides = []
    for pak in sorted((args.mod / 'Data').glob('*.pak')):
        with zipfile.ZipFile(pak) as archive:
            overrides.extend({'pak': str(pak), 'entry': n} for n in archive.namelist()
                             if 'pickable_area_' in normalize(n))
    report = {'evidence': evidence, 'descriptors': descriptors, 'model_registrations': models,
              'mod_pickable_table_overrides': overrides, 'runtime_verified': False,
              'summary': {'source_descriptors': len(descriptors),
                          'matching_descriptor_and_item': sum(not r['issues'] for r in descriptors),
                          'source_model_registrations': len(models),
                          'missing_exact_source_model_paths': sum('source_model_path_not_registered' in r['issues'] for r in models)}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['summary'], indent=2))
    print('Mod pickable table overrides:', len(overrides))
    print('Report:', args.output)


if __name__ == '__main__':
    main()
