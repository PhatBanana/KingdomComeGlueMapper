"""Register missing source items; fail the build rather than dropping pickups."""
import copy
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from campaign_dependency_adapters import ItemAdapter
from character_person import native_xml
from upgrade_map import read, xml
from garment_contracts import clothing_role
from character_source_clothing import native_role


def native_items(target, resources=()):
    result = {}
    with zipfile.ZipFile(Path(target)/'Data/Tables.pak') as archive:
        for name in archive.namelist():
            if re.fullmatch(r'libs/tables/item/item(?:__[^/]+)?\.xml', name, re.I):
                for row in native_xml(read(archive,name)).findall('ItemClasses/*'):
                    key=row.get('Id').lower()
                    if key in result: raise ValueError('Ambiguous native item '+key)
                    result[key]=copy.deepcopy(row)
    for blob in resources:
        for row in ET.fromstring(blob).findall('ItemClasses/*'):
            result[row.get('Id').lower()]=copy.deepcopy(row)
    return result


def usable_native_item(row):
    """A retained GUID with a development placeholder is not a usable asset."""
    model = row.get('Model', '').replace('\\', '/').lower()
    return 'preproduction/traffic_cone/' not in model


def native_item_registry(items):
    result = {key: key for key, row in items.items() if usable_native_item(row)}
    for key, row in items.items():
        match = re.fullmatch(r'(?:worlditems|containeritems)_item_([0-9a-f_]{36})',
                             row.get('Name', '').lower())
        if not match or not usable_native_item(row):
            continue
        source = match[1].replace('_', '-')
        if source in items and not usable_native_item(items[source]):
            if source in result and result[source] != key:
                raise ValueError('Ambiguous imported placeholder replacement: '+source)
            result[source] = key
    return result


class WorldItemAdapter(ItemAdapter):
    """Native typed item rows retain source IDs, assets, text and source stats.

    Clothing and document assets are dependencies, not generic loot substitutes.
    Preserve unported secondary gameplay data in the conversion evidence.
    """
    CATEGORIES = {**ItemAdapter.CATEGORIES, 'food':'Food','melee_weapon':'MeleeWeapon',
                  'missile_weapon':'MissileWeapon','ammo':'Ammo','document':'Document','potion':'Food',
                  'armor':'Armor','helmet':'Helmet','die':'Die'}
    FIELDS = {**ItemAdapter.FIELDS,
        'consumable_item':{}, 'potion':{}, 'die':{},
        'armor':dict(max_status='MaxStatus',noise='Noise',str_req='StrReq',stab_def='DefenseStab',slash_def='DefenseSlash',smash_def='DefenseSmash'),
        'equippable_item':dict(charisma='Charisma',social_class_id='SocialClassId',wealth_level='WealthLevel',
                               visibility='Visibility',conspicuousness='Conspicuousness'),
        'weapon':dict(weapon_class_id='Class',weapon_sub_class_id='SubClass',defense='Defense',
                      max_status='MaxStatus',str_req='StrReq',agi_req='AgiReq',is_breakable='IsBreakable'),
        'melee_weapon':dict(attack='Attack',stab_att_mod='AttackModStab',slash_att_mod='AttackModSlash',smash_att_mod='AttackModSmash'),
        'missile_weapon':dict(power='Power'),
        'ammo':dict(ammo_class_id='Type',stab_att='AttackStab',slash_att='AttackSlash',smash_att='AttackSmash',power_mod='PowerMod'),
        'document':dict(class_id='Type',length_in_game_hours='LengthInGameHours'),
        'food':dict(health_benefit='HealthBenefit',refresh_benefit='RefreshBenefit',nutrition_benefit='NutritionBenefit',
                    short_term_nutrition_benefit_ratio='ShortTermNutritionBenefitRatio',alcohol_content='AlcoholContent',
                    decay_time_hours='DecayTime',food_type_id='Type',food_subtype_id='SubType')}

    def __init__(self,tables,namespace,native,weapon_classes,native_components=None):
        super().__init__(tables,namespace);self.native=native;self.weapon_classes=weapon_classes
        self.native_components=native_components

    def plan(self,identity):
        plan=super().plan(identity)
        rows=plan.source['rows'];category=plan.source['category']
        if category in ('armor','helmet'):
            plan.dependencies.append(('clothing',identity))
            part=self.tables.row('item/clothing','clothing_id',rows['armor']['clothing_id'])
            role=clothing_role(self.tables, rows['armor'], part)
            if self.native_components is not None:
                item_root=ET.Element('Items');item_root.extend(self.native.values())
                _,template=native_role(self.native_components,item_root,role)
            else:
                template=next((r for r in self.native.values() if r.tag=='Armor' and r.get('Clothing','').startswith(role)),None)
                if template is None: raise ValueError('Missing native item template for clothing role: '+role)
            plan.source['armor_icon']=template.get('IconId')
            plan.source['armor_native_tag']=template.tag
            plan.source['armor_native_fields']={k:v for k,v in template.attrib.items() if k in ('VisorTypeId','UiSound')}
        if category in ('melee_weapon','missile_weapon'):
            cls=rows['weapon'].get('weapon_class_id')
            source_class=self.tables.row('item/weapon_class','weapon_class_id',cls)['weapon_class_name']
            if self.weapon_classes.get(cls)!=source_class:
                raise ValueError('Weapon class semantics differ: '+source_class)
            matches=[r for r in self.native.values() if r.tag==self.CATEGORIES[category] and r.get('Class')==cls]
            if not matches:raise ValueError('No native weapon class contract '+str(cls))
            # Templates supply KCD2-only fields, never source weapon statistics.
            plan.source['native_template']=dict(sorted(matches,key=lambda r:r.get('Id'))[0].attrib)
        for table,field,suffix in [('weapon','holster_model','.cgf'),('ammo','inquiver_model','.cgf')]:
            if rows[table].get(field):plan.dependencies.append(('assets',self.asset(rows[table][field],suffix)))
        if category=='document':
            text=rows['document'].get('text_id')
            plan.source['document_parts']=[r for r in self.tables.get('item/document_content')['rows'] if r['text_id']==text]
            plan.source['document_images']=[r for r in self.tables.get('item/document_content_images')['rows'] if r['text_id']==text]
            plan.dependencies.extend(('strings',r['text']) for r in plan.source['document_parts'])
            plan.dependencies.extend(('document_images',r['image']) for r in plan.source['document_images'])
            # Book is the shipped KCD2 entity script, not a KCD1 script port.
            rows['pickable_item']['entity_script']=''
        candidates=[r for r in self.native.values() if r.tag==self.CATEGORIES.get(category) and r.get('IconId')]
        if candidates:
            source_name=rows['player_item'].get('ui_name','').lower()
            source_info=rows['player_item'].get('ui_info','').lower()
            candidates.sort(key=lambda r:(r.get('UIName','').lower()!=source_name,
                r.get('UIInfo','').lower()!=source_info,r.get('Id')))
            plan.source['presentation_template']=dict(candidates[0].attrib)
        return plan

    def convert(self,identity,plan,registered):
        _,files,evidence=super().convert(identity,plan,registered)
        category=plan.source['category'];rows=plan.source['rows']
        root=ET.fromstring(next(iter(files.values())));row=root.find('ItemClasses')[0]
        if 'native_template' in plan.source:
            # Do not inherit another weapon's clothing, quest or breakage IDs.
            allowed={'IconId','MaxQuality','LimbResistance','OldFormula','SoundSwitch','FireSoundMultiplicator','HolsterModel'}
            for k,v in plan.source['native_template'].items():
                if k in allowed and k not in row.attrib:row.set(k,v)
        if category in ('melee_weapon','ammo'):row.set('MaxQuality','1')
        if category in ('armor','helmet'):
            row.tag=plan.source.get('armor_native_tag',self.CATEGORIES[category])
            row.attrib.update(plan.source.get('armor_native_fields',{}))
            row.set('Clothing',registered['clothing'][identity]);row.set('MaxQuality','1')
            row.set('IconId',plan.source['armor_icon'])
        presentation=plan.source.get('presentation_template',{})
        if not row.get('IconId') and presentation.get('IconId'):row.set('IconId',presentation['IconId'])
        if category=='ammo':
            template=next(r for r in self.native.values() if r.tag=='Ammo' and r.get('Type')==row.get('Type'))
            row.set('RpgWeight',template.get('RpgWeight'))
        if category=='key':row.tag='MiscItem';row.set('Type','4');row.set('IconId','key_general')
        if category=='die':
            die=rows['die']
            row.set('SideWeights',' '.join(die.get('side_weight_'+str(i)) or '1' for i in range(1,7)))
            row.set('SideValues',' '.join(die.get('side_value_'+str(i)) or str(i-1) for i in range(1,7)))
        if category=='document':
            row.set('EntityScript','Book')
            parts=sorted(plan.source['document_parts'],key=lambda r:int(r['part']))
            content=ET.SubElement(row,'DocumentContent',Parts=' '.join(registered['strings'][r['text'].lower()] for r in parts))
            for image in plan.source['document_images']:
                ET.SubElement(content,'Image',Image=registered['document_images'][image['image'].lower()],Page=image['page'])
        for table,old,new,suffix in [('weapon','holster_model','HolsterModel','.cgf'),('ammo','inquiver_model','InquiverModel','.cgf')]:
            if rows[table].get(old):row.set(new,registered['assets'][self.asset(rows[table][old],suffix)].removeprefix('objects/'))
        # Retired native IDs still exist in item.xml. Give their imported
        # replacements a separate identity instead of defining the ID twice.
        replaced = identity in self.native and not usable_native_item(self.native[identity])
        if not replaced:
            row.set('Id',identity)
        target = row.get('Id')
        evidence.update(target_id=target,source_identity_preserved=not replaced,
                        replaced_native_placeholder=replaced)
        evidence['secondary_gameplay_pending']={
            table:dict(rows[table]) for table in ('consumable_item','potion')
            if any(v and k!='item_id' for k,v in rows[table].items())}
        if category=='document':
            evidence['reading_rewards_verified']=False
        return target,{name:xml(root) for name in files},evidence
