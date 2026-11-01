"""Index facial tracks for native recordings relocated by world_speech_audio.

KCD2 finds a line's facial animation by mirroring the recording path:
``dialog/X/Y.ogg`` plays ``animations/humans/facials/dialog/X/Y.caf`` from the
facial index. ``world_speech_audio.upgrade`` copies native recordings under the
imported world's voice namespace, so their tracks must be indexed at the new
path too, or the line plays without lip sync. This step reads the same
relocation plan, matches every relocated recording to its native header by the
full original path, and copies each native DBA that holds relocated clips once,
renamed inside by ``NativeFacialImporter`` with its curves byte-for-byte. The
copies go into deflated shard archives beside the dialogue facials pak, which
keeps the combined index. Lines without a native track are reported, never
invented.

Repeatable: output DBAs are named by their source and rename set, index records
keep their identities, and nothing is rewritten when nothing changed.
"""
import json
from pathlib import Path
import zipfile

from dialogue_facials import INDEX, NativeFacialImporter, container
from upgrade_map import read

VERSION = 1
FACIALS = 'Data/gluemapper_dialogue_facials.pak'
SHARD = 'Data/gluemapper_world_speech_facials_{:04d}.pak'
REPORT = 'world-speech-facials.json'
SHARD_BYTES = 1024 ** 3
LABEL = 'Index lip sync for relocated native speech'


def shards(package):
    """Existing relocated-facial archives of a package, in order."""
    package = Path(package)
    data = package / 'Data'
    if not data.is_dir(): return []
    return sorted(p.relative_to(package).as_posix()
                  for p in data.glob('gluemapper_world_speech_facials_[0-9][0-9][0-9][0-9].pak'))


def members(package):
    """{DBA path: archive} over the existing shards; duplicates are an error."""
    package = Path(package)
    result = {}
    for relative in shards(package):
        with zipfile.ZipFile(package / relative) as z:
            for info in z.infolist():
                if info.filename in result:
                    raise ValueError('Duplicate relocated facial database: ' + info.filename)
                result[info.filename] = relative
    return result


def plan(package, target, only=None):
    """Relocated recordings whose audio is already packaged, with the plan's scopes.

    Returns (None, reason) when the package relocates no native speech. Every
    planned recording must already sit in the package's English bank with the
    native payload: the audio pass runs first. `only` keeps the destinations
    starting with a prefix, for staged partial runs.
    """
    from audio_mapping import EnglishRecordings
    from world_speech_audio import plan as audio_plan, selection
    package = Path(package)
    scopes, reason = audio_plan(package, target)
    if scopes is None: return None, reason
    with EnglishRecordings(Path(target)) as recordings:
        selected, scope_reports = selection(recordings, scopes)
        native = {source: (recordings.members[source][0][2].CRC, recordings.members[source][0][2].file_size)
                  for source in set(selected.values())}
    with zipfile.ZipFile(package / 'Localization/English.pak') as z:
        packaged = {i.filename.lower(): (i.CRC, i.file_size) for i in z.infolist()}
    absent = sorted(dest for dest, source in selected.items() if packaged.get(dest) != native[source])
    if absent:
        raise ValueError('Relocated native speech is not packaged yet; the audio relocation runs first: ' + absent[0])
    if only:
        selected = {dest: source for dest, source in selected.items() if dest.startswith(only.lower())}
    return dict(selected=selected, scopes=scope_reports), None


def rewrite(source, destination, replacements):
    """Copy an archive with members replaced or added; the destination changes atomically."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(destination.name + '.facials-pending')
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(pending, 'x', zipfile.ZIP_STORED, allowZip64=True) as out:
        names = set()
        for info in original.infolist():
            if info.filename in names: raise ValueError('Duplicate archive path: ' + info.filename)
            names.add(info.filename)
            out.writestr(info, replacements.get(info.filename, read(original, info.filename)))
        for name in sorted(set(replacements) - names):
            out.writestr(name, replacements[name])
    with zipfile.ZipFile(pending) as check:
        if check.testzip() is not None: raise ValueError('Facial index archive verification failed')
    pending.replace(destination)


class Shards:
    """Deflated DBA copies in bounded archives, pending until every one verifies."""
    def __init__(self, destination):
        self.destination = Path(destination)
        self.pending, self.out, self.count = [], None, 0

    def _open(self):
        self.close()
        relative = SHARD.format(len(self.pending))
        path = self.destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        pending = path.with_name(path.name + '.facials-pending')
        if pending.exists(): pending.unlink()
        self.out = zipfile.ZipFile(pending, 'x', zipfile.ZIP_DEFLATED, allowZip64=False)
        self.pending.append((relative, pending))
        self.count = 0

    def add(self, name, payload):
        if len(payload) + 2 ** 20 > SHARD_BYTES:
            raise ValueError('Relocated facial database exceeds the shard limit: ' + name)
        if self.out is None or (self.count and self.out.fp.tell() + len(payload) + 2 ** 20 > SHARD_BYTES):
            self._open()
        self.out.writestr(name, payload)
        self.count += 1

    def close(self):
        if self.out is not None:
            self.out.close()
            self.out = None

    def commit(self):
        """Verify every pending archive, then move all of them into place."""
        self.close()
        for relative, pending in self.pending:
            with zipfile.ZipFile(pending) as check:
                if check.testzip() is not None:
                    raise ValueError('Relocated facial archive verification failed: ' + relative)
            if pending.stat().st_size > SHARD_BYTES:
                raise ValueError('Relocated facial archive exceeds the shard limit: ' + relative)
        for relative, pending in self.pending:
            pending.replace(self.destination / relative)
        return [relative for relative, _ in self.pending]


def apply(package, target, destination, notify=lambda *a: None, only=None):
    """Index the relocated facial tracks of `package`, writing into `destination`.

    `destination` is the package itself for an in-place upgrade or a new folder
    for a dry run; the current state is always read from `package`. Returns
    (files, removed, report): digests of the written archives and report, the
    archives that became obsolete, and the receipt report.
    """
    from setup_campaign import digest
    package, destination = Path(package), Path(destination)
    planned, reason = plan(package, target, only)
    if planned is None:
        return {}, [], dict(version=VERSION, recordings=0, reason=reason)
    notify(LABEL, 0, 1, 'Matching relocated recordings to native facial tracks')
    with zipfile.ZipFile(package / FACIALS) as z:
        existing = read(z, INDEX)
    previous = members(package)
    in_place = destination.resolve() == package.resolve()
    importer = NativeFacialImporter(target, existing)
    try:
        groups, missing = importer.relocation(planned['selected'])
        changed_records = importer.index_relocation(groups, previous)
        rebuild = not in_place or set(groups) != set(previous)
        archives = sorted(set(previous.values()))
        if rebuild:
            writer = Shards(destination)
            try:
                for index, (name, group) in enumerate(sorted(groups.items()), 1):
                    writer.add(name, importer.relocated_database(group))
                    notify(LABEL, index, len(groups), name)
                archives = writer.commit()
            finally:
                writer.close()
        if changed_records or not in_place:
            rewrite(package / FACIALS, destination / FACIALS, {INDEX: container(importer.records)})
        index_headers, native_headers = len(importer.records), importer.native_count
    finally:
        importer.close()
    removed = [relative for relative in shards(package) if in_place and relative not in archives]
    for relative in removed:
        (package / relative).unlink()
    located = {}
    for relative in archives:
        with zipfile.ZipFile(destination / relative) as z:
            for info in z.infolist():
                located[info.filename] = (relative, info.file_size, info.compress_size)
    if set(located) != set(groups):
        raise ValueError('Relocated facial archives do not match the plan')
    databases = [dict(target=name, source=group['source'], source_archive=group['archive'], archive=located[name][0],
                      clips=len(group['tracks']), bytes=located[name][1], compressed=located[name][2])
                 for name, group in sorted(groups.items())]
    scopes = []
    for scope in planned['scopes']:
        prefix = scope['destination_scope']
        tracked = sum(1 for group in groups.values() for dest in group['tracks'].values()
                      if dest.startswith('animations/humans/facials/' + prefix))
        scopes.append(dict(scope, facial_tracks=tracked, missing_tracks=sum(1 for m in missing if m.startswith(prefix))))
    details = dict(version=VERSION, scopes=scopes, recordings=len(planned['selected']),
                   facial_tracks=sum(len(group['tracks']) for group in groups.values()),
                   missing_tracks=sorted(missing), databases=databases, archives=archives,
                   index_headers=index_headers, native_headers=native_headers)
    text = json.dumps(details, indent=2)
    report_path = destination / REPORT
    if not report_path.exists() or report_path.read_text(encoding='utf-8') != text:
        pending = report_path.with_name(REPORT + '.facials-pending')
        pending.write_text(text, encoding='utf-8')
        pending.replace(report_path)
    files = {relative: digest(destination / relative) for relative in (FACIALS, REPORT, *archives)}
    report = dict(version=VERSION, scopes=scopes, recordings=details['recordings'],
                  facial_tracks=details['facial_tracks'], missing_tracks=len(missing), databases=len(groups),
                  archives=archives, bytes=sum(d['bytes'] for d in databases),
                  compressed_bytes=sum(d['compressed'] for d in databases),
                  index_headers=index_headers, native_headers=native_headers,
                  changed=dict(index_records=changed_records, archives=rebuild, removed=removed),
                  runtime_verified=False)
    return files, removed, report


def upgrade(package, target, notify=lambda *a: None):
    """Used inside the shared finalization, after world_speech_audio.upgrade."""
    package = Path(package).resolve()
    return apply(package, target, package, notify)


def stage(mod, target, output, only=None):
    """Dry run into a new folder, like loft_navigation.stage; the package is not modified."""
    mod, target, output = map(Path, (mod, target, output))
    if output.exists():
        raise FileExistsError('Choose a new facial staging folder')
    output.mkdir(parents=True)
    files, removed, report = apply(mod, target, output, only=only)
    report = dict(report, files=files, only=only)
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('mod', 'target', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--only', help='destination prefix, e.g. dialog/kcd1_travel/open_world/shop/bcas_')
    print(json.dumps(stage(**vars(parser.parse_args())), indent=2))
