"""The Storm program: storm.xml task list, its sources, custom selectors and operations.

``Libs/Storm/storm.xml`` is resolved mod-first, so a mod copy replaces the
native file entirely. Every listed source is resolved mod-first, then native.
A source missing from both layers is recorded: missing native-listed sources
are tolerated (retail lists ``names/quests/predaniVChramu.xml`` which does not
exist), missing sources that only the mod lists are errors.
"""
from collections import defaultdict
import re

from .tables import parse

STORM = 'libs/storm/storm.xml'


class Source:
    def __init__(self, task, path, layer, root):
        self.task, self.path, self.layer, self.root = task, path, layer, root

    @property
    def rules(self):
        return [] if self.root is None else list(self.root.iter('rule'))


class Program:
    def __init__(self, mounts):
        self.mounts = mounts
        self.storm_layer = mounts.where(STORM)
        if self.storm_layer is None:
            raise FileNotFoundError('Libs/Storm/storm.xml is in neither the package nor the install')
        self.root = parse(mounts.read(STORM))
        native_listed = set()
        if self.storm_layer == 'mod' and mounts.where(STORM) and mounts.read(STORM, 'native') is not None:
            native_listed = {self._norm(s.get('path')) for s in parse(mounts.read(STORM, 'native')).iter('source')}
            self.native_storm_sources = native_listed
        else:
            self.native_storm_sources = None
        self.tasks = []           # [(name, [Source])]
        self.missing = []         # dict(path, task, tolerated)
        self.custom_selectors = defaultdict(list)   # name -> [(Source, element)]
        self.custom_operations = defaultdict(list)
        common = self.root.find('common')
        groups = ([('common', common)] if common is not None else []) + \
                 [(t.get('name') or t.get('class') or '?', t) for t in self.root.findall('tasks/task')]
        for name, node in groups:
            sources = []
            for s in node.iter('source'):
                path = self._norm(s.get('path'))
                member = 'libs/storm/' + path
                layer = self.mounts.where(member)
                if layer is None:
                    tolerated = self.storm_layer == 'native' or path in native_listed
                    self.missing.append(dict(task=name, path=path, tolerated=tolerated))
                    continue
                source = Source(name, path, layer, parse(self.mounts.read(member)))
                sources.append(source)
                for c in source.root.iter('customSelector'):
                    self.custom_selectors[c.get('name')].append((source, c))
                for c in source.root.iter('customOperation'):
                    self.custom_operations[c.get('name')].append((source, c))
            self.tasks.append((name, sources))

    @staticmethod
    def _norm(path):
        return re.sub(r'/+', '/', (path or '').replace('\\', '/')).lstrip('/').lower()

    def task(self, name):
        for task, sources in self.tasks:
            if task == name: return sources
        return []

    def inventory(self):
        hidden = None
        if self.native_storm_sources is not None:
            listed = {s.path for _, sources in self.tasks for s in sources} | {m['path'] for m in self.missing}
            # Native sources the mod storm.xml no longer lists: a later retail
            # patch adding sources would be hidden by the replacing mod file.
            hidden = sorted(self.native_storm_sources - listed)
        return dict(storm_xml_layer=self.storm_layer,
                    tasks=[dict(task=t, sources=len(s), mod_sources=sum(x.layer == 'mod' for x in s),
                                rules=sum(len(x.rules) for x in s)) for t, s in self.tasks],
                    missing_sources=self.missing,
                    native_sources_hidden_by_mod_storm_xml=hidden,
                    custom_selectors=len(self.custom_selectors),
                    duplicate_custom_selectors=sorted(n for n, d in self.custom_selectors.items() if len(d) > 1),
                    custom_operations=len(self.custom_operations))
