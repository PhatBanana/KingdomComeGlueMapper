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

    def test_packaged_equipment_with_normalized_metadata_is_found(self):
        import tempfile,zipfile
        from unittest import mock
        from test_mesh_lod_metadata import fixture
        from clothing_regions import Chunk,read_chunks,write_chunks
        from mesh_lod_metadata import normalize
        from build_rattay_smithery import resolve_brushes
        models=('objects/props/blacksmith_tools/anvil_01.cgf',
                'objects/props/blacksmith_tools/water_container.cgf',
                'objects/props/wooden_bins/barrels/barrel_02/barrel_02_metal_pieces.cgf')
        sources={m:write_chunks(read_chunks(fixture())+[Chunk(0x1018,0x800,10,m.encode())],{}) for m in models}
        meshes=['new/anvil.cgf','new/water.cgf','new/barrel.cgf','unrelated.cgf']
        data,hierarchy,_,_=self.fixture()
        with tempfile.TemporaryDirectory() as t:
            (Path(t)/'Data').mkdir()
            with zipfile.ZipFile(Path(t)/'Data/level.pak','w') as z:
                for name,model in zip(meshes,models):z.writestr(name,normalize(sources[model]))
                z.writestr('unrelated.cgf',write_chunks([Chunk(0x1000,0x800,1,b'other')],{}))
            files={'terrain/hlods.dat':data,'terrain/hlods.xml':hierarchy}
            with mock.patch('build_open_test_gates.source_geometry',lambda source,names:dict(sources)):
                self.assertEqual(resolve_brushes(files,meshes,Path(t),None),set(meshes[:3]))
            with zipfile.ZipFile(Path(t)/'Data/level.pak','w') as z:
                for name,model in zip(meshes,models):
                    chunks=read_chunks(normalize(sources[model]));body=bytearray(next(c.data for c in chunks if c.id==2));body[24]^=1
                    z.writestr(name,write_chunks(chunks,{2:bytes(body)}))
            with mock.patch('build_open_test_gates.source_geometry',lambda source,names:dict(sources)):
                with self.assertRaisesRegex(ValueError,'Missing original Rattay equipment geometry'):
                    resolve_brushes(files,meshes,Path(t),None)


if __name__=='__main__':unittest.main()
