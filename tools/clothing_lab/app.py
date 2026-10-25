"""Standalone developer workbench, deliberately separate from consumer Setup."""
import argparse
import base64
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path

from PIL import Image
from .service import Lab
from .validation import validate


class API:
    def __init__(self, package='', source='', target='', reports=Path('reports/clothing-lab'), overlay=''):
        self.lab=Lab(reports)
        self.defaults=dict(package=str(package),source=str(source),target=str(target),overlay=str(overlay))

    def clothing_locations(self):
        from steam_installations import discover
        found,_=discover()
        for field,game in (('source','kcd1'),('target','kcd2')):
            if not self.defaults[field]: self.defaults[field]=next(iter(found[game]),'')
        if not self.defaults['package'] and self.defaults['target']:
            self.defaults['package']=str(Path(self.defaults['target'])/'Mods/kingdomcomegluemapper')
        return self.defaults

    def clothing_open(self,package,target,overlay=''):return self.lab.open(package,target,overlay)

    def clothing_scene(self,selected,lod=0):
        if self.lab.catalog is None:raise ValueError('Open a package first')
        return dict(scene=self.lab.catalog.scene(selected,int(lod)),
                    validation=validate(self.lab.catalog,selected,False,int(lod)))

    def clothing_run(self,options):return self.lab.run(options)

    def clothing_poll(self,offset=0):return self.lab.poll(offset)

    def clothing_cancel(self):return self.lab.cancel()

    def clothing_capture(self,selected,lod,image,view):
        if not self.lab.catalog:raise ValueError('Open a package first')
        if len(image)>24_000_000 or not image.startswith('data:image/png;base64,'):raise ValueError('Expected a bounded PNG capture')
        data=base64.b64decode(image.split(',',1)[1],validate=True)
        with Image.open(io.BytesIO(data)) as check:
            if check.format!='PNG' or check.width*check.height>16_000_000:raise ValueError('Invalid capture dimensions')
            check.verify()
        path=self.lab.reports/(datetime.now(timezone.utc).strftime('view-%Y%m%d-%H%M%S-%f')+'.png')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        report=dict(package=str(self.lab.catalog.assets.root),signature=self.lab.catalog.assets.signature(),view=view,
                    validation=validate(self.lab.catalog,selected,False,int(lod)),runtime_verified=False)
        path.with_suffix('.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        return str(path)

    def clothing_reports(self):
        self.lab.reports.mkdir(parents=True,exist_ok=True)
        os.startfile(str(self.lab.reports.resolve()))
        return str(self.lab.reports)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',default='');parser.add_argument('--source',default='');parser.add_argument('--target',default='')
    parser.add_argument('--overlay',default='')
    parser.add_argument('--reports',type=Path,default=Path(__file__).resolve().parents[2]/'reports/clothing-lab')
    args=parser.parse_args()
    import webview
    api=API(**vars(args))
    window=webview.create_window('KingdomComeGlueMapper Tools · Clothing & Body Test',
        str(Path(__file__).with_name('ui')/'index.html'),js_api=api,width=1440,height=1000,min_size=(980,720),background_color='#151719')
    def closing():
        if api.lab.worker and api.lab.worker.is_alive():
            api.lab.cancel()
            window.evaluate_js("document.querySelector('#lab-progress').textContent='Stopping the audit and saving completed findings. Close again when the report is ready.'")
            return False
        return True
    window.events.closing+=closing
    webview.start(gui='edgechromium',debug=False)


if __name__=='__main__':main()
