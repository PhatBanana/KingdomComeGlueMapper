import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import world_speech_facials as F
from dialogue_facials import INDEX, NativeFacialImporter, chunks, container, database, header_path, renamed_header
from dialogue_dubbing import DEPOT
from setup_campaign import digest
from world_speech_audio import upgrade as relocate_audio
from test_world_speech_audio import fixture as graphs, native_scripts, write_pak

# The audio pass moves dialog/open_world/... under dialog/test/open_world/... in this fixture.
TRACKED = 'dialog/open_world/hello/abc_greet_Test.ogg'
UNTRACKED = 'dialog/open_world/hello/xyz_greet_Test.ogg'
TRACK = 'animations/humans/facials/dialog/open_world/hello/abc_greet_test.caf'
OTHER = 'animations/humans/facials/other/keep.caf'
MOVED = 'animations/humans/facials/dialog/test/open_world/hello/abc_greet_test.caf'
DBA = 'animations/humans/facials/dialog/open_world/hello.dba'
PRIOR_TRACK = 'animations/humans/facials/dialog/kcd1_travel/gm_quest/keep.caf'
PRIOR_DBA = 'animations/humans/facials/dialog/glueimport/prior.dba'
SHARD = F.SHARD.format(0)


def dba(names):
    """A facial DBA with one shared track and one clip per name (after test_dialogue_facials.fixture)."""
    prefix = bytearray(struct.pack('<4I', 1, 1, 1, len(names)))
    for formats in (7, 9, 9):
        prefix.extend(struct.pack('<H', 1)); prefix.extend(struct.pack('<I', 1) + bytes((formats-1)*4))
    prefix.extend(struct.pack('<4i', -12, -8, -4, -12)); prefix.extend(struct.pack('<I', 0))
    prefix.extend(bytes(-len(prefix) % 4))
    meta = bytes(132) + struct.pack('<HH', 0, 1)
    total = sum(2+len(n)+len(meta)+4 for n in names)
    entries = b''.join(struct.pack('<H', len(n)) + n.encode() + meta + struct.pack('<i', total+20*i) for i, n in enumerate(names))
    controllers = b''.join(struct.pack('<I4i', 100+i, 0, 0, 0, 0) for i in range(len(names)))
    data = prefix + entries + controllers; data.extend(bytes(-len(data) % 4)); data.extend(b'abcdefghijkl')
    return container([(0x100d, 0x905, 1, bytes(data))])


def native_facials(target, names, db=DBA):
    data = dba(names); _, entries, _ = database(data)
    records = []
    for i, entry in enumerate(entries):
        header = bytearray(404); raw = entry['name'].encode()
        header[4:260] = raw + bytes(256-len(raw))
        struct.pack_into('<I', header, 264, zlib.crc32(db.encode()))
        struct.pack_into('<I', header, 312, entry['count'])
        records.append((0x3007, 0x971, i+1, bytes(header)))
    folder = Path(target)/'Data/Facials'; folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder/'Facials_english-part0.pak', 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(INDEX, container(records)); z.writestr(db, data)
    return records, data


def build(root, foreign=None):
    """A package whose world graphs relocate native speech, plus the matching game folder."""
    package, target = root/'mod', root/'game'
    native_scripts(target)
    write_pak(package/'Data/gluemappertravel.pak', graphs())
    rows = ''.join(f'<DialogueDubbing FileHash="{zlib.crc32(n.rsplit("/", 1)[-1][:-4].encode())}" Duration="1"/>'
                   for n in (TRACKED, UNTRACKED))
    write_pak(package/'Localization/English.pak', {DEPOT: ('<Root><DialogueDubbingData>'+rows+'</DialogueDubbingData></Root>').encode(),
                                                   'dialog/custom/keep.ogg': b'OggSkeep'})
    write_pak(target/'Localization/English.pak', {TRACKED: b'OggSoriginal', UNTRACKED: b'OggSother'})
    records, data = native_facials(target, [TRACK, OTHER])
    # A KCD1-style import from an earlier recipe step must survive untouched.
    prior = renamed_header(records[1], PRIOR_TRACK, PRIOR_DBA)
    prior = (*prior[:2], 3, prior[3])
    index = [*records, prior]
    if foreign:
        intruder = renamed_header(records[0], foreign, PRIOR_DBA)
        index.append((*intruder[:2], 4, intruder[3]))
    write_pak(package/F.FACIALS, {INDEX: container(index), PRIOR_DBA: data})
    return package, target, index, data


def read_member(path, name):
    with zipfile.ZipFile(path) as z:
        return z.read(name)


def snapshot(package, names):
    return {n: (package/n).read_bytes() for n in names}


class WorldSpeechFacialTests(unittest.TestCase):
    def test_runs_only_after_the_audio_relocation(self):
        with tempfile.TemporaryDirectory() as directory:
            package, target, _, _ = build(Path(directory))
            with self.assertRaisesRegex(ValueError, 'not packaged yet'):
                F.upgrade(package, target)

    def test_indexes_relocated_tracks_once_and_keeps_other_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            package, target, index, data = build(Path(directory))
            relocate_audio(package, target)
            progress = []
            files, removed, report = F.upgrade(package, target, lambda *a: progress.append(a))
            self.assertEqual(removed, [])
            self.assertEqual(set(files), {F.FACIALS, F.REPORT, SHARD})
            self.assertEqual(files, {n: digest(package/n) for n in files})
            self.assertEqual((report['recordings'], report['facial_tracks'], report['missing_tracks'], report['databases']),
                             (2, 1, 1, 1))
            self.assertEqual(report['archives'], [SHARD])
            self.assertEqual(report['changed'], dict(index_records=1, archives=True, removed=[]))
            self.assertEqual((report['native_headers'], report['index_headers']), (2, 4))
            self.assertFalse(report['runtime_verified'])
            self.assertEqual(report['scopes'][0]['destination_scope'], 'dialog/test/open_world/')
            self.assertEqual((report['scopes'][0]['facial_tracks'], report['scopes'][0]['missing_tracks']), (1, 1))
            self.assertTrue(progress and progress[-1][1] == progress[-1][2] == 1, progress)
            with zipfile.ZipFile(package/F.FACIALS) as z:
                records = chunks(z.read(INDEX))
                self.assertEqual(z.read(PRIOR_DBA), data)
            self.assertEqual(records[:3], index)
            self.assertEqual(len(records), 4)
            added = records[3]
            self.assertEqual(header_path(added), MOVED)
            self.assertEqual(added[2], 4)
            with zipfile.ZipFile(package/SHARD) as z:
                infos = z.infolist()
                self.assertEqual(len(infos), 1)
                self.assertEqual(infos[0].compress_type, zipfile.ZIP_DEFLATED)
                self.assertTrue(infos[0].filename.startswith(NativeFacialImporter.RELOCATED))
                self.assertEqual(struct.unpack_from('<I', added[3], 264)[0], zlib.crc32(infos[0].filename.encode()))
                _, clips, tracks = database(z.read(infos[0].filename))
            _, original, native_tracks = database(data)
            self.assertEqual([c['name'] for c in clips], [MOVED])
            self.assertEqual(clips[0]['controllers'], original[0]['controllers'])
            self.assertEqual(tracks, native_tracks)
            details = json.loads((package/F.REPORT).read_text(encoding='utf-8'))
            self.assertEqual(details['missing_tracks'], ['dialog/test/open_world/hello/xyz_greet_test.ogg'])
            self.assertEqual(details['databases'][0]['source'], DBA)
            self.assertEqual(details['databases'][0]['archive'], SHARD)
            # A second pass recognises its own output and changes nothing.
            before = snapshot(package, files)
            again, removed, repeat = F.upgrade(package, target)
            self.assertEqual(again, files)
            self.assertEqual(removed, [])
            self.assertEqual(repeat['changed'], dict(index_records=0, archives=False, removed=[]))
            self.assertEqual(snapshot(package, files), before)

    def test_stage_writes_a_new_folder_and_honours_the_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package, target, _, _ = build(root)
            relocate_audio(package, target)
            untouched = snapshot(package, [F.FACIALS])
            report = F.stage(package, target, root/'out')
            self.assertEqual(report['facial_tracks'], 1)
            self.assertEqual(sorted(p.relative_to(root/'out').as_posix() for p in (root/'out').rglob('*') if p.is_file()),
                             sorted([F.FACIALS, SHARD, F.REPORT, 'report.json']))
            self.assertEqual(snapshot(package, [F.FACIALS]), untouched)
            self.assertFalse((package/SHARD).exists())
            with self.assertRaises(FileExistsError):
                F.stage(package, target, root/'out')
            partial = F.stage(package, target, root/'partial', only='dialog/test/open_world/hello/xyz')
            self.assertEqual((partial['facial_tracks'], partial['missing_tracks'], partial['databases'], partial['archives']),
                             (0, 1, 0, []))

    def test_foreign_track_at_a_relocated_path_is_a_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            package, target, _, _ = build(Path(directory), foreign=MOVED)
            relocate_audio(package, target)
            with self.assertRaisesRegex(ValueError, 'Conflicting facial track'):
                F.upgrade(package, target)

    def test_lines_no_longer_relocated_lose_their_entries_and_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            package, target, index, _ = build(Path(directory))
            relocate_audio(package, target)
            F.upgrade(package, target)
            self.assertTrue((package/SHARD).exists())
            silenced = graphs()
            silenced['Quests/entry/world/native.xml'] = silenced['Quests/entry/world/native.xml'].replace(
                b'<Response><Text StringName="greet_Test"/></Response>', b'')
            write_pak(package/'Data/gluemappertravel.pak', silenced)
            files, removed, report = F.upgrade(package, target)
            self.assertEqual(removed, [SHARD])
            self.assertFalse((package/SHARD).exists())
            self.assertEqual(set(files), {F.FACIALS, F.REPORT})
            self.assertEqual((report['recordings'], report['facial_tracks'], report['databases']), (0, 0, 0))
            self.assertEqual(report['changed'], dict(index_records=1, archives=True, removed=[SHARD]))
            with zipfile.ZipFile(package/F.FACIALS) as z:
                self.assertEqual(chunks(z.read(INDEX)), index)

    def test_shards_split_at_the_byte_bound_and_commit_together(self):
        from unittest.mock import patch
        # One 300-byte payload plus the 1 MiB margin fits; a second one does not.
        with tempfile.TemporaryDirectory() as directory, patch.object(F, 'SHARD_BYTES', 2**20 + 320):
            writer = F.Shards(directory)
            writer.add('a.dba', b'a' * 300)
            writer.add('b.dba', b'b' * 300)
            with self.assertRaisesRegex(ValueError, 'exceeds the shard limit'):
                writer.add('c.dba', b'c' * 1024)
            self.assertEqual(writer.commit(), [F.SHARD.format(0), F.SHARD.format(1)])
            found = {}
            for relative in F.shards(directory):
                with zipfile.ZipFile(Path(directory)/relative) as z:
                    found.update({n: relative for n in z.namelist()})
            self.assertEqual(found, {'a.dba': F.SHARD.format(0), 'b.dba': F.SHARD.format(1)})
            self.assertEqual(F.members(directory), found)
            self.assertFalse(list(Path(directory).rglob('*.facials-pending')))

    def test_converted_faces_get_retargeted_controllers_and_repeat_cleanly(self):
        from unittest.mock import patch
        mouth = zlib.crc32(b'mouthOpen_blendWeightVertex')
        rig = dict(aliases=1, kcd1_without_driver=[], fa_pose_without_target=[], rows=[], amplitude='unchanged')
        with tempfile.TemporaryDirectory() as directory:
            package, target, index, data = build(Path(directory))
            relocate_audio(package, target)
            plain, _, plain_report = F.upgrade(package, target)
            self.assertIsNone(plain_report['rig_retarget'])
            plain_dba = F.members(package)
            # The fixture clip's controller 100 stands for an FA_POSE pose.
            with patch.object(F, 'kcd1_face_joints', return_value=['mouthOpen_blendWeightVertex']), \
                 patch.object(F, 'load_reverse_adapter', return_value=({100: (mouth,)}, rig)):
                files, removed, report = F.upgrade(package, target)
                self.assertEqual(report['rig_retarget']['aliases'], 1)
                self.assertEqual(report['changed']['archives'], True)
                self.assertNotEqual(set(F.members(package)), set(plain_dba))
                (name,) = F.members(package)
                with zipfile.ZipFile(package/SHARD) as z:
                    _, clips, tracks = database(z.read(name))
                _, original, native_tracks = database(data)
                self.assertEqual(tracks, native_tracks)
                self.assertEqual(clips[0]['count'], 2)
                blocks = {struct.unpack_from('<I', clips[0]['controllers'], i)[0]: clips[0]['controllers'][i+4:i+20]
                          for i in range(0, 40, 20)}
                self.assertEqual(blocks, {100: original[0]['controllers'][4:], mouth: original[0]['controllers'][4:]})
                with zipfile.ZipFile(package/F.FACIALS) as z:
                    records = chunks(z.read(INDEX))
                self.assertEqual(records[:3], index)
                moved = records[3]
                self.assertEqual((header_path(moved), struct.unpack_from('<I', moved[3], 312)[0]), (MOVED, 2))
                self.assertEqual(struct.unpack_from('<I', moved[3], 264)[0], zlib.crc32(name.encode()))
                before = snapshot(package, files)
                again, removed, repeat = F.upgrade(package, target)
                self.assertEqual(repeat['changed'], dict(index_records=0, archives=False, removed=[]))
                self.assertEqual(snapshot(package, files), before)
            # Without converted faces the plain copy and native count come back.
            files, removed, report = F.upgrade(package, target)
            self.assertEqual(set(F.members(package)), set(plain_dba))
            with zipfile.ZipFile(package/F.FACIALS) as z:
                self.assertEqual(struct.unpack_from('<I', chunks(z.read(INDEX))[3][3], 312)[0], 1)
            self.assertEqual(files, plain)

    def test_gesture_database_is_overridden_with_aliases_and_restored_without(self):
        from unittest.mock import patch
        from dialogue_facials import GESTURES, GESTURES_MEMBER
        mouth = zlib.crc32(b'mouthOpen_blendWeightVertex')
        rig = dict(aliases=1, kcd1_without_driver=[], fa_pose_without_target=[], rows=[], amplitude='unchanged')
        idle = 'animations/humans/facials/gestures/fa_idle_happy1_01.caf'
        with tempfile.TemporaryDirectory() as directory:
            package, target, _, data = build(Path(directory))
            # Native baseline: the line clips plus one mood idle in the shared gesture database.
            gesture_blob = dba([idle])
            records = chunks(read_member(target/'Data/Facials/Facials_english-part0.pak', INDEX))
            header = bytearray(404); header[4:4+len(idle)] = idle.encode()
            struct.pack_into('<I', header, 264, zlib.crc32(GESTURES.encode())); struct.pack_into('<I', header, 312, 1)
            baseline = [*records, (0x3007, 0x971, 3, bytes(header))]
            with zipfile.ZipFile(target/'Data/Facials/Facials_english-part0.pak', 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr(INDEX, container(baseline)); z.writestr(DBA, data); z.writestr(GESTURES_MEMBER, gesture_blob)
            write_pak(package/F.FACIALS, {INDEX: container(baseline)})
            relocate_audio(package, target)
            with patch.object(F, 'kcd1_face_joints', return_value=['mouthOpen_blendWeightVertex']), \
                 patch.object(F, 'load_reverse_adapter', return_value=({100: (mouth,)}, rig)):
                files, _, report = F.upgrade(package, target)
                self.assertEqual(report['rig_retarget']['gesture_override']['member'], GESTURES_MEMBER)
                with zipfile.ZipFile(package/F.FACIALS) as z:
                    _, clips, tracks = database(z.read(GESTURES_MEMBER))
                    index = chunks(z.read(INDEX))
                self.assertEqual(clips[0]['count'], 2)
                self.assertEqual(tracks, database(gesture_blob)[2])
                recounted = next(r for r in index if header_path(r) == idle)
                self.assertEqual(struct.unpack_from('<I', recounted[3], 312)[0], 2)
                # The relaxed baseline check accepts exactly this difference on a later pass.
                NativeFacialImporter(target, container(index)).close()
                before = snapshot(package, files)
                self.assertEqual(F.upgrade(package, target)[2]['changed']['index_records'], 0)
                self.assertEqual(snapshot(package, files), before)
            F.upgrade(package, target)
            with zipfile.ZipFile(package/F.FACIALS) as z:
                self.assertNotIn(GESTURES_MEMBER, z.namelist())
                self.assertEqual(chunks(z.read(INDEX))[:3], baseline)
            tampered = list(baseline); data2 = bytearray(tampered[0][3]); struct.pack_into('<I', data2, 312, 9)
            tampered[0] = (*tampered[0][:3], bytes(data2))
            with self.assertRaisesRegex(ValueError, 'baseline'):
                NativeFacialImporter(target, container(tampered))

    def test_package_without_relocated_world_is_skipped_without_a_game(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)/'mod'
            write_pak(package/'Data/gluemappertravel.pak', {'Quests/demo.xml': b'<Database/>'})
            files, removed, report = F.upgrade(package, None)
            self.assertEqual((files, removed), ({}, []))
            self.assertEqual(report['reason'], 'no relocated native world')


if __name__ == '__main__':
    unittest.main()
