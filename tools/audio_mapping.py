"""Inventory owned KCD1 recordings against KCD2's dialogue and music contracts.

Never overrides native voices, FMOD banks or the global adaptive music script.
Missing recordings and unconverted music state bindings stay explicit.
"""
from collections import defaultdict
from contextlib import ExitStack
import hashlib
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET
import zipfile

from campaign_sources import retail_sources
from upgrade_map import read


def sqcb_index(data):
    """Validate the shared SQCB1.00 directory and each embedded Ogg stream."""
    if data[:16] != 'SQCB1.00'.encode('utf-16le') or len(data) < 20:
        raise ValueError('Unsupported SQCB header')
    count, = struct.unpack_from('<I', data, 16)
    # Native SYSTEM/AAA, SILENCE and ZZZ contain an empty directory.
    if count > 10000:
        raise ValueError('Invalid SQCB member count')
    cursor, members, names = 20, [], set()
    for _ in range(count):
        end = cursor
        while end + 2 <= len(data) and data[end:end+2] != b'\0\0':
            end += 2
        if end + 10 > len(data):
            raise ValueError('Truncated SQCB directory')
        name = data[cursor:end].decode('utf-16le')
        offset, size = struct.unpack_from('<II', data, end + 2)
        cursor = end + 10
        if (not re.fullmatch(r'[\w.() -]+\.ogg', name, re.I)
                or name.lower() in names or size < 4 or offset + size > len(data)):
            raise ValueError('Invalid SQCB member: ' + name)
        names.add(name.lower())
        members.append(dict(name=name, offset=offset, size=size))
    previous = cursor
    for member in sorted(members, key=lambda m: m['offset']):
        offset, size = member['offset'], member['size']
        if offset < previous or data[offset:offset+4] != b'OggS':
            raise ValueError('Overlapping or non-Ogg SQCB member')
        previous = offset + size
    return members


def scenes(data):
    script = data.decode('utf-8-sig').replace('\r', '')
    starts = list(re.finditer(r'^SCENE ([^\n]+)\n', script, re.M))
    result = {}
    for i, match in enumerate(starts):
        name = match[1].strip()
        if name.lower() in result:
            raise ValueError('Duplicate music scene: ' + name)
        body = script[match.start():starts[i+1].start() if i+1 < len(starts) else len(script)]
        result[name.lower()] = dict(name=name,
            variables=sorted(set(re.findall(r'%[\w@#&.]+', body))),
            sha256=hashlib.sha256(body.encode()).hexdigest())
    return script.splitlines()[0], result


class EnglishRecordings:
    """Resolve regular English banks including owned DLC; never mix HD variants."""
    def __init__(self, game):
        self.game = Path(game)
        self.stack = ExitStack()
        self.members = defaultdict(list)

    def __enter__(self):
        try:
            for path in sorted((self.game/'Localization').glob('*.pak')):
                if not re.fullmatch(r'(?:IPL_)?English(?:-part\d+|_DLC\d+)?\.pak', path.name, re.I):
                    continue
                archive = self.stack.enter_context(zipfile.ZipFile(path))
                for info in archive.infolist():
                    name = info.filename.replace('\\', '/').lower()
                    if name.endswith('.ogg'):
                        self.members[name].append((path, archive, info))
            return self
        except Exception:
            self.stack.close()
            raise

    def __exit__(self, *args):
        self.stack.close()

    def locations(self, name):
        return [dict(archive=p.relative_to(self.game).as_posix(), entry=i.filename,
                     bytes=i.file_size, crc32=f'{i.CRC:08x}')
                for p, _, i in self.members.get(name.lower(), [])]

    def extract(self, name):
        candidates = self.members.get(name.lower(), [])
        if not candidates:
            raise ValueError('Missing English recording: ' + name)
        payloads = [read(a, i.filename) for _, a, i in candidates]
        if len({hashlib.sha256(b).digest() for b in payloads}) != 1:
            raise ValueError('Ambiguous English recording: ' + name)
        if not payloads[0].startswith(b'OggS'):
            raise ValueError('Not an Ogg recording: ' + name)
        return payloads[0]


def dialogue_catalog(source, target, recordings):
    paths = {n: ('Tables.pak', 'Libs/Tables/text/'+n+'.xml')
             for n in ('response', 'v_response_wave_file_recorded')}
    paths['roles'] = ('Tables.pak', 'Libs/Tables/rpg/role.xml')
    sources = retail_sources(source, paths)
    rows = {n: [r.attrib for r in ET.fromstring(s['data']).iter('row')]
            for n, s in sources.items()}
    with zipfile.ZipFile(Path(source)/'Localization/English_xml.pak') as archive:
        strings = {r[0].text: r[1].text for r in ET.fromstring(read(archive, 'text_ui_dialog.xml')).iter('Row') if len(r)>1}
    with zipfile.ZipFile(Path(target)/'Data/Tables.pak') as archive:
        voices = {v.get('abbreviation'): v.get('voice_technical_name')
                  for v in ET.fromstring(read(archive, 'Libs/Tables/skald/voice.xml')).iter('voice')}
    roles = {r['role_id']: r['role_name'] for r in rows['roles']}
    # Reviewed source roles: Henry, Zora's quest role, female horse merchant.
    selected = {'3': ('Henry', '108'), '941': ('Zora', '68'), '2535': ('Zora', '68')}
    waves = defaultdict(list)
    for wave in rows['v_response_wave_file_recorded']:
        waves[wave['sequence_line_id']].append(wave)
    result = []
    for row in rows['response']:
        if row['role_id'] not in selected:
            continue
        speaker, voice_id = selected[row['role_id']]
        found = [w for w in waves[row['sequence_line_id']] if w['voice_id'] == voice_id]
        if len(found)>1:
            raise ValueError('Ambiguous actor recording: '+row['sequence_line_id'])
        record = dict(speaker=speaker, source_role=roles[row['role_id']],
            sequence_line_id=row['sequence_line_id'], string_name=row['string_name'],
            text=strings.get(row['string_name']), status='missing_recording')
        if found:
            wave=found[0]
            path='dialog/'+wave['path'].zfill(6)+'/'+wave['wave_file']+'.ogg'
            abbreviation=wave['wave_file'].split('_',1)[0]
            record.update(source_path=path, wave_file=wave['wave_file'],
                target_voice=voices.get(abbreviation), source_locations=recordings.locations(path))
            record['status'] = ('mapped' if record['source_locations'] and record['text'] and record['target_voice']
                                else 'missing_recording_or_text_or_voice')
        result.append(record)
    return result, {n: dict(entry=s['entry'], candidates=s['candidates']) for n,s in sources.items()}


def music_catalog(source, target):
    with zipfile.ZipFile(Path(target)/'Data/Music.pak') as archive:
        target_version, native = scenes(read(archive, 'Music/kcd/main_layer.widsh'))
    with zipfile.ZipFile(Path(source)/'Data/Music.pak') as archive:
        source_version, original = scenes(read(archive, 'Music/kcd/main_layer.widsh'))
        result=[]
        for name in archive.namelist():
            if not name.lower().endswith('.sqcb'):
                continue
            data=read(archive,name)
            identity=name.removeprefix('Music/kcd/')[:-5].lower()
            scene=original.get(identity)
            result.append(dict(source_path=name, bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(), segments=sqcb_index(data),
                source_scene=scene, native_name_collision=identity in native,
                status='requires_state_conversion' if scene else 'missing_source_scene'))
    return dict(source_version=source_version, target_version=target_version,
                containers_compatible=True, runtime_bound=False, tracks=result)
