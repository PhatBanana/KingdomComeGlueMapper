"""Preserve authored nonvisual outfit items without inventing a wearable mesh."""
import xml.etree.ElementTree as ET
import zipfile

from campaign_sources import RetailSourceReader
from campaign_dependency_adapters import SourceTables
from character_source_clothing import native_role, source_item
from garment_contracts import clothing_role
from upgrade_map import read, xml


def partition_accessories(parts, tables):
    meshes, accessories = [], []
    for part in parts:
        if part['kind'] != 'cloth' or part.get('model'):
            meshes.append(part)
            continue
        role = clothing_role(tables, part['armor_settings'], part)
        if role not in ('Ring', 'Necklace', 'Spurs') or part.get('material') or part.get('morph_target'):
            raise ValueError('Missing source geometry is not an authored nonvisual accessory')
        accessories.append(dict(part, native_role=role))
    return meshes, accessories


def register_accessories(source, target, output, namespace, accessories):
    from character_person import native_xml
    component_path = output / ('Libs/Tables/Character/CharacterComponent__'+namespace+'.xml')
    item_path = output / ('Libs/Tables/item/item__'+namespace+'.xml')
    preset_path = output / ('Libs/Tables/item/clothing_preset__'+namespace+'.xml')
    text_path = output / 'Localization/English/text_ui_items.xml'
    components, items, preset = (ET.parse(p).getroot() for p in (component_path, item_path, preset_path))
    texts = ET.parse(text_path).getroot() if text_path.exists() else ET.Element('Table')
    with zipfile.ZipFile(target / 'Data/Tables.pak') as archive:
        native_components = native_xml(read(archive, 'Libs/Tables/Character/CharacterComponent.xml'))
        native_items = native_xml(read(archive, 'Libs/Tables/item/item.xml'))
    with zipfile.ZipFile(source / 'Localization/English_xml.pak') as archive:
        source_strings = ET.fromstring(read(archive, 'text_ui_items.xml'))
    report = []
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        for accessory in accessories:
            role = accessory['native_role']
            archetype, template = native_role(native_components, native_items, role)
            name = namespace + '_accessory_' + accessory['armor_id'].replace('-', '')
            ET.SubElement(components.find('CharacterComponents/Component/DerivedComponents'), 'Clothing',
                          Name=name, ArmorType=role, ArmorArchetypeId=archetype)
            item, localized = source_item(tables, accessory['armor_id'], namespace, name, template, source_strings)
            items.find('ItemClasses').append(item)
            ET.SubElement(preset.find('clothing_presets/clothing_preset/Items'), 'Guid').text = item.get('Id')
            texts.extend(localized)
            report.append(dict(source_id=accessory['armor_id'], item_id=item.get('Id'), role=role,
                               source_has_mesh=False, equipped_by_clothing_preset=True))
    for path, root in ((component_path, components), (item_path, items), (preset_path, preset), (text_path, texts)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(xml(root))
    return report
