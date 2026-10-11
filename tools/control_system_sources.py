"""Discover native editor objects behind world-system links, including prefab ports.

Runtime mission EntityIds are not a complete dependency index: prefab smart
objects can compile into scheduler records without becoming runtime entities.
Use the authored GUID/port ownership here, before the official editor export.
"""
import copy
import json
from pathlib import Path
import xml.etree.ElementTree as ET


class SourceObjects:
    def __init__(self, layers):
        self.objects, self.owners, self.names, self.paths, self.souls = {}, {}, {}, {}, {}
        for path in sorted(Path(layers).rglob('*.lyr')):
            root = ET.parse(path).getroot()
            for soul in root.findall('WHData0/SoulList/Souls/Soul'):
                self.souls[soul.findtext('Name')] = copy.deepcopy(soul)
            for obj in root.findall('Objects/Object'):
                key = obj.get('Id', '').lower()
                if not key: continue
                if key in self.objects: raise ValueError('Duplicate source object: ' + key)
                self.objects[key] = obj
                self.paths[key] = str(path)
                self.names.setdefault(obj.get('Name'), []).append(key)
                self.owners[key] = key
                for member in obj.iter('ObjectGUID'):
                    alias = member.get('Instance', '').lower()
                    if alias: self.owners[alias] = key

    def named(self, name):
        keys = self.names.get(name, [])
        if len(keys) != 1: raise ValueError(f'Expected one native object {name}: {len(keys)}')
        return keys[0]

    def closure(self, seeds, links_for):
        selected, queue, unresolved, edges = set(), list(seeds), [], []
        while queue:
            key = queue.pop()
            if key in selected: continue
            selected.add(key)
            obj = self.objects[key]
            for label, target in links_for(obj):
                target = target.lower()
                owner = self.owners.get(target)
                edges.append(dict(source=key, label=label, target=target, owner=owner))
                if owner is None:
                    unresolved.append(dict(source=obj.get('Name'), label=label, target=target,
                                           file=self.paths[key]))
                elif owner not in selected: queue.append(owner)
        return selected, edges, unresolved


def authored_links(obj):
    for link in obj.findall('EntityLinks/Link'):
        if link.get('TargetId'): yield link.get('Name', ''), link.get('TargetId')
    # Preserve both ends of authored connections across a prefab boundary.
    for link in obj.findall('.//ExternalLinks/Link'):
        for field in ('SourceId', 'TargetId'):
            if link.get(field): yield 'prefab:' + link.get('Name', ''), link.get(field)


def inspect(layers, output):
    index = SourceObjects(layers)
    roots = ('sa_land', 'open_world', 'playerProxy', 'so_player_scheduler',
             'playerHorseDefaultSmartObject', 'PlayerLinkRerouter', 'hangoverSpotsHub')
    selected, edges, missing = index.closure([index.named(n) for n in roots], authored_links)
    report = dict(roots=roots, objects=len(selected), edges=len(edges), unresolved=missing,
                  entities=[dict(index.objects[k].attrib, source=index.paths[k]) for k in sorted(selected)])
    Path(output).write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--layers', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    r = inspect(a.layers, a.output)
    print(json.dumps({k: r[k] for k in ('objects', 'edges', 'unresolved')}, indent=2))
