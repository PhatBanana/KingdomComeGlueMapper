"""Add the exported systems control and a coach route to one owned retail mod.

The control is optional test content. Its level PAK is identical for direct
and coach entry; neither route invokes an NPC repair or combat test script.
"""
import argparse
import copy
import json
from pathlib import Path, PurePosixPath
import shutil
import uuid
import xml.etree.ElementTree as ET
import zipfile

from campaign_package import level_registration
from full_system_control import LEVEL, LEVEL_ID, ACTOR, GRAPH
from region_travel_dialogue import DIALOGUE, HOST, patch_test_world, merge_localization
from region_travel_tables import KEYS, validate_required_fields
from setup_campaign import MOD_ID, RECEIPT, digest, verify_package
from travel_bridge_package import validate_bridge
from upgrade_map import read, xml


def canonical(node):
    return (node.tag, tuple(sorted(node.attrib.items())), (node.text or '').strip(),
            tuple(canonical(c) for c in node))


def merge_table(base, extra):
    """Keep existing rows; accept repeated shared records only when identical."""
    root, other = ET.fromstring(base), ET.fromstring(extra)
    if len(root) != 1 or len(other) != 1 or root.tag != 'database' or other.tag != 'database':
        raise ValueError('Expected one database table')
    rows, added = root[0], other[0]
    if rows.tag != added.tag or rows.attrib != added.attrib:
        raise ValueError('Different table schemas')
    key = KEYS[rows.tag]
    seen = {r.get(key): r for r in rows}
    if None in seen or len(seen) != len(rows): raise ValueError('Duplicate existing row')
    for row in added:
        name = row.get(key)
        if name is None: raise ValueError('Missing primary key')
        if name in seen:
            if canonical(row) != canonical(seen[name]): raise ValueError('Conflicting record: ' + name)
        else:
            rows.append(copy.deepcopy(row)); seen[name] = row
    validate_required_fields(root, rows.tag)
    return xml(root)


def merge_storm(base, extra):
    root, source = ET.fromstring(base), ET.fromstring(extra)
    if root.tag != 'storm' or source.tag != 'storm': raise ValueError('Expected Storm manifest')
    for task in source.findall('tasks/task'):
        original = root.find("tasks/task[@name='%s']" % task.get('name'))
        if original is None: raise ValueError('Unknown Storm task ' + task.get('name', ''))
        paths = {s.get('path', '').replace('\\', '/').lower() for s in original.findall('source')}
        for item in task.findall('source'):
            path = item.get('path', '').replace('\\', '/').lower()
            if path not in paths:
                # Only the imported actor's rules are needed from the isolated
                # test mod. Never import its Trosky scheduler override.
                if ACTOR not in path: raise ValueError('Unexpected additional Storm source ' + path)
                original.append(copy.deepcopy(item)); paths.add(path)
    return xml(root)


def character_rekeys(existing, source):
    """Earlier character experiments reused source item GUIDs across namespaces.

    Give conflicting cloned rows independent IDs and rewrite their references;
    never overwrite the installed Rattay test actor's outfit records.
    """
    remap = {}
    for name, blob in source.items():
        if not name.lower().startswith('libs/tables/'): continue
        path = PurePosixPath(name)
        normalized = str(path.with_name(path.stem.split('__')[0] + '__' + MOD_ID + '.xml')).lower()
        if normalized not in existing: continue
        original, extra = ET.fromstring(existing[normalized])[0], ET.fromstring(blob)[0]
        key = KEYS[original.tag]
        rows = {r.get(key): r for r in original}
        for row in extra:
            identity = row.get(key)
            if identity in rows and canonical(row) != canonical(rows[identity]):
                uuid.UUID(identity)  # Non-GUID name conflicts are not safe to rename implicitly.
                remap[identity] = str(uuid.uuid5(uuid.NAMESPACE_URL, LEVEL + '/character/' + identity))
    return remap


def rewrite_pak(path, changes):
    """Replace selected entries without repacking the engine's other entries.

    Keep untouched local records at their original offsets, including native
    compression, extra fields and alignment. The replaced local record becomes
    unreferenced; the new central directory lists its replacement exactly once.
    Build from a fresh export to avoid accumulating obsolete records.
    """
    pending = {n.lower(): (n, b) for n, b in changes.items()}
    if len(pending) != len(changes): raise ValueError('Duplicate replacement path')
    temporary = path.with_suffix('.building')
    shutil.copyfile(path, temporary)
    try:
        with zipfile.ZipFile(temporary, 'a') as archive:
            names = [i.filename.lower() for i in archive.infolist()]
            if len(names) != len(set(names)): raise ValueError('Duplicate archive path')
            # zipfile's append writer preserves existing local records. Remove
            # superseded entries from its directory before writing replacements.
            archive.filelist = [i for i in archive.filelist if i.filename.lower() not in pending]
            archive.NameToInfo = {i.filename: i for i in archive.filelist}
            for name, blob in pending.values():
                archive.writestr(name, blob, compress_type=zipfile.ZIP_STORED)
        temporary.replace(path)
    finally:
        if temporary.exists(): temporary.unlink()


def validate_export(level):
    with zipfile.ZipFile(level / 'level.pak') as z:
        wh = ET.fromstring(read(z, 'whdata_0'))
        concept = wh.find('ConceptManager')
        if [m.text for m in concept.findall('ConceptModules/Module')] != [LEVEL]:
            raise ValueError('Export must activate exactly the control Level module')
        if [p.text.lower() for p in concept.findall('ConceptPaths/Path')] != [GRAPH.lower()]:
            raise ValueError('Export must retain the native Barbora campaign project')
        player = next(s for s in wh.findall('SoulList/Souls/Soul') if s.findtext('Player') == '1')
        if player.findtext('SharedSoulGuid') != '4c2dcffb-dea1-6263-72d7-b39f4db2d8b5' or player.find('StaticData') is not None:
            raise ValueError('Export still uses a standalone editor player')
        objects = ET.fromstring(read(z, 'objects_mission0.xml'))
        classes = {e.get('EntityClass') for e in objects}
        if not {'UIApseLinkNode', 'UIShopLinkNode', 'InventoryDummyPlayer', 'InventoryDummyHorse', 'InventoryDummyDog'} <= classes:
            raise ValueError('Control inventory showroom is incomplete')
        for name in ('ControlArrival', 'ControlPlayerSpawn', LEVEL, ACTOR):
            if len([e for e in objects if e.get('Name') == name]) != 1:
                raise ValueError('Missing or duplicate control entity ' + name)
        return {f'Mods/{MOD_ID}/Data/Levels/{LEVEL}/{n}': read(z, n)
                for n in z.namelist() if n.lower().startswith('tables/')}


def prepare_retail_level(editor_level, destination):
    """Preserve the official export, adding its retail Level activation list.

    Sandbox exports the project path but omits ConceptModules for this custom
    map. Native retail maps explicitly list their Level module in whdata_0.
    This is a package-time registration, used identically by both entry paths.
    """
    destination.mkdir(parents=True)
    for name in ('level.pak', 'terrain.pak', 'recast.pak'):
        shutil.copyfile(editor_level / name, destination / name)
    with zipfile.ZipFile(destination / 'level.pak') as pak:
        wh = ET.fromstring(read(pak, 'whdata_0'))
        manager = wh.find('ConceptManager')
        if manager is None: raise ValueError('Missing exported concept manager')
        modules = manager.find('ConceptModules')
        if modules is None: modules = ET.SubElement(manager, 'ConceptModules')
        if len(modules): raise ValueError('Unexpected preexisting level activation')
        ET.SubElement(modules, 'Module').text = LEVEL
        (destination / 'levelinfo.xml').write_bytes(read(pak, 'levelinfo.xml'))
    rewrite_pak(destination / 'level.pak', {'whdata_0': xml(wh)})
    return validate_export(destination)


def build(base, editor_level, resources, character, target, output):
    base, editor_level, resources, character, target, output = map(Path, (base, editor_level, resources, character, target, output))
    if output.exists(): raise FileExistsError(output)
    receipt = verify_package(base)
    supplemental, bridge_changes = {}, {}
    bridge_path = Path('Data/gluemappertravel.pak')
    root_path = Path('Data') / (MOD_ID + '.pak')
    with zipfile.ZipFile(base / bridge_path) as old, zipfile.ZipFile(character / 'Data/gluemapper_fritz_trosky_test.pak') as source:
        names = {n.lower(): n for n in old.namelist()}
        def existing(name): return read(old, names[name.lower()])
        source_tables = {n: read(source, n) for n in source.namelist() if n.lower().startswith('libs/tables/')}
        rekeys = character_rekeys({n.lower(): existing(n) for n in names if n.startswith('libs/tables/')}, source_tables)
        patched, strings = patch_test_world(existing(DIALOGUE), existing(HOST))
        bridge_changes.update(patched)
        route_path = f'Libs/Tables/LevelSwitch__{MOD_ID}.xml'
        routes = ET.fromstring(existing(route_path))
        ET.SubElement(routes[0], 'LevelSwitchData', Name='gluemappertravel_to_test_world',
                      TargetLevelId=str(LEVEL_ID), TargetLocationEntity='ControlArrival')
        bridge_changes[route_path] = xml(routes)
        for name in source.namelist():
            if name.lower().startswith(('mods/', 'scripts/')): continue
            blob = read(source, name)
            if name.lower().endswith('.xml'):
                for before, after in rekeys.items(): blob = blob.replace(before.encode(), after.encode())
            if name.lower() == 'libs/storm/storm.xml':
                bridge_changes[name] = merge_storm(existing(name), blob)
            elif name.lower().startswith('libs/tables/'):
                path = PurePosixPath(name)
                normalized = str(path.with_name(path.stem.split('__')[0] + '__' + MOD_ID + '.xml'))
                if normalized.lower() in names:
                    bridge_changes[names[normalized.lower()]] = merge_table(existing(normalized), blob)
                else: bridge_changes[normalized] = blob
            elif name.lower() in names:
                if existing(name) != blob: raise ValueError('Conflicting existing asset: ' + name)
            else: supplemental[name] = blob
    with zipfile.ZipFile(base / root_path) as old:
        level_path = f'Libs/Tables/level__{MOD_ID}.xml'
        root_changes = {level_path: merge_table(read(old, level_path), level_registration(target, LEVEL, LEVEL_ID))}
    for path in resources.rglob('*'):
        if path.is_file(): supplemental[path.relative_to(resources).as_posix()] = path.read_bytes()
    localization = 'Localization/English_xml.pak'
    with zipfile.ZipFile(base / localization) as old, zipfile.ZipFile(character / localization) as source:
        loc_changes = {'text_ui_dialog.xml': merge_localization(read(old, 'text_ui_dialog.xml'), strings)}
        rows = ET.Element('Table')
        for row in ET.fromstring(read(source, 'text_ui_soul.xml')):
            if ACTOR in row.findtext('Cell', ''): rows.append(copy.deepcopy(row))
        if len(rows) != 1: raise ValueError('Actual Fritz localization missing')
        loc_changes['text_ui_soul.xml'] = merge_localization(read(old, 'text_ui_soul.xml'), xml(rows))
    # Build a full single-mod package, keeping all prior world resources intact.
    shutil.copytree(base, output)
    rewrite_pak(output / bridge_path, bridge_changes)
    rewrite_pak(output / root_path, root_changes)
    rewrite_pak(output / localization, loc_changes)
    destination = output / 'Data/Levels' / LEVEL
    supplemental.update(prepare_retail_level(editor_level, destination))
    with zipfile.ZipFile(output / 'Data/gluemapper_control.pak', 'w', zipfile.ZIP_STORED) as pak:
        for name, blob in sorted(supplemental.items()): pak.writestr(name, blob)
    receipt['systems_control'] = dict(level=LEVEL, level_id=LEVEL_ID, actor=ACTOR,
        entry_methods=['Trosky coach: Travel to Test world', 'console: map ' + LEVEL],
        source_export_sha256=digest(editor_level / 'level.pak'),
        packaged_level_sha256=digest(destination / 'level.pak'),
        export_adjustments=['Register control Level in ConceptModules'], runtime_verified=False)
    receipt['systems_control']['character_record_rekeys'] = rekeys
    receipt['files'] = {p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob('*')) if p.is_file() and p.name != RECEIPT}
    (output / RECEIPT).write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    validate_bridge(output)
    verify_package(output)
    return receipt['systems_control']


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'editor-level', 'resources', 'character', 'target', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(build(a.base, a.editor_level, a.resources, a.character, a.target, a.output), indent=2))
