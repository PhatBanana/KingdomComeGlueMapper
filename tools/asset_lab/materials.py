"""Material (.mtl) and shader-extension (.ext) readers plus the contracts built on them."""
import re
import xml.etree.ElementTree as ET

from . import norm

IMAGE_EXTENSIONS = ('.tif', '.tiff', '.tga', '.png', '.bmp', '.jpg', '.jpeg')
PROPERTY = re.compile(r'Property\s*\{(.*?)\n\s*\}', re.S)
NAME = re.compile(r'^\s*Name\s*=\s*(%\w+)', re.M)
MASK = re.compile(r'^\s*Mask\s*=\s*(0[xX][0-9a-fA-F]+|\d+)', re.M)


HIDE = re.compile(r'^\s*DependencyHide\s*=\s*(.*)$', re.M)


def parse_ext(text):
    """``(masks, hides)`` from a CryEngine shader extension; comments are ignored.

    ``masks`` is ``{'FLAG': mask}`` without the percent sign. ``hides`` maps a flag to
    ``(set_flags, unset_flags)``: the editor hides it when any of the first is set or any
    of the second (written ``!%X``) is not set.
    """
    text = re.sub(r'//[^\n]*', '', text)
    flags, hides = {}, {}
    for body in PROPERTY.findall(text):
        name, mask = NAME.search(body), MASK.search(body)
        if not (name and mask): continue
        flag = name.group(1).upper().lstrip('%')
        flags[flag] = int(mask.group(1), 0)
        hide = HIDE.search(body)
        if hide:
            items = [i.strip() for i in re.split(r'(?<!!)(?=!?%)', hide.group(1)) if i.strip()]
            hides[flag] = (sorted(i.lstrip('%').upper() for i in items if not i.startswith('!')),
                           sorted(i[1:].lstrip('%').upper() for i in items if i.startswith('!')))
    return flags, hides


def hidden_flags(flags, hides):
    """Flags in ``flags`` that the extension's DependencyHide rules would hide."""
    present = set(flags)
    return sorted(f for f in present if f in hides
                  and (any(h in present for h in hides[f][0]) or any(u not in present for u in hides[f][1])))


def shader_key(name):
    return (name or '').lower()


def parse_materials(blob, path=''):
    """Leaf materials as dicts. Raises ``ET.ParseError`` for broken XML."""
    root = ET.fromstring(blob)
    out = []
    for index, node in enumerate(root.iter('Material')):
        has_children = node.find('SubMaterials') is not None
        shader = node.get('Shader')
        if has_children and shader is None: continue
        flags = [f.upper() for f in (node.get('StringGenMask') or '').split('%') if f]
        textures = [(t.get('Map', ''), t.get('File', '')) for t in node.iterfind('./Textures/Texture')]
        out.append(dict(path=path, index=index, name=node.get('Name') or '', shader=shader,
                        genmask=node.get('GenMask'), flags=flags, surface=node.get('SurfaceType'),
                        textures=textures))
    return out


def genmask_value(text):
    if text is None or not text.strip(): return None
    try: return int(text, 16)
    except ValueError: return None


def mask_from_flags(flags, table):
    """Sum of declared masks, or ``None`` when a flag is not in ``table``."""
    total = 0
    for flag in flags:
        if flag not in table: return None
        total |= table[flag]
    return total


def _join(directory, key):
    parts = directory.split('/') if directory else []
    for piece in key.split('/'):
        if piece == '..':
            if parts: parts.pop()
        elif piece not in ('.', ''): parts.append(piece)
    return '/'.join(parts)


def texture_candidates(reference, origin=''):
    """Lower-case archive keys a texture reference may name: root-relative, then next to the material."""
    key = norm(reference)
    if is_builtin(reference): return []
    out = [key]
    directory = norm(origin).rsplit('/', 1)[0] if '/' in norm(origin) else ''
    if origin and (key.startswith('./') or key.startswith('../') or '/' not in key):
        out = [_join(directory, key), key]
    converted = [c[:-len(ext)] + '.dds' for c in out for ext in IMAGE_EXTENSIONS if c.endswith(ext)]
    bare = [c + '.dds' for c in out if '.' not in c.rsplit('/', 1)[-1]]
    return out + converted + bare


def resolve_texture(reference, archives, origin=''):
    for candidate in texture_candidates(reference, origin):
        if candidate in archives.members: return candidate
    return None


def is_builtin(reference):
    """Engine pseudo-references such as ``$WhiteTexture`` or ``nearest_cubemap`` name no file."""
    key = norm(reference)
    return not key or key.startswith('$') or ('/' not in key and '.' not in key)


def is_proxy_name(name):
    name = (name or '').lower()
    return 'proxy' in name and 'shadow' not in name


def is_proxy_texture(reference):
    stem = norm(reference).rsplit('/', 1)[-1].rsplit('.', 1)[0]
    return stem.endswith('collision_proxy')
