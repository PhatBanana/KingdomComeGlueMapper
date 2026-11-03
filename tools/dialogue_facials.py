"""Import original recording-linked facial DBA tracks into the native index.

Supports little-endian Cry 0x746 / GAHCAF 0x971 / in-place DBA 0x905.
Curves are retained byte-for-byte. Names, index hashes and DBA layout move;
validated rig aliases add native speech controls referencing the same tracks.
"""
from collections import defaultdict
import hashlib
from pathlib import Path
import re
import struct
import zipfile
import zlib

from upgrade_map import read

INDEX = 'Animations/FacialAnimations.img'


def chunks(blob):
    if blob[:8] != b'CrCh' + struct.pack('<I', 0x746):
        raise ValueError('Unsupported facial chunk container')
    count, table = struct.unpack_from('<II', blob, 8)
    if table != 16 or table + count * 16 > len(blob):
        raise ValueError('Invalid facial chunk table')
    result, spans, ids = [], [], set()
    for i in range(count):
        kind, version, identity, size, offset = struct.unpack_from('<HHIII', blob, table + i*16)
        if identity in ids or offset < table + count*16 or offset + size > len(blob):
            raise ValueError('Invalid facial chunk bounds/identity')
        ids.add(identity); spans.append((offset, offset+size))
        result.append((kind, version, identity, blob[offset:offset+size]))
    spans.sort()
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        raise ValueError('Overlapping facial chunks')
    return result


def container(records):
    out = bytearray(b'CrCh' + struct.pack('<III', 0x746, len(records), 16))
    out.extend(bytes(16*len(records)))
    for i, (kind, version, identity, data) in enumerate(records):
        out.extend(bytes(-len(out) % 4))
        struct.pack_into('<HHIII', out, 16+16*i, kind, version, identity, len(data), len(out))
        out.extend(data)
    return bytes(out)


def header_path(record):
    kind, version, _, data = record
    if (kind, version, len(data)) != (0x3007, 0x971, 404):
        raise ValueError('Unsupported facial index record')
    raw = data[4:260].split(b'\0', 1)[0]
    path = raw.decode('ascii')
    if not path or path != path.lower() or struct.unpack_from('<I', data, 260)[0] not in (0, zlib.crc32(raw)):
        raise ValueError('Invalid facial index path/hash')
    return path


def renamed_header(record, path, database):
    header_path(record)
    raw = path.encode('ascii')
    if len(raw) >= 256 or path != path.lower():
        raise ValueError('Facial animation path exceeds native limit')
    data = bytearray(record[3]); data[4:260] = raw + bytes(256-len(raw))
    # Every shipped KCD2 facial header leaves the CAF hash for the facial loader.
    struct.pack_into('<II', data, 260, 0, zlib.crc32(database.encode('ascii')))
    return (record[0], record[1], record[2], bytes(data))


def database(blob):
    records = chunks(blob)
    if len(records) != 1 or records[0][:2] != (0x100d, 0x905):
        raise ValueError('Unsupported facial DBA')
    data = records[0][3]
    np, nr, nt, na = struct.unpack_from('<4I', data)
    if not nt or not na or max(np, nr, nt, na) > 1000000:
        raise ValueError('Invalid facial DBA counts')
    offset = 16 + 2*(np+nr+nt) + 4*(7+9+9)
    offsets = struct.unpack_from('<' + str(nt+np+nr+1) + 'i', data, offset)
    if offsets[0] >= 0 or offsets[-1] >= 0:
        raise ValueError('Facial DBA requires in-place streaming layout')
    end_offsets = offset+4*len(offsets)
    padding = struct.unpack_from('<I', data, end_offsets)[0]
    start = (end_offsets+4+padding+3)//4*4
    track_start = len(data)+offsets[-1]
    if not start < track_start or any(v >= 0 or v < offsets[-1] for v in offsets[:-1]):
        raise ValueError('Invalid facial track offsets')
    entries, pos = [], start
    for _ in range(na):
        length = struct.unpack_from('<H', data, pos)[0]; pos += 2
        if not 0 < length < 256:
            raise ValueError('Invalid facial DBA name length')
        name = data[pos:pos+length].decode('ascii'); pos += length
        metadata_start = pos; pos += 132  # MotionParams905
        feet = struct.unpack_from('<H', data, pos)[0]; pos += 2+feet
        count, controller_offset = struct.unpack_from('<Hi', data, pos); pos += 6
        entries.append(dict(name=name, metadata=data[metadata_start:pos-4], count=count,
                            offset=controller_offset))
    cursor = pos
    for entry in entries:
        if start+entry['offset'] != cursor or cursor+entry['count']*20 > track_start:
            raise ValueError('Invalid facial controller block')
        entry['controllers'] = data[cursor:cursor+entry['count']*20]
        cursor += entry['count']*20
        for i in range(entry['count']):
            _, pt, p, rt, r = struct.unpack_from('<I4i', entry['controllers'], 20*i)
            if any(v < -1 or v >= limit for v, limit in [(pt,nt),(p,np),(rt,nt),(r,nr)]):
                raise ValueError('Invalid facial controller track reference')
    if (cursor+3)//4*4 != track_start:
        raise ValueError('Unexpected facial DBA trailing metadata')
    if len({e['name'] for e in entries}) != len(entries):
        raise ValueError('Duplicate facial DBA animation')
    return data[:start], entries, data[track_start:]


def aliased_controllers(controllers, aliases):
    if len(controllers) % 20:
        raise ValueError('Invalid facial controller bytes')
    blocks = {struct.unpack_from('<I', controllers, i)[0]: controllers[i:i+20]
              for i in range(0, len(controllers), 20)}
    if len(blocks) * 20 != len(controllers):
        raise ValueError('Duplicate facial controller')
    additions = {}
    for source, targets in aliases.items():
        if source not in blocks: continue
        for target in targets:
            if target in blocks or target in additions:
                raise ValueError('Competing facial controller alias')
            additions[target] = struct.pack('<I', target) + blocks[source][4:]
    # Runtime controller lookup expects the same increasing ID order used by
    # converted animation exporters; timing and shared tracks are untouched.
    blocks.update(additions)
    return b''.join(blocks[c] for c in sorted(blocks))


def select_database(blob, mapping, aliases=None):
    prefix, entries, tracks = database(blob)
    by_name = {e['name']:e for e in entries}
    if mapping.keys() - by_name.keys():
        raise ValueError('Facial index refers to missing DBA animation')
    selected = [(by_name[name], dest) for name, dest in sorted(mapping.items())]
    if aliases:
        converted = []
        for entry, dest in selected:
            entry = dict(entry)
            entry['controllers'] = aliased_controllers(entry['controllers'], aliases)
            entry['count'] = len(entry['controllers']) // 20
            if entry['count'] > 65535: raise ValueError('Facial controller count exceeds native limit')
            metadata = bytearray(entry['metadata'])
            struct.pack_into('<H', metadata, len(metadata)-2, entry['count'])
            entry['metadata'] = bytes(metadata)
            converted.append((entry, dest))
        selected = converted
    metadata = bytearray(); controllers = bytearray()
    header_size = sum(2+len(dest.encode('ascii'))+len(e['metadata'])+4 for e,dest in selected)
    for e, dest in selected:
        raw = dest.encode('ascii')
        if len(raw) >= 256: raise ValueError('Facial DBA path exceeds limit')
        metadata.extend(struct.pack('<H', len(raw))+raw+e['metadata'])
        metadata.extend(struct.pack('<i', header_size+len(controllers)))
        controllers.extend(e['controllers'])
    data = bytearray(prefix); struct.pack_into('<I', data, 12, len(selected))
    data.extend(metadata); data.extend(controllers); data.extend(bytes(-len(data)%4)); data.extend(tracks)
    result = container([(0x100d,0x905,1,bytes(data))])
    _, verified, retained = database(result)
    if retained != tracks or [e['controllers'] for e in verified] != [e['controllers'] for e,_ in selected]:
        raise ValueError('Facial curve/controller preservation failed')
    return result


def source_facial_index(pak, name):
    # The source IMG also contains unrelated animation records.
    for record in chunks(read(pak, name)):
        if record[:2] != (0x3007, 0x971): continue
        original = header_path(record)
        if original.startswith('animations/humans/facials/'): yield original, record


def source_tracks(source):
    """KCD1 facial clips: (archives, {crc: base DBA}, {stem: [(path, record)]}, {path: patch DBA}).

    Base `Data/Animations*.pak` clips come first. KCD1's patches
    (`Data/patch/*.pak`, a later version overriding an earlier one) re-export
    many base clips and add others, such as the IPL voices' market cries. Only
    stems the base lacks are taken from them, so a line keeps the track that
    matches its base or IPL recording; such a clip reads its DBA from the
    latest patch carrying it, because a patched DBA adds clips under the base
    DBA's own name.
    """
    archives, dbas, headers, patch_dbas = [], {}, defaultdict(list), {}
    try:
        for path in sorted((Path(source)/'Data').glob('Animations*.pak')):
            pak = zipfile.ZipFile(path); archives.append(pak)
            for name in pak.namelist():
                key = name.lower()
                if key.startswith('animations/humans/facials/') and key.endswith('.dba'):
                    crc = zlib.crc32(key.encode())
                    if crc in dbas: raise ValueError('Ambiguous source facial DBA')
                    dbas[crc] = (pak, name)
                if key == 'animations/animations.img':
                    for original, record in source_facial_index(pak, name):
                        headers[Path(original).stem].append((original, record))
        patches = sorted((Path(source)/'Data/patch').glob('*.pak'),
                         key=lambda p: (re.sub(r'^\D*', '', p.stem.lower()), p.name.lower()))
        latest, patched = {}, {}
        for path in patches:
            pak = zipfile.ZipFile(path); archives.append(pak)
            for name in pak.namelist():
                key = name.lower()
                if key.startswith('animations/humans/facials/') and key.endswith('.dba'):
                    patched[zlib.crc32(key.encode())] = (pak, name)
                if key == 'animations/animations.img':
                    latest.update(source_facial_index(pak, name))
        added = defaultdict(list)
        for original, record in latest.items():
            if Path(original).stem not in headers: added[Path(original).stem].append((original, record))
        for stem, rows in added.items():
            # An ambiguous patch-only stem stays without a track, as before.
            if len(rows) != 1: continue
            original, record = rows[0]
            crc = struct.unpack_from('<I', record[3], 264)[0]
            if crc not in patched and crc not in dbas: continue
            headers[stem] = rows; patch_dbas[original] = patched.get(crc) or dbas[crc]
        return archives, dbas, headers, patch_dbas
    except Exception:
        for pak in archives: pak.close()
        raise


class FacialImporter:
    def __init__(self, source, target, existing=None):
        from facial_rig_adapter import load_speech_adapter
        self.aliases, self.rig_report = load_speech_adapter(source, target)
        self.archives, self.dbas, self.source_headers, self.patch_dbas = source_tracks(source)
        baselines=[]
        for path in sorted((Path(target)/'Data/Facials').glob('*english*.pak')):
            with zipfile.ZipFile(path) as pak:
                if INDEX in pak.namelist(): baselines.append(chunks(read(pak,INDEX)))
        if len(baselines)!=1: raise ValueError('Expected one native English facial index')
        baseline=baselines[0]
        self.records = chunks(existing) if existing else baseline
        if self.records[:len(baseline)] != baseline:
            raise ValueError('Existing facial index does not preserve native baseline')
        self.native_count=len(baseline)
        self.indexed={header_path(r):r for r in self.records}
        self.next_id=max(r[2] for r in self.records)+1
        self.outputs={}; self.receipts=[]

    def close(self):
        for pak in self.archives: pak.close()

    def source_database(self, original, record):
        """(DBA CRC, patch archive name or '') naming the database that holds a source clip."""
        crc=struct.unpack_from('<I',record[3],264)[0]
        if original in self.patch_dbas: return crc,Path(self.patch_dbas[original][0].filename).name.lower()
        if crc not in self.dbas: raise ValueError('Missing source lip-sync database: '+original)
        return crc,''

    def add(self, recordings):
        groups=defaultdict(dict); headers={}
        for audio in recordings:
            stem=Path(audio).stem.lower()
            candidates=self.source_headers.get(stem,[])
            if len(candidates)!=1:
                raise ValueError('Missing or ambiguous source lip-sync track: '+stem)
            original,record=candidates[0]
            source=self.source_database(original,record)
            dest='animations/humans/facials/'+audio[:-4].lower()+'.caf'
            if not audio.lower().startswith('dialog/') or not audio.lower().endswith('.ogg') or '..' in audio.split('/'):
                raise ValueError('Invalid bound recording path')
            # Separate namespaces can reference the same source line.
            groups[(source,str(Path(dest).parent))][original]=dest
            headers[dest]=record
        for (source,namespace),mapping in sorted(groups.items()):
            crc,origin=source
            pak,name=self.patch_dbas[next(iter(mapping))] if origin else self.dbas[crc]
            # Base databases keep their earlier copy names; a patch database is a different source.
            identity=hashlib.sha256((name.lower()+'\n'+namespace+('\n'+origin if origin else '')).encode()).hexdigest()[:24]
            dest_dba='animations/humans/facials/dialog/glueimport/'+identity+'.dba'
            # Rebuilding a namespace must retain tracks imported in prior passes.
            for dest, old in self.indexed.items():
                if struct.unpack_from('<I',old[3],264)[0] != zlib.crc32(dest_dba.encode()): continue
                candidates=self.source_headers.get(Path(dest).stem,[])
                if len(candidates)!=1: raise ValueError('Cannot reconstruct existing imported facial track')
                original,record=candidates[0]
                if self.source_database(original,record)!=source:
                    raise ValueError('Imported facial database identity collision')
                mapping[original]=dest;headers[dest]=record
            payload=select_database(read(pak,name),mapping,self.aliases)
            _, converted_entries, _ = database(payload)
            controller_counts = {e['name']: e['count'] for e in converted_entries}
            self.outputs[dest_dba]=payload
            for original,dest in mapping.items():
                record=renamed_header(headers[dest],dest,dest_dba)
                data=bytearray(record[3])
                struct.pack_into('<I',data,312,controller_counts[dest])
                record=(*record[:3],bytes(data))
                if dest in self.indexed:
                    old=self.indexed[dest]
                    old_data=bytearray(old[3]);old_data[312:316]=record[3][312:316]
                    if bytes(old_data)!=record[3]: raise ValueError('Conflicting imported facial track: '+dest)
                    record=(record[0],record[1],old[2],record[3])
                    self.records[self.records.index(old)]=record;self.indexed[dest]=record
                else:
                    identity=self.next_id;self.next_id+=1
                    record=(record[0],record[1],identity,record[3])
                    self.records.append(record);self.indexed[dest]=record
                self.receipts.append(dict(source=original,target=dest,database=dest_dba,source_archive=pak.filename,
                                          controllers=controller_counts[dest]))

    def resources(self):
        return dict(self.outputs, **{INDEX:container(self.records)})

    def report(self):
        return dict(native_headers=self.native_count,total_headers=len(self.records),
                    recordings=self.receipts,databases=len(self.outputs),rig_adapter=self.rig_report,runtime_verified=False)


class NativeFacialImporter(FacialImporter):
    """Relocate target-game dialogue tracks with their original rig/curves.

    Moving a native recording to a new quest namespace also changes its facial
    lookup path. Extend the existing combined index; never replace converted
    source tracks with a fresh native-only index.
    """
    def __init__(self, target, existing=None):
        self.aliases = {}
        self.rig_report = dict(mode='native target rig; no controller remapping')
        self.archives = []; self.dbas = {}; self.source_headers = defaultdict(list); self.patch_dbas = {}
        baselines = []
        try:
            for path in sorted((Path(target)/'Data/Facials').glob('*english*.pak')):
                pak = zipfile.ZipFile(path); self.archives.append(pak)
                for name in pak.namelist():
                    key = name.lower()
                    if key == INDEX.lower(): baselines.append(chunks(pak.read(name)))
                    if key.startswith('animations/humans/facials/') and key.endswith('.dba'):
                        crc = zlib.crc32(key.encode('ascii'))
                        if crc in self.dbas: raise ValueError('Ambiguous native facial DBA')
                        self.dbas[crc] = (pak, name)
            if len(baselines) != 1: raise ValueError('Expected one native English facial index')
            baseline = baselines[0]
            for record in baseline:
                original = header_path(record)
                self.source_headers[Path(original).stem].append((original, record))
            self.records = chunks(existing) if existing is not None else list(baseline)
            if self.records[:len(baseline)] != baseline:
                raise ValueError('Existing facial index does not preserve native baseline')
            self.native_count = len(baseline)
            self.indexed = {header_path(r): r for r in self.records}
            if len(self.indexed) != len(self.records): raise ValueError('Duplicate facial index paths')
            self.native_tracks = {header_path(r): r for r in baseline}
            self.next_id = max(r[2] for r in self.records) + 1
            self.outputs = {}; self.receipts = []
        except Exception:
            self.close()
            raise

    RELOCATED = 'animations/humans/facials/dialog/glueworld/'

    def relocation(self, mapping):
        """Group relocated native recordings by the native DBA holding their tracks.

        `mapping` is {relocated audio path: original audio path}. A track is
        found by its full original facial path, never by its file stem, because
        one stem may recur under several native directories. Returns
        ({output DBA path: dict(source, archive, tracks={original caf: new caf})},
        [relocated recordings without a native track]). The output DBA path
        hashes the source DBA and the exact rename set, so a later pass can
        recognise an unchanged copy without rebuilding it.
        """
        groups, missing = defaultdict(dict), []
        for audio, original in sorted(mapping.items()):
            if not audio.lower().startswith('dialog/') or not audio.lower().endswith('.ogg') or '..' in audio.split('/'):
                raise ValueError('Invalid relocated recording path: ' + audio)
            if not original.lower().endswith('.ogg') or '..' in original.split('/'):
                raise ValueError('Invalid native recording path: ' + original)
            source = 'animations/humans/facials/' + original[:-4].lower() + '.caf'
            record = self.native_tracks.get(source)
            if record is None:
                missing.append(audio)
                continue
            crc = struct.unpack_from('<I', record[3], 264)[0]
            if crc not in self.dbas: raise ValueError('Missing native lip-sync database: ' + source)
            dest = 'animations/humans/facials/' + audio[:-4].lower() + '.caf'
            if groups[crc].get(source, dest) != dest:
                raise ValueError('Native recording relocated to two paths: ' + original)
            groups[crc][source] = dest
        result = {}
        for crc, tracks in groups.items():
            pak, name = self.dbas[crc]
            identity = hashlib.sha256('\n'.join([name.lower(), *(s + '\t' + d for s, d in sorted(tracks.items()))])
                                      .encode('ascii')).hexdigest()[:24]
            result[self.RELOCATED + identity + '.dba'] = dict(source=name, archive=Path(pak.filename).name, tracks=tracks)
        return result, missing

    def index_relocation(self, groups, previous=()):
        """Add or refresh the header of every relocated track; drop stale ones.

        `previous` names output DBAs of earlier passes, so their headers can be
        replaced or removed; a header at a relocated path that belongs to any
        other import is a conflict. Record identities are retained, so an
        unchanged relocation leaves the index byte-identical. Returns the number
        of records added, replaced or removed.
        """
        owned = {zlib.crc32(p.encode('ascii')) for p in (*previous, *groups)}
        wanted = {}
        for dest_dba, group in groups.items():
            for source, dest in group['tracks'].items():
                if dest in wanted: raise ValueError('Two native tracks relocated to one path: ' + dest)
                wanted[dest] = renamed_header(self.native_tracks[source], dest, dest_dba)
        positions = {header_path(r): i for i, r in enumerate(self.records) if i >= self.native_count}
        changes = 0
        for dest, record in wanted.items():
            old = self.indexed.get(dest)
            if old is None:
                record = (record[0], record[1], self.next_id, record[3]); self.next_id += 1
                self.records.append(record); self.indexed[dest] = record; changes += 1
            elif old[3] != record[3]:
                if struct.unpack_from('<I', old[3], 264)[0] not in owned:
                    raise ValueError('Conflicting facial track at relocated path: ' + dest)
                record = (record[0], record[1], old[2], record[3])
                self.records[positions[dest]] = record; self.indexed[dest] = record; changes += 1
        stale = {header_path(r) for r in self.records[self.native_count:]
                 if struct.unpack_from('<I', r[3], 264)[0] in owned and header_path(r) not in wanted}
        if stale:
            self.records = [r for i, r in enumerate(self.records) if i < self.native_count or header_path(r) not in stale]
            for path in stale: del self.indexed[path]
            changes += len(stale)
        return changes

    def relocated_database(self, group):
        """The renamed copy of one native DBA; curves and controllers stay byte-for-byte."""
        pak, name = self.dbas[zlib.crc32(group['source'].lower().encode('ascii'))]
        payload = select_database(read(pak, name), group['tracks'])
        _, entries, _ = database(payload)
        counts = {e['name']: e['count'] for e in entries}
        for source, dest in group['tracks'].items():
            if counts.get(dest) != struct.unpack_from('<I', self.native_tracks[source][3], 312)[0]:
                raise ValueError('Relocated facial controller count differs from its header: ' + dest)
        return payload
