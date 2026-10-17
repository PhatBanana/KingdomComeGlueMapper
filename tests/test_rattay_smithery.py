import struct
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_rattay_smithery import BRUSHES, STATIONS, remove_old_brushes
from vegetation import verify_target_hlods


class SmitheryTests(unittest.TestCase):
    def fixture(self):
        meshes=sorted(BRUSHES)+['unrelated.cgf']
        blocks=[]
        for station in STATIONS:
            records=[]
            for mesh in range(4):
                r=bytearray(104);struct.pack_into('<I',r,0,1)
                struct.pack_into('<H',r,40,mesh)
                for off,value in zip((56,72,88),station[4]):struct.pack_into('<f',r,off,value)
                records.append(bytes(r))
            blocks.append(records)
        root=ET.Element('HLods');data=bytearray(struct.pack('<I',2))
        for block in blocks:
            payload=b''.join(block)
            ET.SubElement(root,'HLod',DataOffset=str(len(data)),DataSize=str(4+len(payload)))
            data.extend(struct.pack('<I',len(payload))+payload)
        return bytes(data),ET.tostring(root),meshes,blocks

    def test_removes_only_equipment_and_reindexes_blocks(self):
        data,hierarchy,meshes,blocks=self.fixture()
        result,tree,removed=remove_old_brushes(data,hierarchy,meshes)
        self.assertEqual(len(removed),6)
        self.assertEqual(verify_target_hlods(result),{1:2})
        self.assertEqual(result,struct.pack('<I',2)+b''.join(struct.pack('<I',104)+b[-1] for b in blocks))
        self.assertEqual([int(e.get('DataOffset')) for e in ET.fromstring(tree)],[4,112])
        with self.assertRaisesRegex(ValueError,'Expected six'):
            remove_old_brushes(result,tree,meshes)

    def test_does_not_remove_same_mesh_outside_workshop(self):
        data,hierarchy,meshes,_=self.fixture()
        data=bytearray(data);struct.pack_into('<f',data,8+56,0)
        with self.assertRaisesRegex(ValueError,'Expected six'):
            remove_old_brushes(data,hierarchy,meshes)

    def test_resolved_mesh_names_survive_rebuild_numbering_changes(self):
        data,hierarchy,meshes,_=self.fixture()
        renamed=['new/anvil.cgf','new/tub.cgf','new/barrel.cgf','unrelated.cgf']
        result,_,removed=remove_old_brushes(data,hierarchy,renamed,set(renamed[:3]))
        self.assertEqual(len(removed),6)
        self.assertEqual(verify_target_hlods(result),{1:2})


if __name__=='__main__':unittest.main()
