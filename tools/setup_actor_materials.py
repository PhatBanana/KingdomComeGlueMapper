"""Upgrade packaged male appearances without rebuilding actor/world registration."""
from contextlib import ExitStack
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from upgrade_map import read, xml


def upgrade(package, target, notify=lambda *a: None, cancelled=lambda: False):
    from audit_character_bodies import Assets
    from character_native_materials import convert_character_materials
    from build_quest_people_test import write_actor_paks
    from setup_campaign import digest
    package = Path(package).resolve()
    travel = package/'Data/gluemappertravel.pak'
    with zipfile.ZipFile(travel) as archive:
        documents = {n: ET.fromstring(read(archive, n)) for n in archive.namelist()
                     if re.fullmatch(r'Libs/Tables/Character/CharacterComponent__gm_person_[0-9a-f]+\.xml', n)}
    selected = []
    for name, document in documents.items():
        component = document.find('CharacterComponents/Component')
        if component is None or component.get('Gender') != 'Male':
            continue
        # Both clean builds and migrated builds carry this native feature.
        if any(f.get('Name') == 'GarmentBase' for f in component.iter('Feature')):
            continue
        selected.append((name, document, component))
    if selected and target is None:
        raise ValueError('KCD2 game folder is required to upgrade saved male clothing')
    changed, removed, replacements, reports = {}, [], {}, []
    with ExitStack() as stack:
        native = Assets(Path(target), stack) if selected else None
        for index, (name, document, component) in enumerate(selected):
            if cancelled(): raise InterruptedError('Cancelled before actor material migration')
            namespace = name.split('__', 1)[1][:-4]
            notify('Upgrade saved male clothing', index, len(selected), namespace)
            archives = sorted(p for p in (package/'Data').glob(namespace+'*.pak')
                              if re.fullmatch(re.escape(namespace)+r'(?:_\d+)?\.pak', p.name))
            if not archives: raise ValueError('Missing actor archives: '+namespace)
            # Only one actor is unpacked at a time, on the build drive.
            with tempfile.TemporaryDirectory(prefix='actor-upgrade-', dir=package.parent) as temporary:
                work = Path(temporary); appearance = work/'appearance'; appearance.mkdir()
                seen = set()
                for path in archives:
                    with zipfile.ZipFile(path) as archive:
                        for entry in archive.namelist():
                            destination = (appearance/entry).resolve()
                            if not destination.is_relative_to(appearance) or not entry.startswith('objects/') or entry in seen:
                                raise ValueError('Unsafe or duplicate actor asset: '+entry)
                            seen.add(entry)
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            destination.write_bytes(read(archive, entry))
                (appearance/'Libs/Tables/Character').mkdir(parents=True)
                report = convert_character_materials(appearance, component, native, namespace, 'male')
                if not any(r['source_shader'] == 'illum' for r in report):
                    raise ValueError('No legacy clothing found for '+namespace)
                output = work/'Data'; output.mkdir()
                shards, libs = write_actor_paks(appearance, output, namespace)
                replacements.update(libs); replacements[name] = xml(document)
                # Replacement breaks hard links to the last verified package.
                new_names = {p.name for p in shards}
                for shard in shards:
                    relative = 'Data/'+shard.name
                    changed[relative] = digest(shard)
                    shard.replace(package/relative)
                for old in archives:
                    if old.name not in new_names:
                        removed.append('Data/'+old.name); old.unlink()
                reports.append(dict(namespace=namespace, materials=len(report), archives=len(shards)))
    if replacements:
        pending = travel.with_suffix('.materials-pending')
        from build_horse_trader_test import rewrite
        rewrite(travel, pending, replacements)
        with zipfile.ZipFile(pending) as check:
            if check.testzip() is not None: raise ValueError('Invalid upgraded actor tables')
        pending.replace(travel)
        changed['Data/gluemappertravel.pak'] = digest(travel)
    return changed, removed, dict(version=1, actors=reports, runtime_verified=False)
