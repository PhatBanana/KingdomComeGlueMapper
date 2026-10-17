import hashlib
import json
import zipfile

from setup_shaders import ARCHIVES, PREFIX, REPAIRS, ILLUM_REPAIRS, patched, digest


def package_shaders(package):
    engine = package/'Engine'; engine.mkdir(exist_ok=True)
    sources = {'Illum.cfx': b'\n'.join(pair[0] for pair in ILLUM_REPAIRS)}
    sources.update({name: pair[0] for name, pair in REPAIRS.items()})
    sources = {PREFIX+n: patched(n,b) for n,b in sources.items()}
    for name in ARCHIVES:
        with zipfile.ZipFile(engine/name, 'w') as z:
            for path, blob in (sources if name=='Shaders.pak' else {'cache.bin': b'compiled'}).items():
                z.writestr(path, blob)
    report = dict(compiled=True, compilation={'compiled': 1}, source=hashlib.sha256(b'native shaders').hexdigest(),
                  files={'Engine/'+n: digest(engine/n) for n in ARCHIVES},
                  changes={n:hashlib.sha256(b).hexdigest() for n,b in sources.items()})
    (package/'shader-build.json').write_text(json.dumps(report))
    return [*report['files'], 'shader-build.json']
