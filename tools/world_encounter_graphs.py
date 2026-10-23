"""Select portable native encounters and copy their lexical dependency closure.

The engine owns event selection, difficulty, cooldowns, spawning and cleanup.
This adapter removes campaign-specific variants; it never marks native quests
complete or substitutes a destination region for the converted world.
"""
import copy
import hashlib
import posixpath as P
import xml.etree.ElementTree as E

from upgrade_map import read, xml

BASE = 'quests/final/barbora/'
ROOT = BASE + 'random_events.xml'
DEST = 'Quests/GlueTravel/encounters/random_events.xml'
VARIANTS = {
    'pocestny': ('drunkard', 'death', 'lost_meaning_of_life'),
    'prepadeniNaCeste': ('attack_on_sight_bandits', 'attack_on_sight_cumans'),
}


def module(name, tag='Gameplay', **attributes):
    root = E.Element('Database', Name='brambora')
    host = E.SubElement(E.SubElement(root, 'Skald'), tag, Name=name, **attributes)
    E.SubElement(host, 'Definitions'); E.SubElement(host, 'Nodes')
    return root


class Graphs:
    """Resolve native symbols before relocation, including lexical libraries."""
    def __init__(self, archive):
        self.archive = archive
        self.index = {n.replace('\\', '/').lower(): n for n in archive.namelist()}
        self.original = {}; self.overrides = {}; self.selected = {}; self.exports = {}
        self.full = set()
        self.hashes = {}

    def get(self, path):
        path = path.lower()
        if path not in self.original:
            data = read(self.archive, self.index[path])
            self.original[path] = E.fromstring(data)
            self.hashes[path] = hashlib.sha256(data).hexdigest()
        return self.overrides.get(path, self.original[path])

    def definitions(self, path):
        return {self.get(child).find('Skald')[0].get('Name'): child
                for d in self.get(path).findall('.//Skald/*/Definitions/Definition')
                for child in [P.normpath(P.join(P.dirname(path), d.get('File'))).lower()]}

    def scope(self, path):
        """Native modules inherit the enclosing source module's symbols."""
        scopes = []
        while path.startswith(BASE):
            if path in self.index or path in self.overrides: scopes.append(path)
            path = P.dirname(path) + '.xml'
        scopes.append(BASE.rstrip('/')+'.xml')
        return scopes

    def resolve(self, path, node):
        scopes = self.scope(path)
        namespace = node.get('Namespace', '')
        for part in namespace.split('.') if namespace else ():
            target = next((self.definitions(p)[part] for p in scopes if part in self.definitions(p)), None)
            if target is None: raise ValueError(f'Unresolved encounter namespace {namespace} in {path}')
            scopes = [target]
        return next(((p, self.definitions(p)[node.tag]) for p in scopes if node.tag in self.definitions(p)), None)

    def include(self, path, *, shell=False):
        path = path.lower()
        if path in self.selected and (shell or path in self.full): return
        previous = self.selected.get(path)
        root = copy.deepcopy(self.get(path)); host = root.find('Skald')[0]
        if shell or (host.tag == 'Library' and not host.get('Name','').startswith('event_')):
            host.find('Nodes').clear()
            if shell and host.tag == 'RandomEventVariant':
                # A namespace used only for its helper library must not become
                # an empty selectable encounter variant.
                host.tag = 'Module'
                host.attrib = {'Name':host.get('Name')}
                for section in ('NpcGroups',):
                    n=host.find(section)
                    if n is not None: host.remove(n)
        # A dependency may first introduce its owner's namespace, then later
        # require that owner's executable graph. Promote it regardless of the
        # order in which native nodes reference it.
        if previous is not None:
            names = {n.get('Name') for n in host.findall('Nodes/*')}
            for node in previous.findall('Skald/*/Nodes/*'):
                if node.get('Name') not in names:
                    host.find('Nodes').append(copy.deepcopy(node))
        self.selected[path] = root
        if not shell: self.full.add(path)
        for node in list(host.findall('Nodes/*')):
            dependency = self.resolve(path, node)
            if dependency:
                owner, target = dependency
                self.export(owner, target)

    def export(self, owner, target, *, shell=False):
        if target == ROOT: return
        original_owner = owner
        if owner == BASE.rstrip('/')+'.xml': owner = ROOT
        if target in self.exports.setdefault(owner, set()):
            self.include(target, shell=shell)
            return
        self.exports[owner].add(target)
        if owner not in self.selected: self.include(owner, shell=True)
        # Libraries declare shared/static instances as well as their types.
        original = self.get(original_owner).find('Skald')[0]
        host = self.selected[owner].find('Skald')[0]
        symbol = self.get(target).find('Skald')[0].get('Name')
        for node in original.findall('Nodes/'+symbol):
            if host.find("Nodes/*[@Name='"+node.get('Name')+"']") is None:
                clone = copy.deepcopy(node); host.find('Nodes').append(clone)
                for edge in clone.findall('Edge'):
                    if shell:
                        clone.remove(edge)
                        continue
                    # Side-effect roots require an explicit adapter, not a shell.
                    if edge.get('From','').split('.')[0] not in {n.get('Name') for n in host.findall('Nodes/*')+host.findall('Ports/*')}:
                        raise ValueError('Native library instance needs an unselected state: '+owner)
        self.include(target, shell=shell)
        # Make nested namespace libraries reachable from their native parents.
        parent = P.dirname(owner) + '.xml'
        if parent in self.index:
            if owner in self.definitions(parent).values(): self.export(parent, owner, shell=True)

    def finish(self):
        paths = {p: (DEST if p == ROOT else P.dirname(DEST)+'/native/'+hashlib.sha256(p.encode()).hexdigest()[:24]+'.xml') for p in self.selected}
        output = {}
        for path, root in self.selected.items():
            host = root.find('Skald')[0]; definitions = host.find('Definitions')
            for tag in ('EventInitiatedFastTravelData','PlayerInitiatedFastTravelData'):
                for data in list(host.findall(tag)): host.remove(data)
            if definitions is None: definitions = E.SubElement(host, 'Definitions')
            definitions.clear()
            for child in sorted(self.exports.get(path, ())):
                E.SubElement(definitions, 'Definition', File=P.relpath(paths[child], P.dirname(paths[path])))
            output[paths[path]] = xml(root)
        return output, paths


def keep_nodes(root, names):
    host = root.find('Skald')[0]; nodes = host.find('Nodes')
    removed = {n.get('Name') for n in nodes if n.get('Name') not in names}
    for n in list(nodes):
        if n.get('Name') in removed: nodes.remove(n)
    for n in nodes:
        for edge in list(n.findall('Edge')):
            if edge.get('From','').split('.')[0] in removed: n.remove(edge)
    return root


def prepare(scripts):
    g = Graphs(scripts)
    root = copy.deepcopy(g.get(ROOT)); host = root.find('Skald')[0]
    keep_nodes(root, {'pocestny', 'prepadeniNaCeste', 'events_common'})
    for node in host.findall('Nodes/*'):
        for edge in list(node.findall('Edge')): node.remove(edge)
    host.remove(host.find('Ports'))
    g.overrides[ROOT] = root
    # Keep the native one-shot traveller state and its output feedback.
    path = BASE+'random_events/pocestny.xml'
    root = copy.deepcopy(g.get(path))
    keep_nodes(root, {'event_pocestny', 'Drunkard', 'Death', 'LostMeaningOfLife'})
    event = root.find(".//Nodes/event_pocestny")
    for e in list(event):
        if e.tag == 'Edge' and e.get('To') not in ('drunkard_is_enabled','death_is_enabled','lostmeaningoflife_is_enabled'): event.remove(e)
    g.overrides[path] = root
    # The generic attack-on-sight branch has no campaign activation inputs.
    path = BASE+'random_events/prepadeninaceste.xml'
    root = copy.deepcopy(g.get(path)); keep_nodes(root, {'event_prepadeniNaCeste'})
    root.find('.//Nodes/event_prepadeniNaCeste').clear()
    root.find('.//Nodes/event_prepadeniNaCeste').set('Name','event_prepadeniNaCeste')
    g.overrides[path] = root
    for family, variants in VARIANTS.items():
        path = (BASE+'random_events/'+family+'/event_'+family+'/'+family+'.xml').lower()
        root = copy.deepcopy(g.get(path)); m = root.find('Skald')[0]
        if family == 'pocestny':
            keep_nodes(root, set(variants) | {'pocestny_lib','eventnpcs_contexts','generic_cooldown_trigger',
                'reconcileeventreputation','ifnot12','not13','and11','isinactorstate7','not9','Output'})
            out = m.find('Nodes/Output')
            for edge in list(out):
                if edge.get('From','').split('.')[0] not in set(variants)|{'not9','generic_cooldown_trigger'}: out.remove(edge)
        else:
            keep_nodes(root, {'attack_on_sight','Output'})
            for edge in list(m.find('Nodes/Output')):
                if edge.get('To')!='IsEnabled': m.find('Nodes/Output').remove(edge)
            branch = path[:-4]+'/attack_on_sight.xml'
            r = copy.deepcopy(g.get(branch))
            keep_nodes(r, set(variants)|{'IsSpawned','disablerandomevent2','switch_look_around'})
            g.overrides[branch] = r
        g.overrides[path] = root
    # Optional authored daycycles refer to native towns. The portable variant
    # retains the native look-around, dialogue, timers and leave-level activity.
    path = BASE+'random_events/pocestny/event_pocestny/pocestny/pocestny_lib/pocestny_logic.xml'
    root = copy.deepcopy(g.get(path));m=root.find('Skald')[0]
    for n in list(m.findall('Nodes/SchedulerLinkActivation')): m.find('Nodes').remove(n)
    g.overrides[path]=root
    g.include(ROOT)
    graphs, paths = g.finish()
    return graphs, dict(native_dependencies={p:g.hashes[p] for p in g.selected},
        variants=VARIANTS, native_paths=paths, runtime_verified=False)
