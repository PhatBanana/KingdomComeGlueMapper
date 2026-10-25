"""Developer-only rebuild of receipt-owned source NPC appearances.

Builds a separate complete package for desktop_setup.install_transaction. It
does not install, change gameplay, or expose diagnostic controls in Setup UI.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from setup_campaign import RECEIPT, digest, verify_package
from setup_package_upgrade import rewrite

TRAVEL = 'Data/gluemappertravel.pak'
LOCALE = 'Localization/English_xml.pak'


def imports(archive, selected):
    """Resolve explicit source identities from importer receipts, never names guessed from meshes."""
    found = {}
    for name in archive.namelist():
        if not name.startswith('Libs/GlueMapper/PersonImport/') or not name.endswith('.json'):
            continue
        row = json.loads(archive.read(name))
        person = row.get('person')
        if person not in selected:
            continue
        namespace = row.get('namespace', '')
        if not re.fullmatch(r'gm_person_[0-9a-f]{32}', namespace):
            raise ValueError('Unsupported appearance ownership: ' + person)
        if name != 'Libs/GlueMapper/PersonImport/' + namespace + '.json' or person in found:
            raise ValueError('Ambiguous source appearance: ' + person)
        if row.get('appearance') != 'character_person_appearance':
            raise ValueError('Unsupported appearance adapter: ' + person)
        found[person] = namespace
    if set(found) != set(selected):
        raise ValueError('No imported appearance receipt for: ' + ', '.join(sorted(set(selected) - set(found))))
    return found


def owned_shards(package, files, namespace):
    pattern = re.compile(re.escape('Data/' + namespace) + r'(?:_\d{2,})?\.pak$')
    paths = sorted(name for name in files if pattern.fullmatch(name))
    if not paths:
        raise ValueError('Missing source appearance archives: ' + namespace)
    prefix = 'objects/characters/gluetravel/' + namespace + '/'
    for name in paths:
        with zipfile.ZipFile(package / name) as archive:
            if any(not entry.replace('\\', '/').lower().startswith(prefix) for entry in archive.namelist()):
                raise ValueError('Appearance archive contains unrelated assets: ' + name)
    return paths


def validate_resources(resources, namespace):
    for name, blob in resources.items():
        if not re.fullmatch(r'Libs/Tables/(?:Character|item)/[A-Za-z_]+__' + re.escape(namespace)
                            + r'(?:_clothes)?\.xml', name):
            raise ValueError('Appearance rebuild attempted an unrelated resource: ' + name)
        ET.fromstring(blob)


def verify_bindings(archive, character, namespace):
    """Refuse a rebuild requiring a gameplay/Storm migration instead of silently breaking it."""
    root = ET.fromstring(archive.read('Libs/Storm/appearance/' + namespace + '.xml'))
    actual = {node.tag[3:].lower(): node.get('name') for node in root.findall('.//operations/*')
              if node.tag.startswith('set')}
    if actual != character['appearance'] or character['inventory'] != namespace + '_clothes':
        raise ValueError('Appearance identities changed; explicit binding migration required: ' + namespace)


def stage(source, target, installed, output, people, *, notify=print):
    from build_profile_population_upgrade import clone_missing
    from build_recipe import require_current
    from build_quest_people_test import write_actor_paks
    from build_english_audio_test import merge_audio_strings
    from character_person import resolve_person
    from character_person_appearance import build_appearance
    from bake_pool import release
    from setup_pak_limits import validate as validate_pak_limits

    source, target, installed, output = map(lambda p: Path(p).resolve(), (source, target, installed, output))
    if not people or len(set(people)) != len(people):
        raise ValueError('Select one or more distinct imported source people')
    if output.exists() or output.is_relative_to(installed):
        raise ValueError('Choose a fresh output outside the installed package')
    notify('Verifying installed baseline')
    baseline = verify_package(installed)
    require_current(baseline)
    with zipfile.ZipFile(installed / TRAVEL) as archive:
        selected = imports(archive, people)
    shards = {name: owned_shards(installed, baseline['files'], ns) for name, ns in selected.items()}
    output.mkdir(parents=True)
    # Keep a verified, cheap recovery package. Every changed file is replaced,
    # never written through these links into either checkpoint or installation.
    package, recovery = output / 'package', output / 'baseline'
    clone_missing(installed, recovery)
    clone_missing(recovery, package)
    receipt = copy.deepcopy(baseline)
    resources, labels, converted = {}, [], []
    try:
        for name in people:
            namespace = selected[name]
            notify('Rebuilding appearance: ' + name)
            person = resolve_person(source, name, include_ai=False)
            if 'gm_person_' + person['soul']['soul_id'].replace('-', '') != namespace:
                raise ValueError('Source soul no longer matches import receipt: ' + name)
            appearance = output / 'people' / namespace
            character = build_appearance(source, target, person, namespace, appearance)
            with zipfile.ZipFile(recovery / TRAVEL) as archive:
                verify_bindings(archive, character, namespace)
            actor_stage = output / 'packed' / namespace
            actor_stage.mkdir(parents=True)
            paks, libs = write_actor_paks(appearance, actor_stage, namespace)
            validate_resources(libs, namespace)
            resources.update(libs)
            strings = appearance / 'Localization/English/text_ui_items.xml'
            if strings.exists():
                labels.append(strings.read_bytes())
            incoming = {'Data/' + p.name for p in paks}
            for old in shards[name]:
                if old not in incoming:
                    (package / old).unlink()
                    del receipt['files'][old]
            for pak in paks:
                relative = 'Data/' + pak.name
                pak.replace(package / relative)
                receipt['files'][relative] = digest(package / relative)
            record = dict(person=name, namespace=namespace, gender=character['gender'],
                          fitting=character.get('fitting'), archives=sorted(incoming),
                          runtime_verified=False)
            converted.append(record)
            (appearance / 'appearance-result.json').write_text(json.dumps(character, indent=2), encoding='utf-8')
    finally:
        release()
    rewrite(package, TRAVEL, resources)
    receipt['files'][TRAVEL] = digest(package / TRAVEL)
    if labels:
        with zipfile.ZipFile(package / LOCALE) as archive:
            before = blob = archive.read('text_ui_items.xml')
        for label in labels:
            blob = merge_audio_strings(blob, label)
        if blob != before:
            rewrite(package, LOCALE, {'text_ui_items.xml': blob})
            receipt['files'][LOCALE] = digest(package / LOCALE)
    report = dict(version=1, scope='explicit_imported_source_appearances', people=converted,
                  native_texture_streaming=True, runtime_verified=False,
                  recovery_package=str(recovery),
                  changed_files=[n for n, h in receipt['files'].items() if baseline['files'].get(n) != h],
                  removed_files=sorted(set(baseline['files']) - set(receipt['files'])))
    receipt['source_appearances'] = report
    temporary = package / (RECEIPT + '.pending')
    temporary.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    temporary.replace(package / RECEIPT)
    verify_package(package, hashes=False)
    validate_pak_limits(package)
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    notify('Candidate ready for bounded native playtest: ' + str(package))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'target', 'installed', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--person', action='append', required=True)
    args = parser.parse_args()
    stage(args.source, args.target, args.installed, args.output, args.person, notify=lambda s: print(s, flush=True))


if __name__ == '__main__':
    main()
