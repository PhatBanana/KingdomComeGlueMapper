"""Translate source opaque garment surfaces into conditional native hiding masks.

Source masks describe triangle opacity, not body visibility. Generate coverage
against the converted, fitted meshes; do not copy those bits onto body vertices.
The bounded normal-ray policy is explicit and does not claim to reproduce the
closed-source KCD1 raycaster exactly.
"""
import base64
import hashlib
from pathlib import Path
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


def source_opacity(rows, model, material, count, rendered_visibility=None, generated_opacity=None):
    def key(path):
        return path.replace('\\', '/').lower()
    matches = [r for r in rows if key(r['skin']) == key(model) and key(r['material']) == key(material)]
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous clothing raycast record: ' + model + ' / ' + material)
    row = matches[0]
    # An empty serialized field is unknown, not proof that every triangle is opaque.
    if not row.get('opaque_triangle_mask') and generated_opacity is None:
        raise ValueError('Source clothing raycast masks need generation: ' + material)
    if generated_opacity is not None:
        generated_opacity = np.asarray(generated_opacity)
        if generated_opacity.dtype != np.dtype(bool) or generated_opacity.shape != (count,):
            raise ValueError('Invalid generated garment opacity')
    if row.get('not_culled_triangle_mask'):
        visible = triangle_mask(row['not_culled_triangle_mask'], count)
    elif rendered_visibility is not None:
        visible = np.asarray(rendered_visibility)
        if visible.dtype != np.dtype(bool) or visible.shape != (count,):
            raise ValueError('Invalid converted garment visibility')
    else:
        raise ValueError('Source clothing raycast masks need generation: ' + material)
    opaque = triangle_mask(row['opaque_triangle_mask'], count) if row.get('opaque_triangle_mask') else generated_opacity
    return opaque & visible


def converted_coverage_surface(skin, rows, model, material, output, material_path, visibility):
    """A legacy triangle bit is a candidate, never proof of converted opacity."""
    surfaces, evidence = native_alpha_surfaces(output, material_path)
    opaque = source_opacity(rows, model, material, len(skin.faces),
                            rendered_visibility=visibility,
                            generated_opacity=np.ones(len(skin.faces), dtype=bool))
    return opaque, alpha_intersections(skin, surfaces, opaque), evidence


def native_alpha_surfaces(output, material_path):
    """Read the supported converted cloth permutation and its complete alpha mips."""
    root = ET.parse(material_path).getroot()
    materials = list(root.find('SubMaterials')) if root.find('SubMaterials') is not None else [root]
    evidence, surfaces = [], []
    allowed = {'CLOTHING_SYSTEM', 'NORMAL_MAP', 'SPECULAR_MAP', 'SUBSURFACE_SCATTERING'}
    for material in materials:
        if material.get('Shader','').lower() == 'nodraw':
            evidence.append(dict(shader='Nodraw', opaque=False))
            surfaces.append((0., [np.zeros((1,1))]))
            continue
        flags = set(filter(None, material.get('StringGenMask', '').split('%')))
        threshold = float(material.get('AlphaTest', '0'))
        if (material.get('Shader') != 'Illum' or 'CLOTHING_SYSTEM' not in flags or flags - allowed
                or material.get('MtlFlags') != '524290' or float(material.get('Opacity', '0')) != 1
                or not 0 <= threshold < 1 or material.find('SubMaterials') is not None):
            raise ValueError('Unsupported generated clothing opacity material')
        textures = material.findall("Textures/Texture[@Map='Diffuse']")
        if len(textures) != 1:
            raise ValueError('Missing or ambiguous clothing diffuse alpha')
        if len(textures[0]) or textures[0].get('IsTileU', '1') != '1' or textures[0].get('IsTileV', '1') != '1':
            raise ValueError('Unsupported clothing alpha UV transform or addressing')
        path = (Path(output) / textures[0].get('File')).resolve()
        if not path.is_relative_to(Path(output).resolve()):
            raise ValueError('Clothing opacity texture outside converted output')
        data = path.read_bytes()
        if (len(data) < 148 or data[:4] != b'DDS ' or data[84:88] != b'DX10'
                or struct.unpack_from('<I', data, 4)[0] != 124
                or struct.unpack_from('<I', data, 76)[0] != 32
                or struct.unpack_from('<5I', data, 128) != (10, 3, 0, 1, 0)):
            raise ValueError('Generated clothing alpha requires native RGBA16_FLOAT DDS')
        height, width = struct.unpack_from('<2I', data, 12)
        mip_count = struct.unpack_from('<I', data, 28)[0]
        if not width or not height or not 1 <= mip_count <= 32:
            raise ValueError('Invalid clothing opacity dimensions')
        offset = 148
        levels = []
        for mip in range(mip_count):
            size = width * height * 8
            if offset + size > len(data): raise ValueError('Truncated clothing alpha mip')
            pixels = np.frombuffer(data, dtype='<f2', count=width*height*4, offset=offset).reshape(-1,4)
            if not np.isfinite(pixels).all() or np.any(pixels[:,3] > 1) or np.any(pixels[:,3] < 0):
                raise ValueError('Invalid clothing alpha pixels')
            levels.append(pixels[:,3].reshape(height, width).copy())
            offset += size
            if width == height == 1 and mip != mip_count-1:
                raise ValueError('Extra clothing alpha mip')
            if mip < mip_count-1: width, height = max(1,width//2), max(1,height//2)
        if width != 1 or height != 1 or offset != len(data):
            raise ValueError('Incomplete clothing opacity mip chain')
        evidence.append(dict(texture=textures[0].get('File'), sha256=hashlib.sha256(data).hexdigest(), mips=mip_count))
        surfaces.append((threshold, levels))
    if not evidence: raise ValueError('Empty clothing material')
    return surfaces, evidence


def opaque_native_surface(output, material_path, count):
    """Prove full opacity across every texel and mip without a UV approximation."""
    surfaces, evidence = native_alpha_surfaces(output, material_path)
    if any(not np.all(level > threshold) for threshold, levels in surfaces for level in levels):
        raise ValueError('Cutout clothing needs triangle opacity generation')
    return np.ones(count, dtype=bool), evidence


def alpha_intersections(skin, surfaces, selected):
    """Filter ray hits using UVs, subset materials and conservative mip footprints.

    All four bilinear texels must survive in every mip. This can retain extra
    hidden skin near cutout edges, but never treats a transparent opening as
    an opaque cover. No missing cache is replaced with all-opaque triangles.
    """
    stream = skin.streams[2]
    if struct.unpack_from('<4I', stream.data) != (0, 2, skin.n, 8):
        raise ValueError('Unsupported clothing coverage UV stream')
    uv = np.frombuffer(stream.data[24:], '<f4').reshape(-1, 2)
    if len(uv) != skin.n or not np.isfinite(uv).all():
        raise ValueError('Invalid clothing coverage UVs')
    materials = np.full(len(skin.faces), -1, dtype=int)
    for subset in skin.info['subset_records']:
        start, count, slot = (subset[k] for k in ('first_index', 'num_indices', 'material_id'))
        if start % 3 or count % 3 or start < 0 or start + count > len(skin.faces)*3 or not 0 <= slot < len(surfaces):
            raise ValueError('Invalid clothing coverage material subset')
        target = materials[start//3:(start+count)//3]
        if np.any(target != -1): raise ValueError('Overlapping clothing coverage subsets')
        target[:] = slot
    if np.any(materials == -1): raise ValueError('Unassigned clothing coverage triangles')
    face_uv, materials = uv[skin.faces[selected]], materials[selected]

    def accepts(triangle, u, v):
        coords = face_uv[triangle]
        point = coords[:,0] * (1-u-v)[:,None] + coords[:,1]*u[:,None] + coords[:,2]*v[:,None]
        result = np.ones(len(triangle), bool)
        for slot in np.unique(materials[triangle]):
            indices = np.flatnonzero(materials[triangle] == slot)
            threshold, levels = surfaces[slot]
            for level in levels:
                height, width = level.shape
                xy = np.floor(point[indices] * [width, height] - .5).astype(np.int64)
                for dx, dy in ((0,0), (1,0), (0,1), (1,1)):
                    result[indices] &= level[(xy[:,1]+dy) % height, (xy[:,0]+dx) % width] > threshold
        return result
    return accepts


def unculled_garment_visibility(skin):
    """Visibility evidence for complete imported meshes with cleared hiding bits.

    This does not reconstruct the legacy cache. It describes the converted
    garment used for the coverage rays. Unknown/retained hiding is rejected.
    Texture cutouts still come from the required source opacity mask.
    """
    colors = skin.streams[3]
    if struct.unpack_from('<I', colors.data, 12)[0] != 4:
        raise ValueError('Expected RGBA garment visibility')
    alpha = np.frombuffer(colors.data[24:], dtype=np.uint8).reshape(-1, 4)[:, 3]
    if len(alpha) != skin.n or np.any(alpha != 255):
        raise ValueError('Converted garment retains unknown hiding membership')
    internal_alpha = np.frombuffer(skin.internal.data[95::64], dtype=np.uint8)
    if len(internal_alpha) != skin.ninternal or np.any(internal_alpha[skin.remap] != alpha):
        raise ValueError('Converted garment hiding buffers disagree')
    return np.ones(len(skin.faces), dtype=bool)


def covered_points(points, normals, triangles, inward=.06, outward=.12, accept_hit=None):
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
        if accept_hit is not None:
            point_ids, triangle_ids = np.nonzero(hits)
            hits[point_ids, triangle_ids] &= accept_hit(triangle_ids, u[point_ids, triangle_ids], v[point_ids, triangle_ids])
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
    masks = {}; report = []; used_groups = set(); visibility_sources = []
    for index, garment in enumerate(ordered):
        node = derived.find("Clothing[@Name='" + namespace + '_' + garment['stem'] + "']")
        model = folder / (garment['stem'] + '.skin')
        cover = CompiledSkin(model.read_bytes())
        matching = [r for r in rows if r['skin'].replace('\\', '/').lower() == garment['source_model'].replace('\\', '/').lower()
                    and r['material'].replace('\\', '/').lower() == garment['source_material'].replace('\\', '/').lower()]
        visibility = (unculled_garment_visibility(cover)
                      if len(matching) == 1 and not matching[0].get('not_culled_triangle_mask') else None)
        opaque, accept_hit, evidence = converted_coverage_surface(
            cover, rows, garment['source_model'], garment['source_material'],
            output, folder / (garment['stem'] + '.mtl'), visibility)
        visibility_sources.append(dict(garment=garment['stem'],
            visibility='source_cache' if matching[0].get('not_culled_triangle_mask') else 'converted_complete_mesh',
            opacity='converted_alpha_intersections', evidence=evidence))
        triangles = cover.vertices[cover.faces[opaque]]
        _, region, layer = garment_layout(garment['part'])
        names = []
        for target in targets:
            if target['rank'] >= layer or (target['region'] is not None and target['region'] != region):
                continue
            element = target['element']; path = folder / element.get('Model')
            skin = CompiledSkin(path.read_bytes())
            covered = covered_points(skin.vertices, normals(skin), triangles, accept_hit=accept_hit)
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
                               candidate_triangles=int(opaque.sum()),
                               opacity_test='UV_alpha_at_intersection',
                               hiding_group=name, bit=bit))
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
    return dict(policy='Source triangle candidates intersected with converted alpha; bounded normal rays after fitting',
                inward_metres=.06, outward_metres=.12, layers=report,
                visibility_sources=visibility_sources, runtime_verified=False)
