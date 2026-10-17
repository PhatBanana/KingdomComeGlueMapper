"""Read-only comparison of a reference mod and a clean setup package.

Compare virtual paths across shards, not archive names. CRC/size comparisons
are an inventory check, not a cryptographic or runtime-equivalence guarantee.
Conflicting overrides remain explicit; alphabetical order is not assumed to
be the engine's mount priority. Renamed generated assets require source review.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile


def inventory(root):
    entries = {}
    for path in sorted(root.rglob('*.pak')):
        relative = path.relative_to(root).as_posix()
        parent = path.parent.relative_to(root).as_posix().lower()
        # Root Data PAKs share the Data virtual root; level and localization
        # archives have their own roots and must not collide with each other.
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = parent + '/' + info.filename.replace('\\', '/').lower()
                entries.setdefault(name, []).append(dict(archive=relative,
                    crc=info.CRC, size=info.file_size))
    return entries


def signatures(records):
    return {(r['crc'], r['size']) for r in records}


def actors(root, level):
    path = root / 'Data/Levels' / level / 'level.pak'
    if not path.is_file():
        return {}
    with zipfile.ZipFile(path) as archive:
        names = {n.replace('\\', '/').lower(): n for n in archive.namelist()}
        mission = ET.fromstring(archive.read(names['objects_mission0.xml']))
    return {e.get('EntityGuid').lower(): dict(name=e.get('Name'),
            entity_class=e.get('EntityClass'), position=e.get('Pos'))
            for e in mission.iter('Entity') if e.get('EntityGuid')
            and e.get('EntityClass', '').startswith('NPC')}


def compare(reference, candidate, level='kcd1_travel'):
    reference, candidate = Path(reference).resolve(), Path(candidate).resolve()
    for root in (reference, candidate):
        if not (root / 'mod.manifest').is_file():
            raise ValueError('Not a mod package: ' + str(root))
    old, new = inventory(reference), inventory(candidate)
    missing = {n: old[n] for n in sorted(old.keys() - new.keys())}
    changed = {n: dict(reference=old[n], candidate=new[n])
               for n in sorted(old.keys() & new.keys())
               if signatures(old[n]) != signatures(new[n])}
    before, after = actors(reference, level), actors(candidate, level)
    return dict(reference=str(reference), candidate=str(candidate), level=level,
        comparison='Virtual paths and ZIP CRC/size; generated-path renames need source review',
        reference_entries=len(old), candidate_entries=len(new),
        missing_count=len(missing), changed_count=len(changed),
        missing_by_archive=dict(Counter(r['archive'] for rows in missing.values() for r in rows)),
        reference_npcs=len(before), candidate_npcs=len(after),
        missing_npcs={k: before[k] for k in sorted(before.keys() - after.keys())},
        missing=missing, changed=changed,
        conflicting_overrides={label: {n: rows for n, rows in entries.items()
            if len(signatures(rows)) > 1} for label, entries in [('reference', old), ('candidate', new)]},
        runtime_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.reference, args.candidate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ('missing', 'changed', 'conflicting_overrides')}, indent=2))


if __name__ == '__main__':
    main()
