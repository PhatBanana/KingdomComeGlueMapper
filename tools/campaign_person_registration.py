"""Connect campaign soul requests to the existing source-person upgrader.

Shared Storm/faction documents are accumulated once and published after all
dependency requests. Individual souls keep independently owned output paths.
"""
from pathlib import Path
import xml.etree.ElementTree as ET

from campaign_quest_graph import xml


class PersonRegistration:
    def __init__(self, source, target, tables, entities, output, namespace,
                 appearance_builder=None, resource_builder=None, item_name=None):
        self.source, self.target, self.tables = source, target, tables
        self.entities = list(entities)
        from character_person_ai import index_person_links
        self.person_link_index = index_person_links(self.entities)
        self.output, self.namespace = Path(output), namespace
        self.resources = {}
        self.appearance_builder = appearance_builder
        self.resource_builder = resource_builder
        self.item_name = item_name

    def convert(self, identity, plan, registered):
        from character_person import actor_resources
        from character_person_ai import capture_person_ai, FACTION_PATH
        from character_person_appearance import build_appearance
        def element(node):
            result = ET.Element(node['op'], node['attributes'])
            result.text = node.get('text')
            result.extend(element(c) for c in node['children'])
            return result
        # Shared soul output cannot safely select one of several distinct
        # instance overrides. Keep that explicit until per-instance selectors
        # are available instead of silently giving all instances one outfit.
        instances = plan.source['instances']
        if len(instances) != 1:
            raise ValueError('Person registration requires one source instance per soul')
        instance = element(instances[0])
        ui_name = instance.find('StaticData/NameStringId')
        if ui_name is not None and ui_name.text:
            ui_name.text = registered['person_names'][ui_name.text.lower()]
        source_guid = instance.findtext('EntityGuid')
        matches = [e for e in self.entities if e.get('EntityGuid') and
                   str(int(e.get('EntityGuid'), 16)) == source_guid and
                   e.get('EntityClass') in ('NPC', 'NPC_Female')]
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous source actor for soul: ' + identity)
        actor = matches[0]
        row = plan.source['row']
        if actor.get('Name') != row['soul_name']:
            raise ValueError('Source actor and soul names differ')
        person = dict(name=row['soul_name'], soul=row, actor=actor, instance=instance,
            ai=capture_person_ai(self.tables, row, actor, instance, self.entities,
                                 link_index=self.person_link_index),
            provenance=dict(tables=plan.source['provenance']))
        namespace = self.namespace + '_person_' + identity.replace('-', '')
        destination = self.output / namespace
        # The appearance builder owns creation and rejects existing output.
        # Creating destination here prevented every real actor build, while
        # the injected test builders previously concealed the integration bug.
        destination.parent.mkdir(parents=True, exist_ok=True)
        character = (self.appearance_builder or build_appearance)(
            self.source, self.target, person, namespace, destination)
        files = {p.relative_to(destination).as_posix(): p
                 for p in destination.rglob('*') if p.is_file() and
                 p.relative_to(destination).parts[0] in ('Libs', 'objects', 'Localization')}
        for path in list(files):
            if path.startswith('Localization/'):
                # Accessory builders use the conventional source filename.
                # Give each imported person's rows their own resource path.
                language = Path(path).parts[1]
                files['localization/'+language+'/text_'+namespace+'_'+Path(path).name] = files.pop(path)
        # The appearance upgrader supplies the source outfit. Nest the authored
        # carried inventory alongside it, without a second inventory reset.
        from character_instance import effective_soul
        inventory_ids = {effective_soul(row, instance).get('inventory_id')}
        inventory_ids -= {None, '', '00000000-0000-0000-0000-000000000000'}
        preset_path = 'Libs/Tables/item/InventoryPreset__' + namespace + '_combined.xml'
        root = ET.Element('database', name='barbora')
        preset = ET.SubElement(ET.SubElement(root, 'InventoryPresets', version='2'),
                               'InventoryPreset', Name=namespace+'_combined', Mode='All')
        ET.SubElement(preset, 'InventoryPresetRef', Name=character['inventory'])
        for inventory in sorted(inventory_ids):
            ET.SubElement(preset, 'InventoryPresetRef', Name=registered['inventories'][inventory.lower()])
        # Weapon presets are separate from outfit geometry. Do not register a
        # naked-handed actor while dropping an authored equipped weapon.
        weapons = [i for i in plan.source['loadouts'][-1]['items'] if i['kind'] == 'weapon']
        from character_weapon_inventory import append_weapons
        files.update(append_weapons(preset, weapons, registered['items'], self.item_name, namespace))
        files[preset_path] = xml(root)
        character = dict(character, inventory=namespace+'_combined')
        updated = (self.resource_builder or actor_resources)(self.target, person, character, namespace,
            role_name=namespace+'_role', native_soul_table='Libs/Tables/rpg/soul__ttac.xml',
            native_soul_name='ttac_procek', native_role_name='PREVOZNIK_TROSECKO', resources=self.resources)
        shared = {'Libs/Storm/storm.xml', FACTION_PATH}
        additions = {p:b for p,b in updated.items() if p not in self.resources and p not in shared}
        if files.keys() & additions.keys():
            raise ValueError('Person appearance and runtime resource paths collide')
        files.update(additions)
        self.resources = updated
        soul_rows = [s for path, blob in additions.items()
                     if path.lower().startswith('libs/tables/rpg/soul__')
                     for s in ET.fromstring(blob).iter('soul') if s.get('soul_id') == identity]
        native_brain = soul_rows[0].get('brain_id') if len(soul_rows) == 1 else None
        return identity, files, dict(source_soul=identity, person=person['name'],
            appearance=character, native_brain=native_brain,
            native_actor_resources=True, runtime_validated=False)

    def finalize(self):
        from character_person_ai import FACTION_PATH
        return {p:b for p,b in self.resources.items() if p in ('Libs/Storm/storm.xml', FACTION_PATH)}
