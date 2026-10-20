"""Repair converted door collection references without changing world geometry."""
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from campaign_entity_links import guid_value
from seating_animations import ANIMATIONS, HELPERS, collection_hash, converted_door
from upgrade_map import read, xml


def refresh(files):
    mission = E.fromstring(files['objects_mission0.xml'])
    doors = [e for e in mission.iter('Entity') if converted_door(e)]
    if not doors:
        return dict(files), dict(doors=0, repaired=0, runtime_verified=False)
    collections = E.fromstring(files[HELPERS])
    table = E.fromstring(files[ANIMATIONS])
    rows = table.find('SmartObjectAnimationss')
    if rows is None:
        raise ValueError('Missing smart-object animation table')
    repaired, identities, families = [], set(), set()
    for door in doors:
        identity = str(guid_value(door.get('EntityGuid')))
        if identity in identities:
            raise ValueError('Duplicate converted door identity: ' + identity)
        identities.add(identity)
        props = door.find('Properties')
        family = props.get('soclass_SmartObjectHelpers') if props is not None else None
        candidates = [c for c in collections if c.get('HelperSetName') == family]
        if not family or len(candidates) != 1:
            raise ValueError('Missing or ambiguous door animation family: ' + str(family))
        expected = collection_hash(candidates[0])
        families.add(family)
        matches = [r for r in rows if r.get('EntityGuid') == identity]
        if len(matches) > 1:
            raise ValueError('Duplicate door animation registration: ' + identity)
        row = matches[0] if matches else None
        if row is not None and row.get('Hash') == expected:
            # Valid native caches and their profile-specific checks remain intact.
            continue
        if row is not None and row.get('Hash', '0') != '0':
            raise ValueError('Door references a different animation collection: ' + identity)
        if row is not None and row.find('Animations') is not None:
            raise ValueError('Unresolved door hash has baked animation data: ' + identity)
        if row is None:
            row = E.SubElement(rows, 'SmartObjectAnimations', EntityGuid=identity)
        transform = row.find('SmartObjectTransform')
        expected_transform = dict(Position=door.get('Pos'), Rotation=door.get('Rotate', '1,0,0,0'))
        if transform is not None and transform.attrib != expected_transform:
            raise ValueError('Door animation transform differs from placement: ' + identity)
        if transform is None:
            E.SubElement(row, 'SmartObjectTransform', **expected_transform)
        row.set('Hash', expected)
        row.set('AllowRuntimeAnimValidationFallback', 'true')
        repaired.append(dict(name=door.get('Name'), guid=identity, family=family, hash=expected))
    result = dict(files)
    if repaired:
        result[ANIMATIONS] = xml(table)
    return result, dict(doors=len(doors), repaired=len(repaired), records=repaired,
                       families=sorted(families), runtime_verified=False)


def plan(package, level='kcd1_travel'):
    """Return replacements for both engine lookup paths before writing anything."""
    package = Path(package)
    level_path = 'Data/Levels/' + level + '/level.pak'
    travel_path = 'Data/gluemappertravel.pak'
    with zipfile.ZipFile(package/level_path) as z:
        mission = read(z, 'objects_mission0.xml')
        if not any(converted_door(e) for e in E.fromstring(mission).iter('Entity')):
            return {}, dict(doors=0, repaired=0, runtime_verified=False)
        files = {'objects_mission0.xml': mission,
                 **{n: read(z, n) for n in (HELPERS, ANIMATIONS)}}
    mod_id = E.parse(package/'mod.manifest').findtext('info/modid')
    if not mod_id or '/' in mod_id or '\\' in mod_id:
        raise ValueError('Invalid mod identity for animation table registration')
    fixed, report = refresh(files)
    alias = 'Mods/' + mod_id + '/Data/Levels/' + level + '/' + ANIMATIONS
    with zipfile.ZipFile(package/travel_path) as z:
        # A stale packaged table can shadow a repaired level-local table.
        aliases = [n for n in z.namelist() if n.replace('\\', '/').lower() == alias.lower()]
        if len(aliases) > 1:
            raise ValueError('Duplicate door animation table mount')
        mounted = read(z, aliases[0]) if aliases else None
    changes = {}
    if fixed[ANIMATIONS] != files[ANIMATIONS]:
        changes[level_path] = {ANIMATIONS: fixed[ANIMATIONS]}
    if mounted != fixed[ANIMATIONS]:
        changes[travel_path] = {aliases[0] if aliases else alias: fixed[ANIMATIONS]}
    report['mounted_table_repaired'] = mounted != fixed[ANIMATIONS]
    return changes, report


def upgrade(package):
    """For private setup/resume packages; callers own the receipt transaction."""
    from setup_package_upgrade import rewrite
    from upgrade_map import digest
    changes, report = plan(package)
    for relative, replacements in changes.items():
        rewrite(Path(package), relative, replacements)
    return {n: digest(Path(package)/n) for n in changes}, report
