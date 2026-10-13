"""Stage imported quest items and native objective tracking over a development build.

Never installs implicitly. Existing scene, menu and actor packages are preserved.
"""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from container_items import build as import_items
from campaign_quest_items import bind
from build_english_audio_test import merge_audio_strings
from build_horse_trader_test import rewrite
from upgrade_map import read


def build(source, target, mod, model_path, quest_path, player_asset, output):
    source, target, mod, model_path, output = map(Path, (source, target, mod, model_path, output))
    if output.exists(): raise ValueError('Choose a fresh staging directory')
    model = json.loads(model_path.read_text(encoding='utf-8'))
    with zipfile.ZipFile(mod / 'Data/gluemappertravel.pak') as z:
        original = read(z, quest_path)
    ids = [r['item_id'] for r in model['tables']['quest_item']['rows'] if r.get('item_id')]
    dependencies = output / 'dependencies'
    import_items(source, target, mod, dependencies, ids, asset_namespace='questitems', origin=model['quest'])
    dependency_report = json.loads((dependencies / 'report.json').read_text())
    mapping = dependency_report['registered_items']
    blob, report = bind(original, model, mapping, dependency_report['item_names'], player_asset)
    files, strings = {}, {}
    for path in (dependencies / 'converted').rglob('*'):
        if not path.is_file(): continue
        name = path.relative_to(dependencies / 'converted').as_posix()
        if name.lower().startswith('localization/english/'):
            for row in ET.fromstring(path.read_bytes()):
                cells = row.findall('Cell')
                if len(cells) >= 2:
                    key = cells[0].text; value = cells[1].text or ''
                    if key in strings and [c.text for c in strings[key]] != [c.text for c in row]:
                        raise ValueError('Conflicting item string')
                    strings[key] = row
        else:
            if name in files: raise ValueError('Conflicting quest resource')
            files[name] = path.read_bytes()
    pak = output / 'gluemapper_quest_items.pak'
    with zipfile.ZipFile(pak, 'x', zipfile.ZIP_STORED, allowZip64=False) as z:
        for name, data in sorted(files.items()): z.writestr(name, data)
    rewrite(mod / 'Data/gluemappertravel.pak', output / 'gluemappertravel.pak', {quest_path: blob})
    locale = output / 'English_xml.pak'
    table = ET.Element('Table'); table.extend(strings.values())
    with zipfile.ZipFile(mod / 'Localization/English_xml.pak') as z:
        entries = [n for n in z.namelist() if n.lower() == 'text_ui_items.xml']
        if len(entries) != 1: raise ValueError('Expected native item localization table')
        name = entries[0]
        merged = merge_audio_strings(read(z, name), ET.tostring(table))
    rewrite(mod / 'Localization/English_xml.pak', locale, {name: merged})
    report.update(quest=model['quest'], item_map=mapping, strings=len(strings),
                  source_quest_sha256=hashlib.sha256(original).hexdigest(),
                  pak_sha256=hashlib.sha256(pak.read_bytes()).hexdigest())
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'target', 'mod', 'model', 'output'): p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--quest-path', required=True)
    p.add_argument('--player-asset', required=True)
    a = p.parse_args()
    r = build(a.source, a.target, a.mod, a.model, a.quest_path, a.player_asset, a.output)
    print(json.dumps(dict(converted=len(r['converted']), pending=len(r['pending']), runtime_verified=False)))
