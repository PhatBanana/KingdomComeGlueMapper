"""Local WebView2 host. The HTML UI calls a narrow native API; no remote content."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
import shutil

from setup_mods import CATALOG, checked_config, preflight
from desktop_setup import APP_VERSION
from steam_installations import discover
from setup_launch import launch as launch_map

def planned_steps(config):
    """Selected operations in execution order, before any work starts."""
    from desktop_setup import conversion_plan
    from build_recipe import STAGE_LABELS
    from setup_baking import PRESETS
    labels=[]
    if 'map' in config['mods']:
        if config['action']!='install':
            labels.extend(row[0] for row in conversion_plan('.', '.'))
            labels.extend(['Package converted world','Build coach travel, arrivals and Rattay services','Combine and verify one complete mod'])
            labels.extend(STAGE_LABELS)
            if config.get('cutscenes')=='opening':labels.append('Convert and package KCD1 opening movie')
            if config.get('baking','none')!='none':labels.append('KCD1 Map · '+PRESETS[config['baking']]+' lighting bake')
        if config['action']!='build_only':labels.append('Install and verify KCD1 Map' if config['action']!='install' else 'Install verified mod')
    if 'fishing' in config['mods']:labels.append('KCD2 Fishing')
    return labels


CONVERTER_FILTER = ('RAD Video Tools (*.exe)',)
CONVERTER_NAMES = ('radvideo64.exe', 'radvideo32.exe', 'radvideo.exe')


def converter_info(path):
    path = Path(path).resolve()
    if path.name.lower() not in CONVERTER_NAMES:
        raise ValueError('Choose radvideo64.exe, radvideo32.exe or radvideo.exe from RAD Video Tools.')
    with path.open('rb') as stream:
        if stream.read(2) != b'MZ':
            raise ValueError('The selected converter is not a Windows executable.')
    return dict(path=str(path), message='Converter found. No download needed. Select the opening movie option to convert and install it.')


class SetupAPI:
    def __init__(self):
        self._window=None;self._process=None;self._job=None;self._lock=threading.Lock()
        self._offsets={};self._terminal=False;self._launching=False
        self._settings=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'KingdomComeGlueMapper'/'setup-settings.json'

    def state(self):
        found,warnings=discover()
        defaults=dict(kcd1=next(iter(found['kcd1']),''),kcd2=next(iter(found['kcd2']),''),
            mod_tools=next(iter(found.get('mod_tools',[])),''),
            workspace=str(self._settings.parent/'builds'),package='',action='build_install',mods=['map'],baking='none',cutscenes='none',converter='',rebuild_cache=False)
        try:defaults.update({k:v for k,v in json.loads(self._settings.read_text()).items() if k in defaults})
        except (OSError,ValueError,TypeError):pass
        defaults['rebuild_cache']=False  # A regeneration request applies to one new build.
        installed=[]
        for item in CATALOG:
            if (Path(defaults['kcd2'])/'Mods'/item['modid']/'mod.manifest').is_file():installed.append(item['id'])
        return dict(config=defaults,catalog=CATALOG,installed=installed,warnings=warnings,version=APP_VERSION,busy=self._busy(),converter=self.find_converter())

    def _remember_converter(self, info):
        self._settings.parent.mkdir(parents=True, exist_ok=True)
        self._settings.with_name('converter.json').write_text(json.dumps(info, indent=2), encoding='utf-8')

    def find_converter(self):
        candidates=[]
        try:
            candidates.append(Path(json.loads(self._settings.with_name('converter.json').read_text())['path']))
        except (OSError, ValueError, TypeError, KeyError): pass
        for name in CONVERTER_NAMES:
            found=shutil.which(name)
            if found:candidates.append(Path(found))
        folders=[]
        for key in ('ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA'):
            if os.environ.get(key):
                root=Path(os.environ[key])
                folders.extend(root / sub for sub in ('RADVideo','RAD Video Tools','Programs/RADVideo','Programs/RAD Video Tools'))
        # Local development/portable installs remain external to the EXE.
        bases=[Path(sys.executable).resolve().parent, Path(__file__).resolve().parent, Path.cwd()]
        for base in bases:
            for root in [base, *list(base.parents)[:3]]:
                folders.extend((root/'.deps/rad-video-tools/portable',root/'rad-video-tools/portable'))
        candidates.extend(folder/name for folder in folders for name in CONVERTER_NAMES)
        for path in dict.fromkeys(candidates):
            try:info=converter_info(path)
            except (OSError,ValueError):continue
            self._remember_converter(info)
            return info
        return None

    def _busy(self):return self._launching or (self._process is not None and self._process.poll() is None)

    def installed(self,target):
        if not isinstance(target,str) or not target.strip():return []
        return [i['id'] for i in CATALOG if (Path(target)/'Mods'/i['modid']/'mod.manifest').is_file()]

    def launch_mod(self,target):
        with self._lock:
            if self._busy():return dict(ok=False,error='Wait for the current setup operation to finish.')
            self._launching=True
        try:return launch_map(target)
        except (OSError,ValueError,subprocess.SubprocessError) as e:return dict(ok=False,error=str(e))
        finally:
            with self._lock:self._launching=False

    def mod_tools_link(self):
        os.startfile('steam://install/2429020')
        return True

    def check_mod_tools(self,target,selected=''):
        from setup_shaders import tool_root
        try:return dict(ok=True,path=str(tool_root(target,selected)))
        except (OSError,ValueError) as e:return dict(ok=False,error=str(e))

    def browse(self,field):
        if field not in ('kcd1','kcd2','mod_tools','workspace','package') or self._busy():return None
        import webview
        result=self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None

    def detect(self):
        found,warnings=discover();return dict(found=found,warnings=warnings)

    def converter_link(self):
        import webbrowser
        return webbrowser.open('https://www.radgametools.com/bnkdown.htm')

    def locate_converter(self):
        import webview
        result=self._window.create_file_dialog(webview.FileDialog.OPEN,file_types=CONVERTER_FILTER)
        if not result:return None
        info=converter_info(result[0])
        self._remember_converter(info)
        return info

    def check(self,config):
        try:return preflight(config)
        except (OSError,ValueError,KeyError,TypeError) as e:return dict(ok=False,error=str(e))

    def cache_candidates(self,workspace,preset):
        from setup_cache_import import candidates
        return candidates(workspace,preset)

    def import_old_cache(self,workspace):
        import webview
        from setup_cache_import import import_build
        with self._lock:
            if self._busy():return dict(ok=False,error='Wait for the current setup operation to finish.')
            selected=self._window.create_file_dialog(webview.FileDialog.FOLDER)
            if not selected:return dict(ok=False,cancelled=True)
            self._launching=True
        try:return dict(ok=True,cache=import_build(selected[0],workspace))
        except (OSError,ValueError,KeyError,TypeError) as e:return dict(ok=False,error=str(e))
        finally:
            with self._lock:self._launching=False

    def start(self,config):
        with self._lock:
            if self._busy():return dict(ok=False,error='An installation is already running.')
            try:
                c=preflight(config)['config']
                self._job=Path(c['workspace']).resolve()/(time.strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8])
                self._job.mkdir(parents=True)
                path=self._job/'job.json';path.write_text(json.dumps(c,indent=2))
                self._settings.parent.mkdir(parents=True,exist_ok=True);self._settings.write_text(json.dumps(c,indent=2))
                command=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).with_name('setup_app.py'))]
                self._process=subprocess.Popen([*command,'--mods-worker',str(path)],creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                self._offsets={};self._terminal=False
                return dict(ok=True,job=str(self._job),steps=planned_steps(c))
            except (OSError,ValueError,KeyError,TypeError) as e:return dict(ok=False,error=str(e))

    def poll(self):
        events=[]
        with self._lock:
            if self._job:
                for p in (self._job/'events.jsonl',self._job/'map-job/events.jsonl'):
                    if not p.exists():continue
                    with p.open('rb') as stream:
                        stream.seek(self._offsets.get(str(p),0))
                        while True:
                            position=stream.tell();line=stream.readline()
                            if not line.endswith(b'\n'):stream.seek(position);break
                            e=json.loads(line)
                            if p.parent.name=='map-job':
                                e['mod']='map'
                                if e['kind'] in ('done','error','cancelled'):e['kind']='log'
                            elif e['kind'] in ('done','error','cancelled'):self._terminal=True
                            events.append(e)
                        self._offsets[str(p)]=stream.tell()
                if self._process and not self._busy() and not self._terminal:
                    events.append(dict(kind='error',message=f'Setup stopped (exit {self._process.returncode}). Open the log for details.'));self._terminal=True
        return dict(busy=self._busy(),events=sorted(events,key=lambda e:e.get('time',0)))

    def resume(self):
        """Select a retained job, with its saved options, even after app restart."""
        import webview
        from setup_resume import load_job,job_lock
        with self._lock:
            if self._busy():return dict(ok=False,error='An installation is already running.')
            selected=self._window.create_file_dialog(webview.FileDialog.FOLDER)
            if not selected:return dict(ok=False,cancelled=True)
            try:
                c=load_job(selected[0]);root=Path(c['resume_from'])
                with job_lock(root):
                    attempt=root/('resume-'+time.strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8])
                    attempt.mkdir()
                    path=attempt/'job.json';path.write_text(json.dumps(c,indent=2),encoding='utf-8')
                self._job=attempt
                command=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).with_name('setup_app.py'))]
                self._process=subprocess.Popen([*command,'--mods-worker',str(path)],creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                self._offsets={};self._terminal=False
                labels=planned_steps(c)
                # Verification in the worker is authoritative; show its result
                # before treating the saved package as complete.
                if (root/'package/map').is_dir() and c['action']!='install':
                    remaining=[]
                    if c.get('cutscenes')=='opening':remaining.append('Convert and package KCD1 opening movie')
                    if c.get('baking','none')!='none':
                        from setup_baking import PRESETS
                        remaining.append('KCD1 Map · '+PRESETS[c['baking']]+' lighting bake')
                    remaining.append('Upgrade saved gameplay and keep one playable world')
                    if c['action']!='build_only':remaining.append('Install and verify KCD1 Map')
                    if 'fishing' in c['mods']:remaining.append('KCD2 Fishing')
                    labels=remaining
                return dict(ok=True,job=str(attempt),source=str(root),steps=['Verify saved work',*labels])
            except (OSError,ValueError,KeyError,TypeError) as e:return dict(ok=False,error=str(e))

    def cancel(self):
        if self._job and self._busy():
            (self._job/'cancel.requested').touch()
            child=self._job/'map-job'
            child.mkdir(exist_ok=True)
            (child/'cancel.requested').touch()
        return True

    def open_result(self,kind):
        if kind not in ('folder','log') or not self._job:return False
        path=self._job if kind=='folder' else self._job/'setup.log'
        if path.exists():os.startfile(str(path));return True
        return False


def launch():
    import webview
    from setup_fishing import asset_root
    api=SetupAPI()
    api._window=webview.create_window('KingdomComeGlueMapper Setup',str(asset_root()/'setup-ui/index.html'),
        js_api=api,width=1280,height=900,min_size=(980,720),background_color='#101216',text_select=True)
    def closing():
        if api._busy():
            api._window.evaluate_js("window.showNotice('Setup is running. Cancel safely from Activity before closing.','error')")
            return False
    api._window.events.closing+=closing
    webview.start(gui='edgechromium',debug=False)
