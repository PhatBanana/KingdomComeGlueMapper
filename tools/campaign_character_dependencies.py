"""Import authored character parts using the accepted male/female skin upgrader.

Character identities come from retail rows, never NPC names. This adapter is
also usable without a quest so population and campaign conversion share it.
"""
import hashlib
import uuid
import xml.etree.ElementTree as ET

from audit_character_bodies import Assets
from build_npc_probe import asset_path, bind_material
from campaign_dependencies import ImportPlan
from campaign_quest_graph import identifier, xml
from character_skin_upgrade import upgrade_skin, limit_skin_influences
from clothing_regions import assign_body_regions, split_skin_regions
from character_lods import source_lods, filename, validate_chain


class CharacterPartAdapter:
    KINDS = {'body': 'torso', 'head': 'face', 'hair': 'head', 'beard': 'beard'}

    def __init__(self, tables, target, stack, assets, namespace):
        self.tables, self.target, self.stack, self.assets = tables, target, stack, assets
        self.namespace = identifier(namespace).lower()
        self.native, self.rigs = None, {}

    def plan(self, identity):
        kind, value = identity.split(':', 1)
        if kind not in self.KINDS:
            raise ValueError('Unknown source character part kind: ' + kind)
        uuid.UUID(value)
        table = 'character_' + kind
        source = self.tables.row(table, table + '_id', value)
        if source.get('race_id') != '0' or source.get('gender_id') not in ('1', '2'):
            raise ValueError('Character rig conversion requires a supported source race/gender')
        if self.assets.adapter is None:
            self.assets.adapter = self.assets.factory()
        pack = self.assets.adapter
        part = dict(source, kind=kind)
        model = asset_path(pack.index, part, 'model', '.skin')
        material = asset_path(pack.index, part, 'material', '.mtl')
        archive, entry = pack.index[model]
        return ImportPlan([('assets', material)], dict(kind=kind, row=source, model=model, material=material,
            lods=source_lods(pack.index, model),
            provenance=self.tables.get(table)['provenance'], mesh_archive=str(archive.filename), mesh_entry=entry.filename))

    def convert(self, identity, plan, registered):
        part = plan.source
        kind, sex = part['kind'], {'1': 'male', '2': 'female'}[part['row']['gender_id']]
        if self.native is None:
            self.native = Assets(self.target, self.stack)
        if sex not in self.rigs:
            self.rigs[sex] = self.native.get('objects/characters/humans/' + sex + '/skeleton/' + sex + '.chr')
        skeleton, provenance = self.rigs[sex]
        pack = self.assets.adapter
        previous = set(pack.emitted)
        suffix = hashlib.sha256(identity.encode()).hexdigest()[:20]
        component = self.namespace + '_' + kind + '_' + suffix
        folder = 'gluecampaign/' + self.namespace + '/' + suffix + '/'
        prefix = 'objects/characters/' + folder
        material = registered['assets'][part['material']].removesuffix('.mtl')
        original, material = bind_material(pack.mesh(part['model']), material, pack.emitted, prefix + 'slots')
        skin, evidence = upgrade_skin(original, skeleton, geometry_mode='preserve', clear_hiding=kind in ('body', 'head'))
        skin, influences = limit_skin_influences(skin)
        lods = {}
        for level, model in part.get('lods', {}).items():
            lower, lower_material = bind_material(pack.mesh(model), material, pack.emitted, prefix + 'slots')
            if lower_material != material:
                raise ValueError('Character LOD requires a different material binding: ' + model)
            lower, _ = upgrade_skin(lower, skeleton, geometry_mode='preserve', clear_hiding=kind in ('body', 'head'))
            lods[level], _ = limit_skin_influences(lower)
        material_blob = pack.emitted[material + '.mtl']
        material_root = ET.fromstring(material_blob.read_bytes() if hasattr(material_blob, 'read_bytes') else material_blob)
        slots = material_root.find('SubMaterials')
        validate_chain(skin, lods, material_slots=len(slots) if slots is not None else 1)
        regions = split_skin_regions(skin, assign_body_regions(skin)) if kind == 'body' and sex == 'male' else {self.KINDS[kind]: skin}
        lower_regions = {level: (split_skin_regions(lower, assign_body_regions(lower))
            if kind == 'body' and sex == 'male' else {self.KINDS[kind]: lower}) for level, lower in lods.items()}
        files = {n: pack.emitted[n] for n in pack.emitted if n not in previous}
        files[prefix + 'material.mtl'] = pack.emitted[material + '.mtl']
        root = ET.Element('database', name='barbora')
        components = ET.SubElement(root, 'CharacterComponents', version='6')
        container = ET.SubElement(components, 'Component', Name=component + '_root', Race='Human', Gender=sex.title(), FilePath=folder)
        node = ET.SubElement(ET.SubElement(container, 'DerivedComponents'), kind.title(), Name=component)
        elements = ET.SubElement(node, 'Elements')
        for region, blob in regions.items():
            base_name = region + '.skin'
            files[prefix + base_name] = blob
            chain = {level: value[region] for level, value in lower_regions.items() if region in value}
            if chain and sorted(chain) != list(range(1, max(chain) + 1)):
                raise ValueError('Character region disappears and returns in its LOD chain: ' + region)
            validate_chain(blob, chain)
            for level, lower in chain.items():
                files[prefix + filename(base_name, level)] = lower
            ET.SubElement(elements, 'SkinElement', EquipmentPart=region, BodyLayerId='0', Model=base_name,
                          Material='material.mtl', IsFinalLayer='false', KeepBodyLayer='false')
        files['Libs/Tables/Character/CharacterComponent__' + component + '.xml'] = xml(root)
        return component, files, dict(source=part, gender=sex, rig=provenance, geometry=evidence,
            influences=influences, regions=list(regions), geometry_mode='preserve', body_from_source=True,
            runtime_validated=False)
