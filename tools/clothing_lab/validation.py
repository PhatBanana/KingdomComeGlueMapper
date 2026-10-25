"""Native table checks and conservative geometry diagnostics, never engine certification."""
from itertools import combinations, product
import math

import numpy as np
from clothing_coverage import normals, alpha_intersections
from .geometry import Surface


def finding(code, message, components=(), severity='review', **evidence):
    return dict(code=code, severity=severity, message=message, components=list(components), **evidence)


def active_masks(catalog, selected):
    masks = {}
    for identity in selected:
        part = catalog.parts[identity]
        for name in part['attributes'].get('HidingGroups','').split():
            g = catalog.groups.get(name)
            if g and 0 <= g['index'] < 8:
                masks[g['region']] = masks.get(g['region'],0) | (1 << g['index'])
    return masks


def body_replaced(catalog, selected, part, element):
    if part['kind']!='Body':return False
    region=element.get('EquipmentPart');layer=int(element.get('BodyLayerId') or 0)
    return any(other['kind']=='Clothing' and any(e.get('EquipmentPart')==region
        and str(e.get('BodyLayerId','')).isdigit() and int(e['BodyLayerId'])>layer
        and e.get('KeepBodyLayer','false')!='true' for e in other['elements'])
        for other in (catalog.parts[i] for i in selected))


def validate(catalog, selected, geometry=False, lod=0):
    selected = list(dict.fromkeys(selected))
    findings, meshes, slots, roles, families = [], [], {}, {}, set()
    if not catalog.native_roles:
        findings.append(finding('native_rules_unavailable','Select a KCD2 installation to validate native clothing roles.',selected))
    genders = {catalog.parts[i]['gender'] for i in selected}
    if len(genders) > 1: findings.append(finding('gender_conflict','The selection mixes male and female components.',selected,'error'))
    if not any(catalog.parts[i]['kind']=='Body' for i in selected):
        findings.append(finding('missing_body','No body component is selected.', selected, 'error'))
    masks = active_masks(catalog,selected)
    for identity in selected:
        part = catalog.parts[identity]; attrs = part['attributes']
        families.add(part['family'])
        role = attrs.get('ArmorType')
        if role:
            roles.setdefault(attrs.get('ArmorArchetypeId', role), []).append(identity)
            native = catalog.native_roles.get(role)
            if catalog.native_roles and native is None:
                findings.append(finding('unknown_native_role','Clothing role is absent from the selected KCD2 tables.',[identity],'error',role=role))
            elif native:
                if native['archetype'] != attrs.get('ArmorArchetypeId') or native['gender'] != part['gender']:
                    findings.append(finding('native_role_mismatch','Archetype or gender differs from the inherited KCD2 role.',[identity],'error',expected=native))
        for group in attrs.get('HidingGroups','').split():
            if group not in catalog.groups:
                findings.append(finding('missing_hiding_group','Referenced hiding group is not defined.',[identity],'error',group=group))
            elif not 0 <= catalog.groups[group]['index'] < 8:
                findings.append(finding('invalid_hiding_bit','Hiding-group index cannot be represented by the vertex alpha byte.',[identity],'error',group=group))
        for element in part['elements']:
            region, layer = element.get('EquipmentPart'),element.get('BodyLayerId')
            slots.setdefault((region,layer),[]).append(identity)
            native=catalog.native_roles.get(role)
            native_default=layer is None and native and (region,None) in native['layers']
            if (layer is None and not native_default) or (layer is not None and not str(layer).isdigit()):
                findings.append(finding('unresolved_layer','Body layer did not resolve through component inheritance.',[identity],'error',region=region))
            if native_default and geometry:
                findings.append(finding('native_default_layer','The native template leaves this part unnumbered; numeric layer-order geometry tests are not applied.',[identity],region=region))
            if native and (region,layer) not in native['layers']:
                findings.append(finding('native_layer_difference','The converted part/layer differs from its native role template; inspect replacement behaviour.',[identity],region=region,layer=layer,native_layers=native['layers']))
            if part['kind']=='Clothing' and element.get('KeepBodyLayer','false') != 'true':
                findings.append(finding('body_layer_replacement','This element can replace the body region beneath it; check exposed skin.',[identity],region=region))
            name = element.get('ModelResolved','')
            if lod: name = name.removesuffix('.skin')+'_lod'+str(lod)+'.skin'
            try:
                mesh = catalog.mesh(name)
                if not np.isfinite(mesh.vertices).all() or np.any(mesh.faces < 0) or np.any(mesh.faces >= mesh.n):
                    raise ValueError('Non-finite vertices or indices outside mesh')
                alpha = np.frombuffer(mesh.streams[3].data[24:],np.uint8).reshape(-1,4)[:,3]
                hidden = ((255 ^ alpha) & masks.get(region,0)) != 0
                if body_replaced(catalog,selected,part,element):hidden[:]=True
                materials = catalog.materials(element.get('MaterialResolved'))
                for subset in mesh.info['subset_records']:
                    if subset['material_id'] >= len(materials): raise ValueError('Material slot outside material table')
                for material in materials:
                    if material['texture'] and material['texture'].lower().replace('\\','/') not in catalog.assets.index:
                        raise ValueError('Missing diffuse texture: '+material['texture'])
                meshes.append((identity,element,mesh,hidden,materials))
            except (OSError,ValueError,KeyError) as exc:
                findings.append(finding('asset_error',str(exc),[identity],'error',asset=name,lod=lod))
    for (region,layer), identities in slots.items():
        if len(set(identities)) > 1:
            findings.append(finding('same_layer_overlap','Multiple components occupy the same equipment part and layer.',identities,'error',region=region,layer=layer))
    for role, identities in roles.items():
        if len(identities)>1:
            findings.append(finding('shared_armor_archetype','Multiple garments use one native equipment archetype. Check native equip replacement.',identities,archetype=role))
    if len(families)>1 and any(catalog.parts[i]['attributes'].get('HidingGroups') for i in selected):
        findings.append(finding('cross_outfit_masks','This combination mixes outfit-specific hiding masks; matching bit numbers do not prove compatible coverage.',selected))
    stats = [dict(component=i, model=e.get('ModelResolved'), vertices=m.n, hidden_vertices=int(h.sum()),
                  visible_triangles=int((~h[m.faces].any(axis=1)).sum())) for i,e,m,h,_ in meshes]
    if geometry:
        covers = []
        for identity,element,mesh,hidden,materials in meshes:
            if catalog.parts[identity]['kind'] != 'Clothing': continue
            try:
                surfaces=[]
                for mat in materials:
                    if mat.get('shader','').lower()=='nodraw':
                        surfaces.append((0,[np.zeros((1,1))]));continue
                    if not mat['texture']: raise ValueError('No alpha texture; geometry coverage is unverified')
                    pixels,_ = catalog.assets.pixels(mat['texture'])
                    surfaces.append((mat['threshold'],[pixels[:,:,3]]))
                visible = ~hidden[mesh.faces].any(axis=1)
                accept = alpha_intersections(mesh,surfaces,visible)
                covers.append((identity,element,Surface(mesh.vertices[mesh.faces[visible]],accept)))
            except (ValueError,OSError,KeyError) as exc:
                findings.append(finding('opacity_unverified',str(exc),[identity],'error'))
        for identity,element,mesh,hidden,_ in meshes:
            if catalog.parts[identity]['kind'] != 'Body': continue
            region = element.get('EquipmentPart'); covered = np.zeros(mesh.n,bool)
            directions=normals(mesh)
            for other,cover_element,surface in covers:
                # Female torso meshes can span arms and legs; spatial rays decide coverage.
                covered |= surface.covers(mesh.vertices,directions)
                inside=np.zeros(mesh.n,bool)
                if (~hidden).any():inside[~hidden]=surface.covers(mesh.vertices[~hidden],directions[~hidden],inward=.025,outward=0)
                if inside.any(): findings.append(finding('cloth_under_visible_skin','Garment intersects inward normal segments of visible skin.',[identity,other],vertices=int(inside.sum()),inward_metres=.025))
            exposed = hidden & ~covered
            if exposed.any():
                findings.append(finding('hidden_skin_without_cover','Body vertices are hidden without an opaque garment surface along their normal.',[identity],vertices=int(exposed.sum()),sample_vertices=np.flatnonzero(exposed)[:32].tolist(),inward_metres=.06,outward_metres=.12))
        # Layer-on-layer rays expose inverted layering without claiming a cloth simulation.
        for inner,ie,im,ih,_ in meshes:
            if catalog.parts[inner]['kind'] != 'Clothing': continue
            for outer,oe,surface in covers:
                il,ol=ie.get('BodyLayerId'),oe.get('BodyLayerId')
                if not str(il).isdigit() or not str(ol).isdigit():continue
                if ie.get('EquipmentPart') != oe.get('EquipmentPart') or int(il) >= int(ol): continue
                inverted = surface.covers(im.vertices,normals(im),inward=.015,outward=0) & ~ih
                if inverted.any(): findings.append(finding('outer_layer_under_inner','Higher layer intersects inward normal segments of the lower garment.',[inner,outer],vertices=int(inverted.sum()),inward_metres=.015))
    status = 'error' if any(f['severity']=='error' for f in findings) else 'review' if findings else 'checked'
    return dict(status=status,selected=selected,lod=lod,geometry_checked=geometry,findings=findings,meshes=stats,
                native_rules_checked=bool(catalog.native_roles),runtime_verified=False)


def plan(catalog, mode='presets', body=None, gender=None, limit=250, offset=0):
    """Enumerate deterministically; explicit cursor bounds do not imply complete coverage."""
    if not 1 <= limit <= 1000 or offset < 0: raise ValueError('Invalid batch size or cursor')
    if mode=='presets':
        cases = [dict(id=p['id'],label=p['label'],selected=p['parts']) for p in catalog.presets.values() if gender in (None,'All',p['gender'])]
        return dict(total=len(cases),offset=offset,cases=cases[offset:offset+limit],next_offset=min(len(cases),offset+limit))
    if body not in catalog.presets: raise ValueError('Select a character for combination tests')
    preset = catalog.presets[body]
    base = [p for p in preset['parts'] if catalog.parts[p]['kind']!='Clothing']
    garments = sorted(p['id'] for p in catalog.parts.values() if p['kind']=='Clothing' and p['gender']==preset['gender'] and p['attributes'].get('ArmorType'))
    if mode=='singles': total=len(garments); stream=((g,) for g in garments)
    elif mode=='pairs': total=math.comb(len(garments),2); stream=combinations(garments,2)
    elif mode=='layers':
        slots={}
        for g in garments:
            slot=tuple(sorted((e.get('EquipmentPart',''),e.get('BodyLayerId','')) for e in catalog.parts[g]['elements']))
            slots.setdefault(slot,[None]).append(g)
        total=math.prod(map(len,slots.values())); stream=product(*slots.values())
    else: raise ValueError('Unknown combination mode')
    from itertools import islice
    rows=[dict(id=f'{mode}:{offset+i}',label=' + '.join(g for g in group if g) or 'Body only',selected=base+[g for g in group if g])
          for i,group in enumerate(islice(stream,offset,offset+limit))]
    return dict(total=total,offset=offset,cases=rows,next_offset=min(total,offset+len(rows)))
