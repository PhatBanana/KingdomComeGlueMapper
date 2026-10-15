"""Import source starting equipment and bind it to a selected New Game edge."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_sources import RetailSourceReader
from campaign_dependency_adapters import SourceTables
from campaign_initial_loadout import resolve, bind_player_before
from container_items import build as import_items
from build_english_audio_test import merge_audio_strings
from build_horse_trader_test import rewrite, digest
from upgrade_map import read


def merge_item_strings(archive, additions):
    """Localization keys are global across tables, not scoped to one XML file."""
    known = {}
    for name in archive.namelist():
        if not name.lower().endswith('.xml'): continue
        for row in ET.fromstring(read(archive, name)).iter('Row'):
            cells = [c.text or '' for c in row.findall('Cell')]
            if cells: known[cells[0]] = cells
    pending = ET.Element('Table')
    for row in additions:
        cells = [c.text or '' for c in row.findall('Cell')]
        if not cells: continue
        if cells[0] in known:
            if cells != known[cells[0]]:
                raise ValueError('Conflicting installed item localization: '+cells[0])
        else:
            pending.append(row); known[cells[0]] = cells
    return merge_audio_strings(read(archive, 'text_ui_items.xml'), ET.tostring(pending))


def build(source, target, mod, output, binding):
    source, target, mod, output = map(Path, (source, target, mod, output))
    if output.exists(): raise FileExistsError('Choose a fresh output directory')
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        # Select the authored player instance, preserving per-instance overrides.
        with zipfile.ZipFile(source/'Data/Levels'/binding['source_level']/'level.pak') as archive:
            world = ET.fromstring(read(archive, 'whdata_0'))
        instances = [s for s in world.findall('./SoulList/Souls/Soul')
                     if s.findtext('Guid') == binding['source_instance']]
        if len(instances) != 1: raise ValueError('Missing or ambiguous source actor instance')
        instance = instances[0]
        overrides = {}
        for field, path in [('initial_clothing_preset_id', 'StaticData/InitialClothingDescription/PresetId'),
                            ('initial_weapon_preset_id', 'StaticData/InitialWeaponPresetId')]:
            value = instance.findtext(path)
            if value: overrides[field] = value
        plan = resolve(tables, instance.findtext('SharedSoulGuid'), overrides)
    dependencies = output/'dependencies'
    imported = import_items(source, target, mod, dependencies, plan['dependencies'],
                            asset_namespace='initialloadout', origin='source_initial_loadout')
    with zipfile.ZipFile(target/'Data/IPL_GameData.pak') as archive:
        definitions = read(archive, 'Libs/concept/definitions.xml')
    package = mod/'Data/gluemappertravel.pak'
    with zipfile.ZipFile(package) as archive:
        original = read(archive, binding['graph'])
    blob = bind_player_before(original, plan, imported['registered_items'],
                              definitions=definitions, **{k: binding[k] for k in
                              ('soul_asset','destination','input_port','source_event','namespace')})
    rewrite(package, output/'gluemappertravel.pak', {binding['graph']: blob})
    strings = ET.Element('Table')
    with zipfile.ZipFile(output/'gluemapper_initial_loadout.pak', 'x', zipfile.ZIP_STORED) as archive:
        for path in sorted((dependencies/'converted').rglob('*')):
            if not path.is_file(): continue
            name = path.relative_to(dependencies/'converted').as_posix()
            if name.lower().startswith('localization/english/'):
                strings.extend(ET.fromstring(path.read_bytes()))
            else: archive.writestr(name, path.read_bytes())
    locale = mod/'Localization/English_xml.pak'
    with zipfile.ZipFile(locale) as archive:
        merged = merge_item_strings(archive, strings)
    rewrite(locale, output/'English_xml.pak', {'text_ui_items.xml': merged})
    report = dict(binding=binding, plan=plan, items=imported['registered_items'],
                  baselines={'Data/gluemappertravel.pak': digest(package),
                             'Localization/English_xml.pak': digest(locale)},
                  runtime_verified=False, installed=False)
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source','target','mod','output','binding'):
        parser.add_argument('--'+key, type=Path, required=True)
    args = vars(parser.parse_args())
    args['binding'] = json.loads(args['binding'].read_text())
    print(json.dumps(build(**args), indent=2))
