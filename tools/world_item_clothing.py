"""Wearable source pickup components, with source meshes on the native rig."""
import xml.etree.ElementTree as ET
import zipfile
from audit_character_bodies import Assets
from build_npc_probe import asset_path, bind_material
from campaign_dependencies import ImportPlan
from character_person import native_xml
from character_person_appearance import align_internal_translation
from character_skin_upgrade import upgrade_skin, limit_skin_influences, CompiledSkin, matrix, read_morphs
from clothing_appearance import apply_armor_colorization
from clothing_regions import assign_upper_garment_regions, split_skin_regions, read_chunks
from garment_contracts import clothing_role, source_variant
from character_source_clothing import female_role
from upgrade_map import read, xml


class ClothingAdapter:
    # Source SQL armor_type is distinct from KCD2's enum. Resolve an explicit
    # semantic role, then inherit the native role's layer and archetype.
    ROLES = {'7': 'Cap', '11': 'HorseShoe'}

    def __init__(self, tables, assets, target, stack):
        self.tables, self.assets = tables, assets
        self.native = Assets(target, stack)
        with zipfile.ZipFile(target/'Data/Tables.pak') as z:
            self.components = native_xml(read(z, 'Libs/Tables/Character/CharacterComponent.xml'))
        self.parents = {c:p for p in self.components.iter() for c in p}

    def plan(self, identity):
        armor = self.tables.row('item/armor', 'item_id', identity)
        part = self.tables.row('item/clothing', 'clothing_id', armor['clothing_id'])
        role = clothing_role(self.tables, armor, part)
        return ImportPlan(source=dict(armor=armor, part=part, role=role))

    def convert(self, identity, plan, registered):
        part, armor, role = (plan.source[k] for k in ('part','armor','role'))
        original = next(n for n in self.components.iter('Clothing') if n.get('Name') == role and n.get('ArmorType') == role)
        ancestor = original
        while not ancestor.get('ArmorArchetypeId'): ancestor = self.parents[ancestor]
        name = 'worlditems_cloth_'+identity.replace('-','_')
        prefix = 'objects/characters/gluetravel/worlditems/'+identity.replace('-','')+'/'
        root = ET.Element('database', name='barbora')
        horse = role in ('HorseShoe','Saddle','Bridle','Caparison')
        sex = 'female' if part.get('gender_id') == '2' else 'male'
        component = ET.SubElement(ET.SubElement(root,'CharacterComponents',version='6'),'Component',
            Name=name+'_root', Race='Horse' if horse else 'Human',
            FilePath=prefix.removeprefix('objects/characters/'))
        if not horse: component.set('Gender',sex.title())
        node = ET.SubElement(ET.SubElement(component,'DerivedComponents'),'Clothing',
            Name=name, ArmorType=role, ArmorArchetypeId=ancestor.get('ArmorArchetypeId'))
        files = {}
        missing_variant = None
        internal_offset = None
        if part.get('model'):
            a = self.assets; before = set(a.emitted)
            source_part = dict(part, kind='cloth')
            def resolve(field, extension):
                if not horse: return asset_path(a.index, source_part, field, extension)
                value = part[field].replace('\\','/').lower().removesuffix(extension)
                matches = [p for p in a.index if p.startswith('objects/characters/animals/horse/') and p.endswith('/'+value+extension)]
                if len(matches) != 1: raise ValueError('Ambiguous source horse equipment '+field+': '+value)
                return matches[0]
            model = resolve('model', '.skin')
            mat = a.material(resolve('material', '.mtl'))
            tinted = prefix+'source'
            a.emitted[tinted+'.mtl'] = xml(apply_armor_colorization(ET.parse(a.emitted[mat+'.mtl']).getroot(),armor))
            blob,mat = bind_material(a.mesh(model), tinted, a.emitted, prefix+'slots')
            # Some shipped gauntlets retain an 11 cm internal-buffer offset.
            # Every mapped vertex must agree on one translation; rendered
            # positions are never moved or approximated.
            blob,internal_offset = align_internal_translation(blob, max_translation=.25)
            skeleton,_ = self.native.get('objects/characters/animals/horse/horse.chr' if horse else f'objects/characters/humans/{sex}/skeleton/{sex}.chr')
            available = [m['name'] for c in read_chunks(blob) if c.kind == 0x2002 for m in read_morphs(c)]
            variant, missing_variant = source_variant(part.get('morph_target'), available)
            blob,detail = upgrade_skin(blob,skeleton,variant=variant,
                discard_unused_variants=True,geometry_mode='preserve',clear_hiding=False)
            blob,_ = limit_skin_influences(blob)
            region = 'head'
            if horse: region = 'horse_back' if role in ('Saddle','Caparison') else 'horse_head'
            elif sex == 'female': region = female_role(part)[1]
            elif role in ('HoseJoined','HoseSeparate','LegsChain','LegsPlate','LegsBrigandine','LegsPadded'): region = 'legs'
            elif role in ('Shoes','BootsAnkle','BootsKnee'): region = 'feet'
            elif role in ('Gauntlets','Gloves'): region = 'hands'
            elif role in ('ArmPlate','ArmBrigandine'): region = 'arms'
            elif role in ('Hood','CollarMail','CollarPadded'): region = 'neck'
            regions = {region:blob}
            if sex == 'male' and role in ('Habit','TunicLong','TunicShort','GambesonLong','GambesonShort','MailShort','Cuirass','Waffenrock','Coat'):
                bones = CompiledSkin(blob).info['bones']
                waist = float(matrix(next(b for b in bones if b['name']=='Hips')['bind'])[2,3])
                regions = split_skin_regions(blob,assign_upper_garment_regions(blob,waist_z=waist))
            elements = ET.SubElement(node,'Elements')
            # Native layer values are inherited by role; do not reuse KCD1's
            # numerical layers as KCD2 layers.
            for region,skin in regions.items():
                ancestor = original; layer = None
                while ancestor is not None and layer is None:
                    e = ancestor.find("Elements/SkinElement[@EquipmentPart='"+region+"']")
                    if e is not None: layer = e.get('BodyLayerId')
                    ancestor = self.parents.get(ancestor)
                files[prefix+region+'.skin'] = skin
                element = ET.SubElement(elements,'SkinElement',EquipmentPart=region,Model=region+'.skin',
                    Material='source.mtl',KeepBodyLayer='true',IsFinalLayer='true')
                if layer is not None: element.set('BodyLayerId',layer)
            files.update({n:a.emitted[n] for n in a.emitted if n not in before})
            files[prefix+'source.mtl'] = a.emitted[mat+'.mtl']
        elif role not in ('HorseShoe','Ring','Necklace','Spurs'): raise ValueError('Source wearable is missing a model')
        files['Libs/Tables/Character/CharacterComponent__'+name+'.xml'] = xml(root)
        return name, files, dict(role=role,source_clothing=part['clothing_id'],source_geometry_preserved=True,
            missing_source_variant=missing_variant, internal_translation=internal_offset, fitting_runtime_verified=False)
