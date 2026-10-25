"""Build an isolated candidate for native layer repairs. Never installs a mod."""
import json
from pathlib import Path
import posixpath
import xml.etree.ElementTree as ET
import zipfile

from character_layer_contract import region_layers
from character_person import native_xml
from clothing_assembly import assemble_region_skins
from character_skin_upgrade import CompiledSkin
from upgrade_map import read, xml
from .assets import Assets, key


def repair_table(data, native, assets):
    parents = {child: parent for parent in native.iter() for child in parent}
    roles = {n.get('Name'): n for n in native.iter('Clothing')
             if n.get('Name') == n.get('ArmorType')}
    root = ET.fromstring(data)
    files, corrections = {}, []
    for component in root.findall('CharacterComponents/Component'):
        if not (component.get('Name','').startswith('worlditems_cloth_')
                and component.get('Race') == 'Human'
                and component.get('FilePath','').startswith('gluetravel/worlditems/')):
            continue
        folder = 'objects/characters/' + component.get('FilePath').rstrip('/') + '/'
        for clothing in component.findall('DerivedComponents/Clothing'):
            role = clothing.get('ArmorType')
            if role not in roles:
                raise ValueError('Missing native role: '+str(role))
            contract = region_layers(roles[role], parents)
            elements = clothing.find('Elements')
            if elements is None:
                continue
            skins = list(elements.findall('SkinElement'))
            unsupported = [e for e in skins if e.get('EquipmentPart') not in contract]
            changed = []
            if unsupported:
                # Old upper-body conversions split every mesh into arms/waist,
                # even where the native role represents the garment in torso.
                torso = [e for e in skins if e.get('EquipmentPart') == 'torso']
                if (component.get('Gender') != 'Male' or len(torso) != 1 or 'torso' not in contract
                        or any(e.get('EquipmentPart') not in ('arms','waist') for e in unsupported)):
                    raise ValueError('Unresolved native region repair: '+clothing.get('Name',''))
                sources = torso + unsupported
                if len({e.get('Material') for e in sources}) != 1:
                    raise ValueError('Region repair requires matching material tables')
                blobs = [assets.read(key(posixpath.normpath(folder+e.get('Model','')))) for e in sources]
                before = sum(len(CompiledSkin(b).faces) for b in blobs)
                output = folder+'native_regions.skin'
                merged = assemble_region_skins(blobs, [0]*len(blobs), folder+torso[0].get('Material','').removesuffix('.mtl'))
                after = len(CompiledSkin(merged).faces)
                if after != before:
                    raise ValueError('Region repair lost source triangles')
                files[output] = merged
                torso[0].set('Model','native_regions.skin')
                for e in unsupported:
                    elements.remove(e)
                changed.append(dict(kind='native_region_projection', before_triangles=before, after_triangles=after,
                                    removed_regions=[e.get('EquipmentPart') for e in unsupported]))
            for element in elements.findall('SkinElement'):
                region = element.get('EquipmentPart')
                expected = contract[region]
                # Repair absent inheritance; intentionally authored explicit
                # differences remain review findings, rather than being guessed.
                if element.get('BodyLayerId') is None and expected is not None:
                    element.set('BodyLayerId', expected)
                    changed.append(dict(kind='inherited_layer', region=region, layer=expected))
            if changed:
                corrections.append(dict(component=clothing.get('Name'), role=role, changes=changed))
    return (xml(root) if corrections else data), files, corrections


def build_candidate(package, target, destination):
    destination = Path(destination).resolve()
    package = Path(package).resolve()
    target = Path(target).resolve()
    if destination.is_relative_to(package) or destination.is_relative_to(target):
        raise ValueError('Developer repair must be outside the game installation')
    if destination.exists():
        raise FileExistsError('Choose a new developer candidate directory')
    assets = Assets(package)
    with zipfile.ZipFile(target/'Data/Tables.pak') as archive:
        native = native_xml(read(archive, 'Libs/Tables/Character/CharacterComponent.xml'))
    corrections, outputs, unresolved = [], {}, []
    for name in sorted(assets.index):
        if '/charactercomponent__' not in name or not name.endswith('.xml'):
            continue
        data = assets.read(name)
        try:
            updated, files, rows = repair_table(data, native, assets)
        except ValueError as exc:
            unresolved.append(dict(table=name,error=str(exc)))
            continue
        if rows:
            outputs[name] = updated
            outputs.update(files)
            corrections.extend(rows)
    (destination/'Data').mkdir(parents=True)
    with zipfile.ZipFile(destination/'Data/developer_layer_candidate.pak','w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in sorted(outputs.items()):
            archive.writestr(name,data)
    report = dict(base_package=str(package),base_signature=assets.signature(),corrections=corrections,unresolved=unresolved,
                  installed=False,runtime_verified=False,
                  limitation='Layer/region repair only; skin coverage and native outfit arbitration are not repaired by this candidate.')
    (destination/'repair.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
