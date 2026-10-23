import struct
import json
import unittest
import xml.etree.ElementTree as E

from setup_static_gate_repair import apply, opened, replacements


class StaticGateTests(unittest.TestCase):
    def fixture(self):
        plan = dict(source_model='source/door.cgf', matrix=(1,0,0,10,0,1,0,20,0,0,1,5),
                    bounds=(8,19.9,5,10,20.1,7), direction=1)
        row=bytearray(104);struct.pack_into('<I',row,0,1)
        struct.pack_into('<6f',row,4,*plan['bounds'])
        struct.pack_into('<12f',row,44,*plan['matrix'])
        other=bytearray(row);struct.pack_into('<f',other,56,50)
        data=struct.pack('<II',2,208)+row+other
        metadata=b'<HLod DataOffset="4" DataSize="212" Radius="100"/>'
        return bytes(data), metadata, [plan]

    def test_rotates_leaf_and_collision_about_hinge_and_repeats_without_changes(self):
        data, metadata, plans=self.fixture(); calls=[]
        check=lambda actual, source:calls.append((actual,source))
        out, meta, count=apply(data,metadata,plans,['converted.cgf'],check)
        self.assertEqual(count,1);self.assertEqual(out[-104:],data[-104:])
        matrix=struct.unpack_from('<12f',out,52)
        self.assertEqual(matrix[3::4],(10,20,5))
        self.assertEqual(matrix[:3],(0,-1,0))
        bounds=struct.unpack_from('<6f',out,12)
        for a,b in zip(bounds,(9.9,18,5,10.1,20,7)):self.assertAlmostEqual(a,b,places=5)
        self.assertGreater(float(E.fromstring(meta).get('Radius')),100)
        self.assertEqual(calls,[('converted.cgf','source/door.cgf')])
        again, again_meta, changed=apply(out,meta,plans,['converted.cgf'],check)
        self.assertEqual((again,again_meta,changed),(out,meta,0))

    def test_conflicting_bounds_are_not_silently_rotated(self):
        data, metadata, plans=self.fixture(); data=bytearray(data)
        struct.pack_into('<f',data,12,0)
        with self.assertRaisesRegex(ValueError,'bounds conflict'):
            apply(data,metadata,plans,['converted.cgf'],lambda *_:None)

    def test_missing_gate_rejected(self):
        data, metadata, plans=self.fixture();plans[0]['matrix']=(1,0,0,99,0,1,0,99,0,0,1,99)
        with self.assertRaisesRegex(ValueError,'Missing reviewed'):
            apply(data,metadata,plans,['converted.cgf'],lambda *_:None)

    def test_duplicate_gate_rejected(self):
        data, metadata, plans=self.fixture();data=data[:112]+data[8:112]
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            apply(data,metadata,plans,['converted.cgf'],lambda *_:None)

    def test_invalid_direction_rejected(self):
        _,_,plans=self.fixture();plans[0]['direction']=0
        with self.assertRaises(ValueError):opened(plans[0])

    def test_geometry_edit_refreshes_valid_lod_marker_without_reencoding(self):
        import test_lod_ratio_metadata as fixtures
        from lod_ratio_metadata import convert, marker_for, validate_marker, MARKER
        terrain, _ = fixtures.fixture()
        data, metadata, plans=self.fixture()
        terrain, data, report=convert(terrain,data)
        marker=marker_for(terrain,data,report)
        updated, hierarchy, _=apply(data,metadata,plans,['converted.cgf'],lambda *_:None)
        files=replacements(terrain,data,updated,hierarchy,marker)
        refreshed=json.loads(files[MARKER])
        validate_marker(terrain,files['terrain/hlods.dat'],refreshed)
        self.assertEqual(refreshed['groups_sha256'],marker['groups_sha256'])
        self.assertEqual(refreshed['transitions'],marker['transitions'])
        self.assertNotEqual(refreshed['hlods_sha256'],marker['hlods_sha256'])
        self.assertEqual(updated[51],data[51])
        with self.assertRaisesRegex(ValueError,'marker does not match'):
            replacements(terrain,updated,data,hierarchy,marker)

    def test_unfinalized_build_remains_for_lod_finalizer(self):
        files=replacements(b'unfinalized',b'old',b'new',b'xml',None)
        self.assertEqual(set(files),{'terrain/hlods.dat','terrain/hlods.xml'})
