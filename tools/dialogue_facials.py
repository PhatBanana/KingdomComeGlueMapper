"""Import original recording-linked facial DBA tracks into the native index.

Supports little-endian Cry 0x746 / GAHCAF 0x971 / in-place DBA 0x905.
Curves are retained byte-for-byte. Names, index hashes and DBA layout move;
validated rig aliases add native speech controls referencing the same tracks.
"""
from collections import defaultdict
import hashlib
from pathlib import Path
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


class FacialImporter:
    def __init__(self, source, target, existing=None):
        from facial_rig_adapter import load_speech_adapter
        self.aliases, self.rig_report = load_speech_adapter(source, target)
        self.archives = []
        self.dbas = {}; self.source_headers = defaultdict(list)
        for path in sorted((Path(source)/'Data').glob('Animations*.pak')):
            pak = zipfile.ZipFile(path); self.archives.append(pak)
            for name in pak.namelist():
                key = name.lower()
                if key.startswith('animations/humans/facials/') and key.endswith('.dba'):
                    crc = zlib.crc32(key.encode())
                    if crc in self.dbas: raise ValueError('Ambiguous source facial DBA')
                    self.dbas[crc] = (pak, name)
                if key == 'animations/animations.img':
                    for record in chunks(read(pak,name)):
                        # The source IMG also contains unrelated animation records.
                        if record[:2] != (0x3007,0x971): continue
                        original = header_path(record)
                        if original.startswith('animations/humans/facials/'):
                            self.source_headers[Path(original).stem].append((original,record))
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

    def add(self, recordings):
        groups=defaultdict(dict); headers={}
        for audio in recordings:
            stem=Path(audio).stem.lower()
            candidates=self.source_headers.get(stem,[])
            if len(candidates)!=1:
                raise ValueError('Missing or ambiguous source lip-sync track: '+stem)
            original,record=candidates[0]
            crc=struct.unpack_from('<I',record[3],264)[0]
            if crc not in self.dbas: raise ValueError('Missing source lip-sync database: '+original)
            dest='animations/humans/facials/'+audio[:-4].lower()+'.caf'
            if not audio.lower().startswith('dialog/') or not audio.lower().endswith('.ogg') or '..' in audio.split('/'):
                raise ValueError('Invalid bound recording path')
            # Separate namespaces can reference the same source line.
            groups[(crc,str(Path(dest).parent))][original]=dest
            headers[dest]=record
        for (crc,namespace),mapping in sorted(groups.items()):
            pak,name=self.dbas[crc]
            identity=hashlib.sha256((name.lower()+'\n'+namespace).encode()).hexdigest()[:24]
            dest_dba='animations/humans/facials/dialog/glueimport/'+identity+'.dba'
            # Rebuilding a namespace must retain tracks imported in prior passes.
            for dest, old in self.indexed.items():
                if struct.unpack_from('<I',old[3],264)[0] != zlib.crc32(dest_dba.encode()): continue
                candidates=self.source_headers.get(Path(dest).stem,[])
                if len(candidates)!=1: raise ValueError('Cannot reconstruct existing imported facial track')
                original,record=candidates[0]
                if struct.unpack_from('<I',record[3],264)[0]!=crc:
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
        self.archives = []; self.dbas = {}; self.source_headers = defaultdict(list)
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
            self.next_id = max(r[2] for r in self.records) + 1
            self.outputs = {}; self.receipts = []
        except Exception:
            self.close()
            raise
