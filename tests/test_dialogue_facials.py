import struct
import sys
import unittest
import zlib
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from dialogue_facials import (chunks, container, database, select_database, header_path,
                             renamed_header, aliased_controllers, NativeFacialImporter, INDEX)
from facial_rig_adapter import controller_aliases, reverse_speech_mapping, load_reverse_adapter, speech_mapping


class ReverseRigTests(unittest.TestCase):
    def test_reverse_table_inverts_forward_rows_with_one_driver_per_joint(self):
        mapping, rows = reverse_speech_mapping()
        drivers = {}
        for pose, joints in mapping.items():
            for joint in joints:
                self.assertNotIn(joint, drivers)
                drivers[joint] = pose
        self.assertEqual(drivers['mouthOpen_blendWeightVertex'], 'FA_POSE_C_jawDrop')
        self.assertEqual(drivers['lowLipDown_blendWeightVertex'], 'FA_POSE_L_lowLipDepressor')
        unused = [r for r in rows if not r['used']]
        self.assertEqual({r['fa_pose'] for r in unused}, {'FA_POSE_R_lowLipDepressor', 'FA_POSE_L_squint_low', 'FA_POSE_R_squint_low'})
        # Every forward pair is accounted for, used or not.
        forward = {(t, s) for s, ts in speech_mapping().items() for t in ts}
        self.assertTrue(forward <= {(r['fa_pose'], r['kcd1']) for r in rows})
        self.assertTrue(all(r['basis'] for r in rows))

    def test_adapter_keeps_only_joints_a_face_has(self):
        mapping, _ = reverse_speech_mapping()
        native = set(mapping) | {'FA_POSE_C_chinRaise'}
        aliases, report = load_reverse_adapter(None, {'mouthOpen_blendWeightVertex', 'mouthBack_blendWeightVertex'}, native)
        self.assertEqual(aliases, {zlib.crc32(b'FA_POSE_C_jawDrop'): (zlib.crc32(b'mouthOpen_blendWeightVertex'),)})
        self.assertEqual(report['kcd1_without_driver'], ['mouthBack_blendWeightVertex'])
        self.assertIn('FA_POSE_C_chinRaise', report['fa_pose_without_target'])
        self.assertFalse(report['exact_acting_equivalence'])
        with self.assertRaisesRegex(ValueError, 'Missing source'):
            load_reverse_adapter(None, {'mouthOpen_blendWeightVertex'}, {'FA_POSE_C_O'})


def fixture():
    # One shared position/rotation/time track, two independently named clips.
    prefix=bytearray(struct.pack('<4I',1,1,1,2))
    for formats in (7,9,9):
        prefix.extend(struct.pack('<H',1));prefix.extend(struct.pack('<I',1)+bytes((formats-1)*4))
    prefix.extend(struct.pack('<4i',-12,-8,-4,-12));prefix.extend(struct.pack('<I',0))
    prefix.extend(bytes(-len(prefix)%4))
    names=['animations/humans/facials/source/a.caf','animations/humans/facials/source/b.caf']
    meta=bytes(132)+struct.pack('<HH',0,1)
    total=sum(2+len(n)+len(meta)+4 for n in names)
    entries=b''.join(struct.pack('<H',len(n))+n.encode()+meta+struct.pack('<i',total+20*i) for i,n in enumerate(names))
    controllers=struct.pack('<I4i',123,0,0,0,0)+struct.pack('<I4i',456,0,0,0,0)
    data=prefix+entries+controllers;data.extend(bytes(-len(data)%4));data.extend(b'abcdefghijkl')
    return container([(0x100d,0x905,1,bytes(data))])


class FacialTests(unittest.TestCase):
    def native_archive(self, directory):
        data=fixture(); _,entries,_=database(data)
        records=[]; db='animations/humans/facials/native.dba'
        for i,entry in enumerate(entries):
            header=bytearray(404); raw=entry['name'].encode()
            header[4:260]=raw+bytes(256-len(raw))
            struct.pack_into('<I',header,264,zlib.crc32(db.encode()))
            struct.pack_into('<I',header,312,entry['count'])
            records.append((0x3007,0x971,i+1,bytes(header)))
        folder=Path(directory)/'Data/Facials';folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'Facials_english-part0.pak','w') as z:
            z.writestr(INDEX,container(records)); z.writestr(db,data)
        return records

    def test_native_relocation_preserves_rig_curves_and_existing_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline=self.native_archive(directory)
            prior=renamed_header(baseline[0],'animations/humans/facials/dialog/earlier/a.caf','animations/earlier.dba')
            prior=(*prior[:2],3,prior[3])
            importer=NativeFacialImporter(directory,container([*baseline,prior]))
            try:
                importer.add(['dialog/newquest/a.ogg'])
                resources=importer.resources()
                self.assertEqual(chunks(resources[INDEX])[:3],[*baseline,prior])
                dbs=[v for k,v in resources.items() if k.endswith('.dba')]
                self.assertEqual(len(dbs),1)
                _,original,tracks=database(fixture());_,relocated,retained=database(dbs[0])
                self.assertEqual(retained,tracks)
                self.assertEqual(relocated[0]['controllers'],original[0]['controllers'])
                self.assertEqual(relocated[0]['name'],'animations/humans/facials/dialog/newquest/a.caf')
                self.assertFalse(importer.aliases)
            finally:importer.close()
            resumed=NativeFacialImporter(directory,resources[INDEX])
            try:
                resumed.add(['dialog/newquest/b.ogg'])
                self.assertEqual(len(resumed.records),5)
                _,clips,_=database(next(iter(resumed.outputs.values())))
                self.assertEqual({Path(e['name']).stem for e in clips},{'a','b'})
            finally:resumed.close()

    def test_native_relocation_rejects_missing_track_and_corrupt_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline=self.native_archive(directory)
            with self.assertRaisesRegex(ValueError,'baseline'):
                NativeFacialImporter(directory,container(baseline[1:]))
            importer=NativeFacialImporter(directory)
            try:
                with self.assertRaisesRegex(ValueError,'lip-sync track'):
                    importer.add(['dialog/quest/missing.ogg'])
            finally:importer.close()

    def test_native_relocation_by_full_path_is_repeatable_and_guarded(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline=self.native_archive(directory)
            dest='animations/humans/facials/dialog/new/a.caf'
            importer=NativeFacialImporter(directory)
            try:
                # 'elsewhere/b.ogg' shares its stem with a native track but not its path.
                groups,missing=importer.relocation({'dialog/new/a.ogg':'source/a.ogg','dialog/new/b.ogg':'elsewhere/b.ogg'})
                self.assertEqual(missing,['dialog/new/b.ogg'])
                (name,group),=groups.items()
                self.assertTrue(name.startswith(NativeFacialImporter.RELOCATED))
                self.assertEqual(group['tracks'],{'animations/humans/facials/source/a.caf':dest})
                self.assertEqual(importer.index_relocation(groups),1)
                added=importer.records[2]
                self.assertEqual((header_path(added),added[2]),(dest,3))
                self.assertEqual(struct.unpack_from('<I',added[3],264)[0],zlib.crc32(name.encode()))
                payload=importer.relocated_database(group)
                _,clips,tracks=database(payload);_,original,native=database(fixture())
                self.assertEqual([c['name'] for c in clips],[dest])
                self.assertEqual(clips[0]['controllers'],original[0]['controllers'])
                self.assertEqual(tracks,native)
                index=container(importer.records)
                with self.assertRaisesRegex(ValueError,'Invalid relocated recording path'):
                    importer.relocation({'bad.ogg':'source/a.ogg'})
            finally:importer.close()
            resumed=NativeFacialImporter(directory,index)
            try:
                same,_=resumed.relocation({'dialog/new/a.ogg':'source/a.ogg'})
                self.assertEqual(set(same),set(groups))
                self.assertEqual(resumed.index_relocation(same,previous=list(groups)),0)
                self.assertEqual(container(resumed.records),index)
                # A changed rename set moves the clip to a new database and keeps the record identity.
                grown,_=resumed.relocation({'dialog/new/a.ogg':'source/a.ogg','dialog/new/b.ogg':'source/b.ogg'})
                (renamed,)=list(grown)
                self.assertNotEqual(renamed,name)
                self.assertEqual(resumed.index_relocation(grown,previous=list(groups)),2)
                moved=resumed.indexed[dest]
                self.assertEqual((moved[2],struct.unpack_from('<I',moved[3],264)[0]),(3,zlib.crc32(renamed.encode())))
                self.assertEqual(len(resumed.records),4)
                # Nothing relocated any more: the owned records go, the baseline stays.
                self.assertEqual(resumed.index_relocation({},previous=[renamed]),2)
                self.assertEqual(resumed.records,baseline)
            finally:resumed.close()
            foreign=renamed_header(baseline[0],dest,'animations/foreign.dba')
            conflicted=NativeFacialImporter(directory,container([*baseline,(*foreign[:2],9,foreign[3])]))
            try:
                with self.assertRaisesRegex(ValueError,'Conflicting facial track'):
                    conflicted.index_relocation(groups)
            finally:conflicted.close()

    def test_rig_aliases_retain_original_curves_and_rebuild_metadata(self):
        blob = fixture()
        _, before, tracks = database(blob)
        result = select_database(blob, {before[0]['name']: 'dialog/a.caf'}, {123: (789, 987)})
        _, after, retained = database(result)
        self.assertEqual(retained, tracks)
        self.assertEqual(after[0]['count'], 3)
        self.assertEqual(struct.unpack_from('<H', after[0]['metadata'], len(after[0]['metadata'])-2)[0], 3)
        controls = dict((struct.unpack_from('<I', after[0]['controllers'], i)[0], after[0]['controllers'][i+4:i+20])
                        for i in range(0, 60, 20))
        self.assertEqual(set(controls), {123, 789, 987})
        self.assertTrue(all(v == before[0]['controllers'][4:] for v in controls.values()))
        self.assertEqual(after[0]['metadata'][:-2], before[0]['metadata'][:-2])
        with self.assertRaisesRegex(ValueError, 'Competing'):
            aliased_controllers(before[0]['controllers'], {123: (123,)})

    def test_named_rig_contract_rejects_missing_or_competing_controls(self):
        aliases = controller_aliases({'source'}, {'target'}, {'source': ['target']})
        self.assertEqual(aliases, {zlib.crc32(b'source'): (zlib.crc32(b'target'),)})
        with self.assertRaisesRegex(ValueError, 'Missing target'):
            controller_aliases({'source'}, set(), {'source': ['target']})
        with self.assertRaisesRegex(ValueError, 'Competing'):
            controller_aliases({'a','b'}, {'target'}, {'a': ['target'], 'b': ['target']})

    def test_subset_rename_retains_shared_curves_and_controllers(self):
        original=fixture();_,before,tracks=database(original)
        dest='animations/humans/facials/dialog/other_person/a.caf'
        output=select_database(original,{before[1]['name']:dest})
        _,after,new_tracks=database(output)
        self.assertEqual([e['name'] for e in after],[dest])
        self.assertEqual(after[0]['controllers'],before[1]['controllers'])
        self.assertEqual(after[0]['metadata'],before[1]['metadata'])
        self.assertEqual(new_tracks,tracks)
        with self.assertRaisesRegex(ValueError,'missing DBA'):
            select_database(original,{'missing.caf':dest})

    def test_index_translation_keeps_timing_and_native_default_hash(self):
        data=bytearray(404);path=b'animations/humans/facials/source/a.caf'
        data[4:260]=path+bytes(256-len(path));struct.pack_into('<I',data,260,zlib.crc32(path))
        data[268:]=bytes(range(136))
        record=(0x3007,0x971,1,bytes(data))
        result=renamed_header(record,'animations/humans/facials/dialog/actor/a.caf','animations/actor.dba')
        self.assertEqual(header_path(result),'animations/humans/facials/dialog/actor/a.caf')
        self.assertEqual(result[3][268:],record[3][268:])
        self.assertEqual(struct.unpack_from('<II',result[3],260),(0,zlib.crc32(b'animations/actor.dba')))

    def test_bad_chunk_bounds_and_track_layout_fail(self):
        blob=bytearray(fixture());struct.pack_into('<I',blob,28,len(blob)+4)
        with self.assertRaisesRegex(ValueError,'bounds'):
            chunks(blob)
        record=chunks(fixture())[0];data=bytearray(record[3]);struct.pack_into('<I',data,12,9000000)
        with self.assertRaisesRegex(ValueError,'counts'):
            database(container([(record[0],record[1],record[2],bytes(data))]))

if __name__=='__main__':unittest.main()
