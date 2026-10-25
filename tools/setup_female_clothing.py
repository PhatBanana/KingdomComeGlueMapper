"""Retain the female body beneath converted pickup dresses in saved packages.

The native female body is a single torso element, including its exposed arms.
Source dress geometry is not a complete replacement for that element. This
migration only updates components owned by the source pickup converter; it
does not change native outfits, geometry, hiding groups or male layer policy.
"""
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from upgrade_map import read, xml


VERSION = 1
MODE = 'preserve_female_wearable_body_layer'


def repair(blob):
    """Return an updated table and the names of corrected pickup components."""
    root = ET.fromstring(blob)
    corrected = []
    for component in root.findall('CharacterComponents/Component'):
        name = component.get('Name', '')
        if (component.get('Gender') != 'Female' or component.get('Race') != 'Human'
                or not name.startswith('worlditems_cloth_') or not name.endswith('_root')
                or not component.get('FilePath', '').startswith('gluetravel/worlditems/')):
            continue
        for clothing in component.findall('DerivedComponents/Clothing'):
            if clothing.get('Name') != name.removesuffix('_root'):
                continue
            changed = False
            for element in clothing.findall('Elements/SkinElement'):
                if element.get('EquipmentPart') == 'torso' and element.get('KeepBodyLayer') == 'false':
                    element.set('KeepBodyLayer', 'true')
                    changed = True
            if changed:
                corrected.append(clothing.get('Name'))
    return (xml(root) if corrected else blob), corrected


def upgrade(package, receipt):
    """Migrate receipt-owned PAK tables through the setup's atomic writer.

    Scan on every run so a valid old marker cannot conceal newly restored
    converter output. Clean tables and unrelated archive members stay byte
    identical. Rewrites use replacement files, preserving linked checkpoints.
    """
    from setup_campaign import digest
    from setup_package_upgrade import rewrite
    package = Path(package)
    updates, corrected, scanned = {}, [], 0
    for relative, expected in sorted(receipt['files'].items()):
        path = Path(relative)
        if path.suffix.lower() != '.pak' or path.parts[0].lower() != 'data' or len(path.parts) != 2:
            continue
        source = package / path
        if not source.resolve().is_relative_to(package.resolve()):
            raise ValueError('Female clothing package path escapes the package')
        replacements = {}
        with zipfile.ZipFile(source) as archive:
            for entry in archive.namelist():
                key = entry.replace('\\', '/').lower()
                if not (key.startswith('libs/tables/character/charactercomponent__') and key.endswith('.xml')):
                    continue
                original = read(archive, entry)
                updated, names = repair(original)
                scanned += 1
                if updated != original:
                    replacements[entry] = updated
                    corrected.extend(dict(component=name, archive=relative, table=entry) for name in names)
        if replacements:
            if digest(source) != expected:
                raise ValueError('Female clothing migration refuses a changed package: ' + relative)
            rewrite(package, relative, replacements)
            updates[relative] = digest(source)
    return updates, dict(version=VERSION, mode=MODE, tables_scanned=scanned,
                         corrected_components=corrected, runtime_verified=False)
