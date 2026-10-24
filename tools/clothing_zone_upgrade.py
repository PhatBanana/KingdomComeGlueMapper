"""Rebake saved NPC clothing whose colour zones were indexed by the encoded sRGB mask.

Converted materials do not record which legacy material a macro texture came
from, so a texture is only replaced when re-baking a candidate source with the
old (encoded) zone index reproduces the packaged members byte for byte. The
same source is then baked with the decoded index. Anything else is reported
and left alone; repeat runs therefore change nothing.
"""
import re
import struct
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np

from upgrade_map import read

VERSION = 1
SRGB_FORMATS = (72, 75, 78, 99)


def srgb_dds(blob):
    return blob[:4] == b'DDS ' and blob[84:88] == b'DX10' and struct.unpack_from('<I', blob, 128)[0] in SRGB_FORMATS


def textures(material):
    return {t.get('Map'): t.get('File', '').replace('\\', '/') for t in material.findall('Textures/Texture')}


def zone_moves(spec):
    """Distinct (encoded zone, decoded zone) pairs where decoding moves a texel."""
    green = np.asarray(spec.convert('RGB'))[..., 1] / 255
    decoded = np.where(green <= .04045, green / 12.92, ((green + .055) / 1.055) ** 2.4)
    pairs = np.unique(np.stack([np.floor(green * 3.9999), np.floor(decoded * 3.9999)], -1).reshape(-1, 2), axis=0)
    return {(int(a), int(b)) for a, b in pairs if a != b}


def tint(material, zone):
    params = material.find('PublicParams')
    params = params.attrib if params is not None else {}
    keys = (('ColorizingHue', 'ColorizingSaturation', 'ColorizingBrightness') if zone == 0 else
            (f'MaskHue{zone}', f'MaskSaturation{zone}', f'MaskBrightness{zone}'))
    return tuple(float(params.get(k, d)) for k, d in zip(keys, (0, 1, 1)))


def recolours(material, moves):
    """Only a move between differently tinted zones changes the bake."""
    return any(tint(material, a) != tint(material, b) for a, b in moves)


def inputs(material, maps):
    """Everything bake_macro_diffuse reads; equal inputs give equal bakes."""
    return (maps['Diffuse'].lower(), maps['Specular'].lower(), material.get('StringGenMask', ''),
            material.get('Diffuse', '1,1,1'), tuple(tint(material, z) for z in range(4)))


class Actor:
    """One packaged person: its archives, members and an extraction folder."""

    def __init__(self, archives, work):
        # Person archives are near 1 GB; reopening one per member read dominates.
        self.work, self.members, self.open = work, {}, {}
        for path in archives:
            archive = self.open[path] = zipfile.ZipFile(path)
            for name in archive.namelist():
                self.members.setdefault(name.replace('\\', '/').lower(), (path, name))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        for archive in self.open.values(): archive.close()

    def blob(self, name):
        path, entry = self.members[name.lower()]
        return read(self.open[path], entry)

    def family(self, name):
        """{suffix: bytes} for a DDS and its numbered mips, as packaged."""
        key = name.lower()
        return {m[len(key):]: self.blob(m) for m in self.members
                if m == key or re.fullmatch(re.escape(key) + r'\.\d+', m)}

    def image(self, name):
        from npc_effects import read_dds_family
        folder = Path(tempfile.mkdtemp(dir=self.work))
        for suffix, blob in self.family(name).items():
            (folder / ('t.dds' + suffix)).write_bytes(blob)
        return read_dds_family(folder / 't.dds')


def packaged(name, blob):
    """The members the archive writer stores for a generated texture."""
    from texture_streaming import generated_entries
    return {n[len(name):]: b for n, b in generated_entries([(name, blob)])}


def bake(diffuse, material, spec, decoded, work):
    from npc_effects import bake_macro_diffuse, write_float_dds
    spec = spec.copy(); spec.info['srgb'] = decoded
    path = Path(tempfile.mkdtemp(dir=work)) / 'bake.dds'
    write_float_dds(path, bake_macro_diffuse(diffuse, material, spec))
    return path.read_bytes()


def upgrade_actor(actor):
    """Return ({member: bytes}, fixed, unmatched) for one person."""
    candidates = []
    for name in actor.members:
        if not name.endswith('.mtl'): continue
        for material in ET.fromstring(actor.blob(name)).iter('Material'):
            maps = textures(material)
            if ('COLORIZING_WITH_MASK' in material.get('StringGenMask', '') and 'Diffuse' in maps
                    and maps.get('Specular', '').lower() in actor.members
                    and maps['Diffuse'].lower() in actor.members and srgb_dds(actor.blob(maps['Specular']))):
                candidates.append((name, material, maps))
    if not candidates: return {}, [], []
    targets = {}
    for name in actor.members:
        if not name.endswith('.mtl'): continue
        for material in ET.fromstring(actor.blob(name)).iter('Material'):
            maps = textures(material)
            diffuse = maps.get('Diffuse', '')
            if ('%CLOTHING_SYSTEM' in material.get('StringGenMask', '') and '/native_' in diffuse.lower()
                    and diffuse.lower() in actor.members):
                targets.setdefault(diffuse, maps.get('Bumpmap'))
    images, specs, replacements, fixed, used = {}, {}, {}, [], set()
    for target, bump in targets.items():
        installed = None
        for source, material, maps in candidates:
            # The native slot keeps the source normal map, which narrows the search.
            if bump and maps.get('Bumpmap') and maps['Bumpmap'].lower() != bump.lower(): continue
            if maps['Specular'] not in specs:
                spec = actor.image(maps['Specular'])
                specs[maps['Specular']] = (spec, zone_moves(spec))
            spec, moves = specs[maps['Specular']]
            if not recolours(material, moves): continue
            if maps['Diffuse'] not in images: images[maps['Diffuse']] = actor.image(maps['Diffuse'])
            if installed is None: installed = actor.family(target)
            if packaged(target, bake(images[maps['Diffuse']], material, spec, False, actor.work)) != installed:
                continue
            new = packaged(target, bake(images[maps['Diffuse']], material, spec, True, actor.work))
            if sorted(new) != sorted(installed):
                raise ValueError('Rebaked texture changed its mip layout: ' + target)
            replacements.update({target.lower() + s: b for s, b in new.items()})
            fixed.append(dict(texture=target, source=source)); used.add(inputs(material, maps))
            break
    unmatched = [dict(source=source, reason='no packaged texture reproduces from this material')
                 for source, material, maps in candidates
                 if maps['Specular'] in specs and recolours(material, specs[maps['Specular']][1])
                 and inputs(material, maps) not in used]
    return replacements, fixed, list({u['source']: u for u in unmatched}.values())


def fresh_report():
    """A package whose people were baked by this version needs no rebake."""
    return dict(version=VERSION, mode='baked with decoded masks', textures=[], unmatched=[],
                runtime_verified=False)


def apply(package, receipt, notify=lambda *a: None, cancelled=lambda: False):
    """Finalize step: rebake once per package, then keep the recorded report."""
    if receipt.get('clothing_zone_mask', {}).get('version') == VERSION:
        return
    files, report = upgrade(package, notify, cancelled)
    receipt['files'].update(files)
    receipt['clothing_zone_mask'] = report


def upgrade(package, notify=lambda *a: None, cancelled=lambda: False):
    from control_retail_package import rewrite_pak
    from setup_campaign import digest
    package = Path(package).resolve()
    families = {}
    for path in sorted((package / 'Data').glob('gm_person_*.pak')):
        match = re.fullmatch(r'(gm_person_[0-9a-f]+)(?:_\d+)?\.pak', path.name)
        if match: families.setdefault(match[1], []).append(path)
    changed, report = {}, dict(version=VERSION, scanned=len(families), textures=[], unmatched=[],
                               runtime_verified=False)
    for index, (namespace, archives) in enumerate(families.items()):
        if cancelled(): raise InterruptedError('Cancelled before clothing zone upgrade')
        notify('Rebake two-colour clothing zones', index, len(families), namespace)
        with tempfile.TemporaryDirectory(prefix='zone-upgrade-', dir=package.parent) as temporary:
            with Actor(archives, Path(temporary)) as actor:
                replacements, fixed, unmatched = upgrade_actor(actor)
            report['unmatched'] += [dict(namespace=namespace, **u) for u in unmatched]
            if not replacements: continue
            by_archive = {}
            for name, blob in replacements.items():
                path, entry = actor.members[name]
                by_archive.setdefault(path, {})[entry] = blob
            for path, entries in by_archive.items():
                rewrite_pak(path, entries)
                with zipfile.ZipFile(path) as check:
                    if check.testzip() is not None: raise ValueError('Invalid upgraded actor archive: ' + path.name)
                changed['Data/' + path.name] = digest(path)
            report['textures'] += [dict(namespace=namespace, **f) for f in fixed]
    return changed, report
