"""Translate source opaque garment surfaces into conditional native hiding masks.

Source masks describe triangle opacity, not body visibility. Generate coverage
against the converted, fitted meshes; do not copy those bits onto body vertices.
The bounded normal-ray policy is explicit and does not claim to reproduce the
closed-source KCD1 raycaster exactly.
"""
import base64
import struct
import xml.etree.ElementTree as ET

import numpy as np

from character_skin_upgrade import CompiledSkin
from clothing_regions import write_chunks
from character_source_clothing import garment_layout
from upgrade_map import xml


def triangle_mask(encoded, count):
    data = base64.b64decode(encoded, validate=True)
    if len(data) != 2 + (count + 7) // 8 or struct.unpack_from('<H', data)[0] != count:
        raise ValueError('Source triangle mask does not match mesh topology')
    return np.unpackbits(np.frombuffer(data[2:], dtype=np.uint8), bitorder='little')[:count].astype(bool)


def source_opacity(rows, model, material, count):
    def key(path):
        return path.replace('\\', '/').lower()
    matches = [r for r in rows if key(r['skin']) == key(model) and key(r['material']) == key(material)]
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous clothing raycast record: ' + model + ' / ' + material)
    row = matches[0]
    # An empty serialized field is unknown, not proof that every triangle is opaque.
    if not row.get('opaque_triangle_mask') or not row.get('not_culled_triangle_mask'):
        raise ValueError('Source clothing raycast masks need generation: ' + material)
    return triangle_mask(row['opaque_triangle_mask'], count) & triangle_mask(row['not_culled_triangle_mask'], count)


def covered_points(points, normals, triangles, inward=.06, outward=.12):
    """Test two-sided triangles along short surface-normal segments (metres)."""
    points, normals, triangles = (np.asarray(a, dtype=float) for a in (points, normals, triangles))
    result = np.zeros(len(points), dtype=bool)
    if not len(triangles):
        return result
    a = triangles[:, 0]
    edge1, edge2 = triangles[:, 1] - a, triangles[:, 2] - a
    for start in range(0, len(points), 64):
        p, direction = points[start:start+64], normals[start:start+64]
        h = np.cross(direction[:, None, :], edge2)
        det = np.einsum('tj,ntj->nt', edge1, h)
        valid = np.abs(det) > 1e-10
        inv = np.divide(1., det, out=np.zeros_like(det), where=valid)
        delta = p[:, None, :] - a
        u = np.einsum('ntj,ntj->nt', delta, h) * inv
        q = np.cross(delta, edge1)
        v = np.einsum('nj,ntj->nt', direction, q) * inv
        distance = np.einsum('tj,ntj->nt', edge2, q) * inv
        hits = valid & (u >= -1e-7) & (v >= -1e-7) & (u+v <= 1+1e-7)
        hits &= (distance >= -inward) & (distance <= outward)
        result[start:start+len(p)] = hits.any(axis=1)
    return result


def normals(skin):
    vertices, faces = skin.vertices, skin.faces
    face_normals = np.cross(vertices[faces[:, 1]]-vertices[faces[:, 0]],
                            vertices[faces[:, 2]]-vertices[faces[:, 0]])
    # Weld duplicated render vertices using the engine's own internal remap.
    welded = np.zeros((skin.ninternal, 3))
    for column in range(3):
        np.add.at(welded, skin.remap[faces[:, column]], face_normals)
    result = welded[skin.remap]
    return result / np.maximum(np.linalg.norm(result, axis=1)[:, None], 1e-12)


def apply_membership(blob, memberships):
    skin = CompiledSkin(blob)
    colors = skin.streams[3]
    if struct.unpack_from('<I', colors.data, 12)[0] != 4:
        raise ValueError('Expected RGBA hiding membership')
    alpha = np.full(skin.n, 255, dtype=np.uint8)
    for bit, covered in memberships.items():
        if bit not in range(4, 8) or len(covered) != skin.n:
            raise ValueError('Invalid native coverage allocation')
        # Every render copy must agree, otherwise a seam can appear in animation.
        shared = np.zeros(skin.ninternal, dtype=bool)
        np.logical_or.at(shared, skin.remap, covered)
        alpha[shared[skin.remap]] &= np.uint8(255 ^ (1 << bit))
    payload = bytearray(colors.data)
    payload[27::4] = alpha.tobytes()
    internal = bytearray(skin.internal.data)
    for i, remap in enumerate(skin.remap):
        internal[32 + int(remap)*64 + 63] = int(alpha[i])
    return write_chunks(skin.chunks, {colors.id: bytes(payload), skin.internal.id: bytes(internal)})


def register_coverage(output, component, garments, tables, namespace):
    folder = output / 'objects/characters' / component.get('FilePath')
    derived = component.find('DerivedComponents')
    rows = tables.get('item/clothing_raycast')['rows']
    ordered = sorted(garments, key=lambda g: (garment_layout(g['part'])[1:]))
    if len(ordered) > 4:
        raise ValueError('Outfit needs more than four independent native hiding groups')
    groups = ET.Element('database', name='barbora')
    definitions = ET.SubElement(groups, 'ClothingHidingGroups', version='2')
    targets = []
    for element in derived.find('Body/Elements'):
        targets.append(dict(element=element, rank=0, region=None, component=derived.find('Body')))
    for garment in ordered:
        node = derived.find("Clothing[@Name='" + namespace + '_' + garment['stem'] + "']")
        _, region, layer = garment_layout(garment['part'])
        targets.append(dict(element=node.find('Elements/SkinElement'), rank=layer, region=region, component=node))
    masks = {}; report = []; used_groups = set()
    for index, garment in enumerate(ordered):
        node = derived.find("Clothing[@Name='" + namespace + '_' + garment['stem'] + "']")
        model = folder / (garment['stem'] + '.skin')
        cover = CompiledSkin(model.read_bytes())
        opaque = source_opacity(rows, garment['source_model'], garment['source_material'], len(cover.faces))
        triangles = cover.vertices[cover.faces[opaque]]
        _, region, layer = garment_layout(garment['part'])
        names = []
        for target in targets:
            if target['rank'] >= layer or (target['region'] is not None and target['region'] != region):
                continue
            element = target['element']; path = folder / element.get('Model')
            skin = CompiledSkin(path.read_bytes())
            covered = covered_points(skin.vertices, normals(skin), triangles)
            if not covered.any():
                continue
            bit = 4 + index
            masks.setdefault(path, {})[bit] = covered
            name = namespace + '_' + garment['stem'] + '_covers_' + element.get('EquipmentPart')
            if name not in used_groups:
                ET.SubElement(definitions, 'HidingGroup', Name=name, Index=str(bit), EquipmentPart=element.get('EquipmentPart'))
                used_groups.add(name)
            names.append(name)
            report.append(dict(cover=garment['stem'], target=element.get('Model'),
                               covered_vertices=int(covered.sum()), total_vertices=skin.n,
                               opaque_triangles=int(opaque.sum()), hiding_group=name, bit=bit))
        node.set('HidingGroups', ' '.join(sorted(set(names))))
        # The fallback underwear uses the same mesh and must hide the same body
        # coverage when no equipped dress is present.
        for other in derived.findall('Clothing'):
            if other.get('ArmorType') is None and any(e.get('Model') == model.name for e in other.findall('Elements/SkinElement')):
                other.set('HidingGroups', node.get('HidingGroups'))
    for path, membership in masks.items():
        path.write_bytes(apply_membership(path.read_bytes(), membership))
    path = output / ('Libs/Tables/Character/ClothingHidingGroup__' + namespace + '.xml')
    path.write_bytes(xml(groups))
    return dict(policy='Opaque source triangles, bounded normal rays after fitting',
                inward_metres=.06, outward_metres=.12, layers=report, runtime_verified=False)
