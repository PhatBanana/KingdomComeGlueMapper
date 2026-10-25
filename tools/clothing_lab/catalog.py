"""Resolve component inheritance and native equipment contracts for the lab."""
import base64
from functools import lru_cache
import hashlib
import posixpath
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
from character_person import native_xml
from character_skin_upgrade import CompiledSkin
from clothing_coverage import normals
from upgrade_map import read
from .assets import Assets, key


def resolved_nodes(document, roles_only=False):
    """Yield named leaves with inherited attributes and per-part/layer overrides."""
    def walk(node, attrs, elements, path, family):
        attrs = dict(attrs, **node.attrib)
        if roles_only and attrs.get('Race','Human') != 'Human': return
        path = node.get('FilePath', path)
        if node.tag == 'Component' and node.get('FilePath'): family = node.get('Name', family)
        elements = {k:dict(v) for k,v in elements.items()}
        for element in node.findall('Elements/*'):
            if element.tag not in ('SkinElement', 'VClothElement'): continue
            slot = (element.get('EquipmentPart'), element.get('BodyLayerId'))
            previous = [k for k in elements if k[0] == slot[0]]
            if slot[1] is None and len(previous) == 1: slot = previous[0]
            elif slot[1] is None and len(previous) > 1: raise ValueError('Ambiguous inherited layer: '+node.get('Name',''))
            if slot[1] is not None and slot not in elements and (slot[0],None) in elements:
                elements[slot]=elements.pop((slot[0],None))
            merged = dict(elements.get(slot, {}), **element.attrib, element_type=element.tag)
            for field in ('Model','Material'):
                if field in element.attrib:
                    value = element.get(field)
                    merged[field+'Resolved'] = key(posixpath.normpath('objects/characters/'+path.rstrip('/')+'/'+value)) if value else ''
            elements[slot] = merged
        if node.tag in ('Body','Head','Hair','Beard','Clothing') and node.get('Name'):
            yield dict(id=node.get('Name'), kind=node.tag, family=family, gender=attrs.get('Gender','Unknown'),
                       attributes=attrs, elements=list(elements.values()))
            if roles_only and node.get('Name') == attrs.get('ArmorType'): return
        for child in node.findall('DerivedComponents/*'):
            yield from walk(child, attrs, elements, path, family)
        if node.tag in ('database','CharacterComponents'):
            for child in node: yield from walk(child, attrs, elements, path, family)
    yield from walk(document, {}, {}, '', '')


class Catalog:
    def __init__(self, package, target=None):
        self.assets = Assets(package)
        self.parts, self.presets, self.groups, self.souls, self.errors = {}, {}, {}, {}, []
        self.native_roles, self.rule_evidence = {}, []
        if target:
            path = Path(target)/'Data/Tables.pak'
            with zipfile.ZipFile(path) as archive:
                name = 'Libs/Tables/Character/CharacterComponent.xml'
                data = read(archive, name)
                for part in resolved_nodes(native_xml(data), roles_only=True):
                    attrs = part['attributes']
                    role = attrs.get('ArmorType')
                    if role and part['id'] == role:
                        self.native_roles[role] = dict(archetype=attrs.get('ArmorArchetypeId'), gender=part['gender'],
                            layers=sorted({(e.get('EquipmentPart'), e.get('BodyLayerId')) for e in part['elements']}, key=str))
                self.rule_evidence.append(dict(file=str(path), member=name, sha256=hashlib.sha256(data).hexdigest()))
                group_data = read(archive, 'Libs/Tables/Character/ClothingHidingGroup.xml')
                self._groups(native_xml(group_data))
        names = list(self.assets.index)
        for name in names:
            if not name.startswith('libs/tables/') or not name.endswith('.xml'): continue
            try:
                if '/soul__' in name:
                    for soul in ET.fromstring(self.assets.read(name)).iter('soul'):
                        self.souls[soul.get('soul_id','').replace('-','')] = dict(soul.attrib)
                elif '/clothinghidinggroup__' in name:
                    self._groups(ET.fromstring(self.assets.read(name)))
                elif '/charactercomponent__' in name:
                    for part in resolved_nodes(ET.fromstring(self.assets.read(name))):
                        if not part['elements']: continue
                        if part['id'] in self.parts: raise ValueError('Duplicate component: '+part['id'])
                        part['table'] = name
                        part['label'] = part['id']
                        self.parts[part['id']] = part
            except (ValueError, ET.ParseError) as exc: self.errors.append(dict(asset=name, error=str(exc)))
        for part in self.parts.values():
            identity = part['family'].removesuffix('_root').removeprefix('gm_person_')
            actor = self.souls.get(identity, {}).get('soul_name', part['family'].removesuffix('_root'))
            part['actor'] = actor
            part['label'] = actor+' · '+part['id'].removeprefix(part['family'].removesuffix('_root')+'_')
            self.presets.setdefault(part['family'], dict(id=part['family'], label=actor, gender=part['gender'], parts=[]))['parts'].append(part['id'])
        self.presets = {k:v for k,v in self.presets.items() if any(self.parts[p]['kind']=='Body' for p in v['parts'])}
        # Underwear is a fallback, not an additional equipped copy of its source dress.
        for preset in self.presets.values():
            preset['parts'] = [p for p in preset['parts'] if not (self.parts[p]['kind']=='Clothing' and not self.parts[p]['attributes'].get('ArmorType'))]

    def _groups(self, doc):
        for g in doc.iter('HidingGroup'):
            value = dict(index=int(g.get('Index')), region=g.get('EquipmentPart'))
            if g.get('Name') in self.groups and self.groups[g.get('Name')] != value:
                raise ValueError('Conflicting hiding group definition: '+g.get('Name'))
            self.groups[g.get('Name')] = value

    def summary(self):
        return dict(package=str(self.assets.root), signature=self.assets.signature(), parts=list(self.parts.values()),
                    presets=list(self.presets.values()), groups=self.groups, errors=self.errors,
                    native_rules=bool(self.native_roles), rule_evidence=self.rule_evidence)

    @lru_cache(maxsize=32)
    def mesh(self, name):
        return CompiledSkin(self.assets.read(name))

    def materials(self, name, textures=False):
        if not name: raise ValueError('Component has no resolved material')
        root = ET.fromstring(self.assets.read(name))
        nodes = list(root.find('SubMaterials')) if root.find('SubMaterials') is not None else [root]
        output = []
        for node in nodes:
            diffuse = node.find("Textures/Texture[@Map='Diffuse']")
            item = dict(name=node.get('Name',''), shader=node.get('Shader',''), threshold=float(node.get('AlphaTest','0')),
                        opacity=float(node.get('Opacity','1')), texture=diffuse.get('File') if diffuse is not None else None)
            if textures and item['texture']:
                macro='CLOTHING_SYSTEM' in node.get('StringGenMask','')
                item['image'] = 'data:image/png;base64,'+base64.b64encode(self.assets.texture(item['texture'],macro)).decode()
            output.append(item)
        return output

    def scene(self, selected, lod=0):
        from .validation import body_replaced
        if not isinstance(selected,list) or not 1 <= len(selected) <= 64: raise ValueError('Select 1–64 components')
        if lod not in range(5): raise ValueError('Invalid LOD')
        rows, errors = [], []
        for identity in dict.fromkeys(selected):
            part = self.parts[identity]
            for e in part['elements']:
                name = e.get('ModelResolved','')
                if lod: name = name.removesuffix('.skin')+'_lod'+str(lod)+'.skin'
                try:
                    skin = self.mesh(name)
                    uv = np.frombuffer(skin.streams[2].data[24:], '<f4').reshape(-1,2)
                    alpha = np.frombuffer(skin.streams[3].data[24:],np.uint8).reshape(-1,4)[:,3]
                    if len(uv) != skin.n or len(alpha) != skin.n: raise ValueError('Invalid vertex stream size')
                    def buffer(a, dtype): return base64.b64encode(np.asarray(a,dtype=dtype).tobytes()).decode()
                    rows.append(dict(id=identity, kind=part['kind'], element=e, model=name, replaced=body_replaced(self,selected,part,e), provenance=self.assets.provenance(name),
                        positions=buffer(skin.vertices,'<f4'), normals=buffer(normals(skin),'<f4'), uv=buffer(uv,'<f4'),
                        indices=buffer(skin.faces,'<u4'), alpha=buffer(alpha,'u1'), bones=skin.info['bones'],
                        weights=buffer(skin.weights,'<f4'), joints=buffer(skin.ids,'<u2'), influences=skin.ids.shape[1],
                        subsets=skin.info['subset_records'], materials=self.materials(e.get('MaterialResolved'),True)))
                except (ValueError, KeyError, OSError, NotImplementedError) as exc:
                    errors.append(dict(component=identity, asset=name, error=str(exc)))
        return dict(meshes=rows, errors=errors, lod=lod)
