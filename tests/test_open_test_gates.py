import sys,struct,unittest
from pathlib import Path
import xml.etree.ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_open_test_gates import open_gates, resolve_models, GRATES

class OpenGateTests(unittest.TestCase):
    def fixture(self):
        records=[]
        for p in (*GRATES,(100,200,30)):
            r=bytearray(104);struct.pack_into('<I',r,0,1)
            struct.pack_into('<6f',r,4,p[0]-1,p[1]-.1,p[2],p[0]+1,p[1]+.1,p[2]+4)
            struct.pack_into('<12f',r,44,1,0,0,p[0],0,1,0,p[1],0,0,1,p[2]);records.append(bytes(r))
        return {'terrain/hlods.dat':struct.pack('<II',2,312)+b''.join(records),
                'terrain/hlods.xml':b'<HLod DataOffset="4" DataSize="316" Radius="8000"/>',
                'objects_mission0.xml':b'<Objects><Entity Name="glue_item_124019" Geometry="gluebuild/setup_props/entity104.cga" Pos="2346.5435,2828.605,105.96074"/><Entity Name="keep" Pos="1,2,3"/></Objects>'}

    def test_only_selected_gate_transforms_and_bounds_change(self):
        f=self.fixture();u,r=open_gates(f,['gluebuild/setup_buildings/mesh1197.cgf'])
        expected=bytearray(f['terrain/hlods.dat'])
        for start in (8,112):
            for off in (12,24,88):struct.pack_into('<f',expected,start+off,struct.unpack_from('<f',expected,start+off)[0]+4)
        self.assertEqual(bytes(expected),u['terrain/hlods.dat'])
        self.assertEqual(E.fromstring(u['objects_mission0.xml'])[1].attrib,E.fromstring(f['objects_mission0.xml'])[1].attrib)
        with self.assertRaisesRegex(ValueError,'Expected two original'):open_gates(u,['gluebuild/setup_buildings/mesh1197.cgf'])

    def test_wrong_mesh_rejected(self):
        with self.assertRaisesRegex(ValueError,'Expected two original'):open_gates(self.fixture(),['other.cgf'])

    def test_rebuilt_model_names_are_verified_by_geometry(self):
        from clothing_regions import Chunk,write_chunks
        def mesh(value):return write_chunks([Chunk(0x1000,0x800,1,value)],{})
        grate,palisade=mesh(b'grate geometry'),mesh(b'palisade geometry')
        files=self.fixture()
        files['objects_mission0.xml']=files['objects_mission0.xml'].replace(b'entity104.cga',b'entity111.cga')
        assets={'new/grate.cgf':grate,'gluebuild/setup_props/entity111.cga':palisade}
        original=lambda n:grate if n.endswith('_grate.cgf') else palisade
        models=resolve_models(files,['new/grate.cgf'],assets.__getitem__,original)
        _,report=open_gates(files,['new/grate.cgf'],*models)
        self.assertEqual(len(report['skalitz_portcullises']),2)
        assets['new/grate.cgf']=mesh(b'wrong object at expected location')
        with self.assertRaisesRegex(ValueError,'geometry differs'):
            resolve_models(files,['new/grate.cgf'],assets.__getitem__,original)

if __name__=='__main__':unittest.main()
