"""Repair two invalid vector conversions in the supplied dev Illum shader."""
import argparse
from pathlib import Path
import zipfile
from upgrade_map import read

REPAIRS = (
    (b'attribs.Albedo = GetDiffuseTex(diffuseTex, float4(baseTC.xy, 0, 0));',
     b'attribs.Albedo = GetDiffuseTex(diffuseTex, baseTC.xy).rgb;'),
    (b'alpha *= GetDiffuseTex(diffuseTex, float4(baseTC.xy, 0, 0)).w;',
     b'alpha *= GetDiffuseTex(diffuseTex, baseTC.xy).w;'),
)


def repair(source):
    for old,new in REPAIRS:
        if source.count(old)!=1:raise ValueError('Shader source differs from reviewed version')
        source=source.replace(old,new)
    return source


def install(game):
    relative='Shaders/HWScripts/CryFX/Illum.cfx'
    with zipfile.ZipFile(game/'Engine/Shaders.pak') as z:original=read(z,relative)
    fixed=repair(original)
    destination=game/'Engine'/relative
    if destination.exists() and destination.read_bytes() not in (original,fixed):
        raise ValueError('Preserve existing custom Illum shader before installing')
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(fixed)
    assert destination.read_bytes()==fixed
    print('Installed shader source override:',destination)
    print('Bundled archive unchanged. Reload/restart required for shaders already loaded.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--game',type=Path,required=True)
    install(p.parse_args().game)
