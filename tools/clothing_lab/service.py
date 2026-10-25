"""Desktop and CLI orchestration. Reports are independent of install receipts."""
from datetime import datetime, timezone
import json
from pathlib import Path
import threading

from .catalog import Catalog
from .source import soul_records
from .validation import plan, validate


class Lab:
    def __init__(self, reports):
        self.reports = Path(reports)
        self.catalog = None
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.worker = None
        self.progress = dict(running=False,done=0,total=0,results=[])

    def open(self, package, target, overlay=None):
        with self.lock:
            if self.worker and self.worker.is_alive(): raise ValueError('Stop the clothing audit before changing packages')
            candidate = Catalog(package,target or None,overlay or None)
            self.catalog = candidate
            self.progress = dict(running=False,done=0,total=0,results=[])
            return candidate.summary()

    def run(self, options):
        with self.lock:
            if not self.catalog: raise ValueError('Open a clothing package first')
            if self.worker and self.worker.is_alive(): raise ValueError('Clothing audit is already running')
            self.cancelled.clear()
            self.progress = dict(running=True,done=0,total=0,results=[],message='Preparing cases…')
            self.worker = threading.Thread(target=self._run,args=(dict(options),),daemon=True)
            self.worker.start()
        return dict(started=True)

    def _run(self, options):
        result = dict(schema=1,package=str(self.catalog.assets.root),signature=self.catalog.assets.signature(),catalog_errors=self.catalog.errors,
                      overlay=str(self.catalog.assets.overlay) if getattr(self.catalog.assets,'overlay',None) else None,
                      options=options,rule_evidence=self.catalog.rule_evidence,runtime_verified=False,results=[],
                      limitations=['Bind-pose mesh and diffuse-alpha diagnostics; no native cloth simulation or gameplay execution.',
                                   'Normal-ray intersections are candidates for review, not proof of a visual defect.',
                                   'Soul coverage includes shared source database rows; per-instance world overrides need native testing.'])
        try:
            mode=options.get('mode','presets')
            if mode=='souls':
                cases=soul_records(Path(options['source']),self.catalog)
                result['source_records']=len(cases)
                result['enumeration']=dict(total=len(cases),offset=0,next_offset=len(cases))
            else:
                enumeration=plan(self.catalog,mode,options.get('body'),options.get('gender'),int(options.get('limit',250)),int(options.get('offset',0)))
                cases=enumeration.pop('cases'); result['enumeration']=enumeration
            with self.lock: self.progress.update(total=len(cases),message='Checking clothing…')
            cache={}
            for case in cases:
                if self.cancelled.is_set(): break
                if not case.get('selected'):
                    row=dict(case,findings=[],runtime_verified=False)
                else:
                    key=tuple(case['selected'])
                    if key not in cache:
                        try: cache[key]=validate(self.catalog,case['selected'],bool(options.get('geometry')),int(options.get('lod',0)))
                        except Exception as exc: cache[key]=dict(status='error',findings=[dict(code='validation_error',severity='error',message=str(exc))])
                    row=dict(case,**{k:v for k,v in cache[key].items() if k!='selected'})
                    if case.get('source_issues'):
                        row['findings']=list(row['findings'])+[dict(code='source_error',severity='error',message=issue)
                                                               for issue in case['source_issues']]
                        row['status']='source_error'
                result['results'].append(row)
                with self.lock:
                    self.progress.update(done=len(result['results']),message=case['label'])
                    self.progress['results'].append(dict(id=case['id'],label=case['label'],status=row['status'],selected=case.get('selected',[]),findings=row.get('findings',[])))
            result['cancelled']=self.cancelled.is_set()
            result['enumeration_complete']=not result['cancelled'] and len(result['results'])==result['enumeration']['total'] and result['enumeration']['offset']==0
            result['complete']=result['enumeration_complete'] and not self.catalog.errors and all(r['status']=='checked' for r in result['results'])
            result['counts']={status:sum(r['status']==status for r in result['results']) for status in sorted({r['status'] for r in result['results']})}
            self.reports.mkdir(parents=True,exist_ok=True)
            path=self.reports/(datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'.json')
            path.write_text(json.dumps(result,indent=2),encoding='utf-8')
            with self.lock: self.progress.update(report=str(path),counts=result['counts'],enumeration=result['enumeration'],cancelled=result['cancelled'])
        except Exception as exc:
            with self.lock: self.progress['error']=str(exc)
        finally:
            with self.lock: self.progress['running']=False

    def poll(self, offset=0):
        with self.lock:
            return dict(self.progress,results=self.progress['results'][max(0,int(offset)):max(0,int(offset))+200])

    def cancel(self):
        self.cancelled.set()
        return True
