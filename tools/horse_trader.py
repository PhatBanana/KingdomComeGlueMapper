"""Source stable roster and native horse companion records for development tests."""
import copy
import re
import xml.etree.ElementTree as ET
import zipfile

from campaign_dependency_adapters import SourceTables
from campaign_sources import RetailSourceReader
from character_person import unique, native_xml
from character_person_ai import stat_operations
from upgrade_map import read, xml


def roster(source, stable='neu', merchant='neu_zdena'):
    with zipfile.ZipFile(source/'Data/Scripts.pak') as archive:
        script = read(archive, 'Scripts/Script/Horsetraders.lua').decode('utf-8')
    # The roster is data, not executable conversion code. Read one balanced Lua
    # table and reject unexpected data rather than executing legacy scripts.
    match = re.search(r"\['"+re.escape(stable)+r"'\]\s*=\s*\{", script)
    if not match: raise ValueError('Source stable not found: '+stable)
    start = match.end(); depth = 1; end = start
    while depth and end < len(script):
        depth += (script[end] == '{') - (script[end] == '}'); end += 1
    block = script[start:end-1]
    if depth or not re.search(r"merchants\s*=\s*\{\s*'"+re.escape(merchant)+r"'", block):
        raise ValueError('Unexpected stable merchant contract')
    names = re.findall(r"name\s*=\s*'([^']+)'", block)
    if not names or len(names) != len(set(names)): raise ValueError('Invalid stable roster')
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as archive:
        world = ET.fromstring(read(archive, 'whdata_0'))
        actors = []
        for path in archive.namelist():
            if path == 'objects_mission0.xml' or path.startswith('layers/') and path.endswith('.xml'):
                blob = read(archive, path)
                if any(n.encode() in blob for n in names):
                    actors.extend(e for e in ET.fromstring(blob).iter('Entity') if e.get('Name') in names)
    with zipfile.ZipFile(source/'Localization/English_xml.pak') as archive:
        labels = {r.findtext('Cell'): r.findall('Cell')[-1].text
                  for r in ET.fromstring(read(archive, 'text_ui_soul.xml')).findall('Row')}
    result = []
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        for name in names:
            soul = tables.row('rpg/soul', 'soul_name', name)
            actor = unique((a for a in actors if a.get('Name') == name), 'stable horse')
            instance = unique((s for s in world.findall('SoulList/Souls/Soul')
                               if s.findtext('Name') == name), 'stable horse soul')
            if actor.get('EntityClass') != 'Horse' or instance.findtext('SharedSoulGuid') != soul['soul_id']:
                raise ValueError('Source stable horse identity mismatch')
            key = instance.findtext('StaticData/NameStringId')
            if key not in labels: raise ValueError('Missing source horse display name: '+name)
            result.append(dict(name=name, soul=soul, actor=copy.deepcopy(actor),
                               instance=copy.deepcopy(instance), display_name=labels[key], name_key=key))
    return result


def horse_resources(resources, target, horses, faction):
    """Preserve source identities and stats with a compatible native sale-horse rig.

    Visual fallback is explicit in the build receipt: legacy horse body/coat
    conversion is separate from the human skin upgrader and is not claimed here.
    """
    result = dict(resources)
    with zipfile.ZipFile(target/'Data/Tables.pak') as archive:
        template = unique((s for s in native_xml(read(archive, 'Libs/Tables/rpg/soul__tsem.xml')).iter('soul')
                           if s.get('soul_name') == 'tsem_horseForSale_1'), 'native sale horse')
        shop = copy.deepcopy(unique((s for s in native_xml(read(archive, 'Libs/Tables/shop/shop.xml')).iter('ShopData')
                                     if s.get('shop_name') == 'shop_tsem_horseTrader'), 'native horse shop'))
    root = ET.Element('database', name='barbora'); souls = ET.SubElement(root, 'souls', version='2')
    storm = ET.fromstring(result['Libs/Storm/storm.xml'])
    groups = {task: ET.Element('storm') for task in ('appearance', 'abilities', 'names')}
    rules = {task: ET.SubElement(root, 'rules') for task, root in groups.items()}
    with zipfile.ZipFile(target/'Data/IPL_GameData.pak') as archive:
        native_looks = native_xml(read(archive, 'Libs/Storm/appearance/common/appearance_horse.xml'))
        looks = unique((r for r in native_looks.findall('rules/rule')
                        if r.find("selectors/hasName[@name='tsem_horseForSale_1']") is not None), 'native horse look')
    for horse in horses:
        row = copy.deepcopy(template)
        row.attrib.update(soul_id=horse['soul']['soul_id'], soul_name=horse['name'], factionName=faction)
        row.attrib.pop('skald_character_name', None); souls.append(row)
        for task in groups:
            rule = ET.SubElement(rules[task], 'rule', name='gm_'+horse['name']+'_'+task)
            ET.SubElement(ET.SubElement(rule, 'selectors'), 'hasName', name=horse['name'])
            ops = ET.SubElement(rule, 'operations')
            if task == 'appearance': ops.extend(copy.deepcopy(list(looks.find('operations'))))
            elif task == 'names': ET.SubElement(ops, 'setUiName', name=horse['name_key'])
            else:
                for tag, attrs in stat_operations(horse['soul']): ET.SubElement(ops, tag, attrs)
    for task, document in groups.items():
        path = task+'/gm_neuhof_horses.xml'
        ET.SubElement(storm.find(f"tasks/task[@name='{task}']"), 'source', path=path)
        result['Libs/Storm/'+path] = xml(document)
    result['Libs/Storm/storm.xml'] = xml(storm)
    result['Libs/Tables/rpg/soul__gm_neuhof_horses.xml'] = xml(root)
    shop.attrib.update(shop_id='20130', shop_name='gm_neuhof_horse_shop')
    root = ET.Element('database', name='barbora'); ET.SubElement(root, 'Shops', version='5').append(shop)
    result['Libs/Tables/shop/shop__gm_neuhof_horses.xml'] = xml(root)
    return result
