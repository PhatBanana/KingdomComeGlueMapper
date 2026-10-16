"""Convert authored tool slots and their physical item into one native slot."""
import xml.etree.ElementTree as ET

from campaign_entity_links import native_guid
from world_item_placements import placement_transform
from entity_visuals import world_transform


def element(node):
    result = ET.Element(node['op'], node['attributes'])
    result.extend(element(c) for c in node['children'])
    return result


class WorkItems:
    def __init__(self, records):
        self.by_id = {}
        self.by_guid = {}
        self.slots = {}
        self.aliases = {}
        for record in records:
            entity = element(record['entity']) if 'entity' in record else ET.Element('Entity',record['attributes'])
            self.by_id.setdefault(entity.get('EntityId'), []).append(entity)
            if entity.get('EntityGuid'):
                self.by_guid.setdefault(entity.get('EntityGuid').lower(), []).append(entity)
            if entity.get('EntityClass') == 'ItemSlot':
                self.slots[entity.get('EntityGuid', '').lower()] = entity
        # The source world is immutable during this build. Resolve parent
        # candidates once rather than rescanning it for every placed tool.
        self.unique_by_id = {key: values[0] for key, values in self.by_id.items() if len(values) == 1}
        for guid, slot in self.slots.items():
            for link in slot.findall("EntityLinks/Link[@Name='SlotLink']"):
                try:
                    target = self.resolve_link(link)
                except ValueError:
                    continue  # The slot's plan reports the malformed source link.
                if target.get('EntityClass') == 'PickableItem':
                    self.aliases.setdefault(target.get('EntityGuid', '').lower(), []).append(guid)

    def resolve_link(self, link):
        guid, eid = link.get('TargetGuid'), link.get('TargetId')
        matches = (self.by_guid.get(guid.lower(), []) if guid not in (None, '', '0')
                   else self.by_id.get(eid, []) if eid not in (None, '', '0') else [])
        if len(matches) != 1:
            raise ValueError('Tool slot physical item is missing or ambiguous')
        target = matches[0]
        if eid not in (None, '', '0') and eid != target.get('EntityId'):
            raise ValueError('Tool slot target GUID and ID disagree')
        return target

    def alias(self, source):
        matches = self.aliases.get(source['attributes'].get('EntityGuid', '').lower(), [])
        if len(matches) > 1:
            raise ValueError('Source item is assigned to multiple tool slots')
        return native_guid(int(matches[0],16)) if matches else None

    def prepare(self, source):
        slot = element(source['entity'])
        props = slot.find('Properties')
        if props is None:
            raise ValueError('Source tool slot has no properties')
        allowed = {'guidItemClassId','icfItemClassFilter','bSpawnOnStart','bSaved_by_game',
            'bSlotMagnetism','soclasses_SmartObjectHelpers','guidSmartObjectType','sWH_AI_EntityCategory',
            'vectorPIMatRow1','vectorPIMatRow2','vectorPIMatRow3','vectorPIMatRow4'}
        if set(props.attrib)-allowed:
            raise ValueError('Unconverted tool slot properties: '+str(sorted(set(props.attrib)-allowed)))
        if props.get('icfItemClassFilter'):
            raise ValueError('Tool item-class filter requires native schema conversion')
        if props.get('bSlotMagnetism','1') != '1':
            raise ValueError('Nonmagnetic source tool slot requires physics conversion')
        for script in props:
            if script.tag != 'Script' or set(script.attrib)-{'esHand','Misc'} or script.get('Misc') or list(script):
                raise ValueError('Tool slot has an unconverted script')
            if script.get('esHand','Right') != 'Right':
                raise ValueError('Tool slot requires an explicit native manipulation animation tag')
        placed = slot.findall("EntityLinks/Link[@Name='SlotLink']")
        if len(placed)>1:
            raise ValueError('Tool slot has multiple placed items')
        pickup = None
        if placed:
            pickup=self.resolve_link(placed[0])
            if pickup.get('EntityClass')!='PickableItem' or pickup.find('Properties') is None:
                raise ValueError('Tool slot target is not a physical item')
            pp=pickup.find('Properties')
            if pp.get('guidItemClassId','').lower()!=props.get('guidItemClassId','').lower():
                raise ValueError('Tool slot and placed item classes disagree')
            if pp.get('nAmount','1')!='1' or float(pp.get('fRespawn','0')) or pp.get('ScriptCommand'):
                raise ValueError('Tool pickup quantity, respawn or script needs conversion')
        item=props.get('guidItemClassId','').lower()
        if not item or item=='0':
            raise ValueError('Tool slot has no authored item class')
        original=pickup if pickup is not None else slot
        p,r,s=world_transform(original,self.unique_by_id)
        p,r,s=placement_transform(dict(entity=original,position=p,rotation=r,scale=s))
        return dict(item=item, position=p, rotation=r, scale=s,
            pickup_id=pickup.get('EntityId') if pickup is not None else None,
            pickup_properties=dict(pickup.find('Properties').attrib) if pickup is not None else {})

    def apply(self, entity, source, prepared, registered):
        props=element(source['entity']).find('Properties')
        vector=lambda value: ','.join(format(v,'.10g') for v in value)
        for key,value in [('Pos',prepared['position']),('Rotate',prepared['rotation']),('Scale',prepared['scale'])]:
            entity.set(key,vector(value))
        pickup=prepared['pickup_properties']
        native=ET.SubElement(entity,'Properties',guidItemClassId=registered['items'][prepared['item']],
            bSpawnOnStart=props.get('bSpawnOnStart','1'),bOnlyNPC=pickup.get('bOnlyNPC','0'),
            bSaveBorrowedItem='1',bHasItemPhysics='0',bOwnedByHome='1',
            nRestockPeriodDays='0',nDestockPeriodDays='0',ItemHealth=pickup.get('fHealth','-1'),
            sWH_AI_EntityCategory=props.get('sWH_AI_EntityCategory',''))
        family=props.get('soclasses_SmartObjectHelpers')
        if family:
            native.set('soclass_SmartObjectHelpers',registered['work_helpers'][family.lower()])
        if source.get('work_object_identity'):
            native.set('guidSmartObjectType',registered['smart_entities'][source['work_object_identity'].lower()])
        ET.SubElement(native,'Script',Misc='')
