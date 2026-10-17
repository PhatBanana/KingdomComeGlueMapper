"""On-disk cache of building blend bakes, filled in parallel before the serial world build.

Enabled by GLUEMAPPER_BLEND_CACHE (a directory). A bake depends only on the material XML after the
importer's preprocessing, the mesh bytes and the bake code, so those form the key. Entries store
the converted geometry, baked textures and the material XML as convert() left it, with the target
name replaced by a placeholder, or the error a bake raised. Without the variable nothing changes.
"""
import hashlib
import json
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

PLACEHOLDER = '@TARGET@'
SOURCES = ('building_materials.py', 'building_blend.py', 'building_blend_mesh.py')
_code = None


def directory():
    value = os.environ.get('GLUEMAPPER_BLEND_CACHE')
    return Path(value) if value else None


def key(name, doc, geometry):
    global _code
    if _code is None:
        here = Path(__file__).parent
        _code = hashlib.sha256(b''.join((here/s).read_bytes() for s in SOURCES)).digest()
    digest = hashlib.sha256(_code)
    for part in (name.encode(), ET.tostring(doc), geometry or b''):
        digest.update(len(part).to_bytes(8, 'little')); digest.update(part)
    return digest.hexdigest()


def _replace(doc, source):
    doc.attrib.clear(); doc.attrib.update(source.attrib)
    doc[:] = list(source); doc.text, doc.tail = source.text, source.tail


def cached_convert(convert, name, doc, geometry, target, asset_read, index):
    """convert(doc, geometry, target, asset_read, index) through the cache, when enabled."""
    root = directory()
    if root is None:
        return convert(doc, geometry, target, asset_read, index)
    digest = key(name, doc, geometry)
    entry = root/digest[:2]/digest
    meta = entry/'meta.json'
    if meta.is_file():
        info = json.loads(meta.read_text(encoding='utf-8'))
        if 'error' in info:
            raise ValueError(info['error'])
        _replace(doc, ET.fromstring((entry/'material.xml').read_text(encoding='utf-8').replace(PLACEHOLDER, target)))
        baked = {suffix.replace(PLACEHOLDER, target): (entry/f'tex{i}.dds').read_bytes()
                 for i, suffix in enumerate(info['textures'])}
        return (entry/'geometry.bin').read_bytes(), baked
    failure = None
    try:
        converted, baked = convert(doc, geometry, target, asset_read, index)
        info = {'textures': [n.replace(target, PLACEHOLDER) for n in baked]}
    except ValueError as error:
        converted, baked, info, failure = None, {}, {'error': str(error)}, error
    entry.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=digest[:16]+'-', dir=entry.parent))
    try:
        if failure is None:
            (staging/'geometry.bin').write_bytes(converted)
            (staging/'material.xml').write_text(ET.tostring(doc, encoding='unicode').replace(target, PLACEHOLDER), encoding='utf-8')
            for i, payload in enumerate(baked.values()):
                (staging/f'tex{i}.dds').write_bytes(payload)
        (staging/'meta.json').write_text(json.dumps(info), encoding='utf-8')
        try:
            staging.rename(entry)
        except OSError:
            pass  # Another worker stored the same bake first; entries are identical.
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    if failure is not None:
        raise failure
    return converted, baked
