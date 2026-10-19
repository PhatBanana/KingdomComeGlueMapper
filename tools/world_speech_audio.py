"""Relocate native world speech with its instantiated voice namespace.

The native world graphs keep their internal namespaces and response IDs. A new
Level ancestor adds an audio directory, even though subtitles still resolve.
Copy only referenced native recordings, retaining every recorded voice/fallback.
"""
from contextlib import ExitStack
from pathlib import Path
import posixpath
import xml.etree.ElementTree as ET
import zipfile
import zlib

from audio_mapping import EnglishRecordings
from campaign_dialogue_runtime import voice_namespace
from dialogue_dubbing import DEPOT
from upgrade_map import read


def relocation(graphs, wrapper):
    """Derive the added scope; follow literal packaged dependencies for text IDs."""
    host = ET.fromstring(graphs[wrapper]).find('Skald')[0]
    if host.get('VoiceNamespace') != 'true':
        raise ValueError('Native world wrapper must retain its voice namespace')
    scope = voice_namespace(graphs, wrapper)
    native = ('dialog/' + host.get('Name') + '/').lower()
    destination = ('dialog/' + '/'.join(scope) + '/').lower()
    visited, responses = set(), set()
    def walk(path):
        if path in visited: return
        visited.add(path)
        root = ET.fromstring(graphs[path])
        responses.update(t.get('StringName').lower() for t in root.findall('.//Response/Text') if t.get('StringName'))
        for definition in root.findall('.//Definitions/Definition'):
            child = posixpath.normpath(posixpath.join(posixpath.dirname(path), definition.get('File')))
            if child not in graphs: raise ValueError('Missing speech dependency: ' + child)
            walk(child)
    walk(wrapper)
    return native, destination, responses


def select(entries, native, destination, responses):
    result = {}
    for name in entries:
        normalized = name.replace('\\', '/').lower()
        if not normalized.startswith(native) or not normalized.endswith('.ogg'): continue
        # Voice abbreviation precedes the original response string ID.
        if normalized.rsplit('/', 1)[-1].split('_', 1)[-1][:-4] not in responses: continue
        target = destination + name.replace('\\', '/')[len(native):]
        if target.lower() in result and result[target.lower()] != name:
            raise ValueError('Ambiguous case-insensitive recording: ' + target)
        result[target.lower()] = name
    return result


def upgrade(package, target, notify=lambda *a: None):
    """Atomic, idempotent audio-only upgrade; shared native banks stay untouched."""
    package = Path(package)
    with zipfile.ZipFile(package/'Data/gluemappertravel.pak') as z:
        graphs = {n: read(z,n) for n in z.namelist() if n.startswith('Quests/') and n.endswith('.xml')}
    wrappers = [n for n in graphs if n.endswith('/entry/world/open_world.xml')]
    if not wrappers: return {}, dict(recordings=0, reason='no relocated native world')
    if len(wrappers) != 1: raise ValueError('Ambiguous native world wrapper')
    target = Path(target)
    native, destination, responses = relocation(graphs, wrappers[0])
    if native == destination: return {}, dict(recordings=0, reason='native audio scope retained')
    relative = 'Localization/English.pak'
    path = package/relative
    pending = path.with_suffix('.speech-pending')
    with EnglishRecordings(target) as recordings, ExitStack() as stack:
        selected = select(recordings.members, native, destination, responses)
        if responses and not selected: raise ValueError('No native speech recordings resolved')
        current = stack.enter_context(zipfile.ZipFile(path))
        existing = {i.filename.lower(): i for i in current.infolist()}
        depot = ET.fromstring(read(current, DEPOT))
        hashes = {r.get('FileHash') for r in depot.iter('DialogueDubbing')}
        missing = [n for n in selected.values() if str(zlib.crc32(
            recordings.members[n][0][2].filename.rsplit('/',1)[-1][:-4].encode())) not in hashes]
        if missing: raise ValueError('Packaged dubbing index omits native speech: ' + missing[0])
        changed = {}
        total = 0
        for dest, source in selected.items():
            candidates = recordings.members[source]
            signatures = {(i.CRC, i.file_size) for _, _, i in candidates}
            if len(signatures) != 1: raise ValueError('Conflicting native audio banks: ' + source)
            info = candidates[0][2]
            total += info.file_size
            old = existing.get(dest)
            if old is None or (old.CRC,old.file_size) != (info.CRC,info.file_size): changed[dest] = source
        report = dict(source_scope=native, destination_scope=destination, responses=len(responses),
                      recordings=len(selected), bytes=total, changed=len(changed), runtime_verified=False)
        if not changed: return {}, report
        notify('Relocating native nearby speech recordings', 0, len(changed), '')
        try:
            with zipfile.ZipFile(pending, 'x', zipfile.ZIP_STORED) as out:
                for info in current.infolist():
                    if info.filename.lower() not in changed: out.writestr(info, read(current,info.filename))
                for index, (dest, source) in enumerate(sorted(changed.items()), 1):
                    # Preserve filename case: the native dubbing hash is case sensitive.
                    original = recordings.members[source][0][2].filename.rsplit('/',1)[-1]
                    out.writestr(dest.rsplit('/',1)[0]+'/'+original, recordings.extract(source))
                    notify('Relocating native nearby speech recordings', index, len(changed), dest)
            with zipfile.ZipFile(pending) as check:
                if check.testzip() is not None: raise ValueError('Invalid relocated speech archive')
                actual = {i.filename.lower():(i.CRC,i.file_size) for i in check.infolist()}
                for dest, source in selected.items():
                    i = recordings.members[source][0][2]
                    if actual.get(dest) != (i.CRC,i.file_size): raise ValueError('Speech payload verification failed')
        except Exception:
            # Leave failed output for inspection; never replace a working archive.
            raise
    pending.replace(path)
    from setup_campaign import digest
    return {relative: digest(path)}, report
