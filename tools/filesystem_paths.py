"""Local filesystem paths that work without Windows' long-path policy enabled.

Use at staging roots, so descendants and cleanup retain the extended prefix.
These paths must not be used as virtual asset names inside game archives.
"""
import os
from pathlib import Path
import tempfile
import zipfile


def filesystem_path(path):
    path = Path(path).resolve()
    if os.name != 'nt':
        return path
    name = str(path)
    if name.startswith('\\\\?\\'):
        return path
    if name.startswith('\\\\'):
        return Path('\\\\?\\UNC\\' + name[2:])
    return Path('\\\\?\\' + name)


def staging_self_test(parent=None):
    """Exercise write, traversal, packing, rename and cleanup past MAX_PATH."""
    parent = filesystem_path(parent or tempfile.gettempdir())
    with tempfile.TemporaryDirectory(prefix='gm-path-', dir=parent) as temporary:
        root = Path(temporary)
        relative = Path('actors/people') / ('gm_person_' + '4' * 32)
        relative /= Path('objects/characters/gluetravel') / ('gm_person_' + '4' * 32)
        # Keep each component valid while guaranteeing a long total path even
        # when TEMP lives at the drive root.
        relative /= 'nested-stage-' + 'x' * 80
        relative /= 't43_s1_p3_l1_v0_generic_scratches_scratches_spec.dds'
        texture = root / relative
        texture.parent.mkdir(parents=True)
        texture.write_bytes(b'DDS path regression')
        if texture not in root.rglob('*.dds'):
            raise RuntimeError('Long staging path was not traversed')
        archive_path = root / 'actor.pak'
        with zipfile.ZipFile(archive_path, 'w') as archive:
            archive.write(texture, relative.as_posix())
        renamed = texture.with_suffix('.checked')
        texture.replace(renamed)
        with zipfile.ZipFile(archive_path) as archive:
            if archive.read(relative.as_posix()) != renamed.read_bytes():
                raise RuntimeError('Long staging path archive round trip failed')
        length = len(str(texture))
    if root.exists():
        raise RuntimeError('Long staging path cleanup failed')
    return dict(status='passed', path_length=length)
