"""Lighting translation regressions independent of installed games."""
from pathlib import Path
import struct
import sys
import unittest
import xml.etree.ElementTree as E

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from lighting_cubemaps import time_bracket, float_dds, float_mips, atlas_mips, standard_cube, cry_cube_members
from world_lighting import defaults, overlay, bounds, reflex_times, shadow_spec, probe_lighting_environment, native_probe_areas
from world_lighting import global_probe_fog, disable_global_probe_fog


class LightingTests(unittest.TestCase):
    def test_native_probe_areas_do_not_reinterpret_bake_offset_as_influence_origin(self):
        native=E.fromstring('<Properties><Options bIgnoresVisAreas="0" bAffectsThisAreaOnly="0" bDeferredClipBounds="0"/></Properties>')
        p=E.fromstring('<Properties BoxSizeX="7.42" BoxSizeY="22.2" GenOffsetY="-7"><Options bIgnoresVisAreas="1" bAffectsThisAreaOnly="0" bDeferredClipBounds="1" SortPriority="11"/></Properties>')
        result=native_probe_areas(p,native)
        self.assertEqual(p.attrib,{'BoxSizeX':'7.42','BoxSizeY':'22.2','GenOffsetY':'-7'})
        self.assertEqual(p.find('Options').attrib,dict(native.find('Options').attrib,SortPriority='11'))
        self.assertEqual(result['source']['bIgnoresVisAreas'],'1')
        native_probe_areas(p,native,linked=True)
        self.assertEqual(p.find('Options').get('bDeferredClipBounds'),'1')
        self.assertEqual(p.find('Options').get('bAffectsThisAreaOnly'),'0')

    def test_global_probe_leaves_volumetric_fog(self):
        p=E.fromstring('<Properties BoxSizeX="99999"><Options bVolumetricFog="1" SortPriority="3"/></Properties>')
        self.assertEqual(global_probe_fog(p),'1')
        self.assertEqual(p.find('Options').attrib,{'bVolumetricFog':'0','SortPriority':'3'})
        default=E.fromstring('<Properties BoxSizeX="99999"/>')  # unauthored: the engine default is 1
        self.assertIsNone(global_probe_fog(default))
        self.assertEqual(default.find('Options').get('bVolumetricFog'),'0')

    def test_only_the_packaged_global_probe_leaves_volumetric_fog_once(self):
        mission=(b'<Objects>'
                 b'<Entity Name="gm_lighting_26965" EntityClass="EnvironmentLight" PerInstanceStreamable="0"><Properties BoxSizeX="99999">'
                 b'<Options bVolumetricFog="1"/></Properties></Entity>'
                 b'<Entity Name="gm_lighting_7" EntityClass="EnvironmentLight" PerInstanceStreamable="1"><Properties><Options bVolumetricFog="1"/></Properties></Entity>'
                 b'<Entity Name="Env_Probe_UI_01" EntityClass="EnvironmentLight" PerInstanceStreamable="0"><Properties><Options bVolumetricFog="1"/></Properties></Entity>'
                 b'<Entity Name="gm_lighting_9" EntityClass="Light" PerInstanceStreamable="0"><Properties><Options bVolumetricFog="1"/></Properties></Entity>'
                 b'</Objects>')
        result,report=disable_global_probe_fog(mission)
        fog={e.get('Name'):e.find('Properties/Options').get('bVolumetricFog') for e in E.fromstring(result)}
        # Local converted probes keep the default like Trosky's; native entities and other classes are untouched.
        self.assertEqual(fog,{'gm_lighting_26965':'0','gm_lighting_7':'1','Env_Probe_UI_01':'1','gm_lighting_9':'1'})
        self.assertEqual(report['probes'],['gm_lighting_26965'])
        self.assertEqual(disable_global_probe_fog(result),(result,dict(report,probes=[])))

    def test_probe_only_world_does_not_enable_empty_voxel_gi(self):
        original=b'<Mission><Environment><Total_Illumination_v2 Active="1" IntegrationMode="1"/><Fog value="kept"/></Environment><TimeOfDay value="kept"/></Mission>'
        result=E.fromstring(probe_lighting_environment(original))
        self.assertEqual(result.find('Environment/Total_Illumination_v2').attrib,{'Active':'0','IntegrationMode':'1'})
        self.assertEqual(result.find('Environment/Fog').get('value'),'kept')
        self.assertEqual(result.find('TimeOfDay').get('value'),'kept')
        with self.assertRaises(ValueError):probe_lighting_environment(b'<Mission/>')

    def test_experimental_shadow_tier_is_translated(self):
        self.assertEqual(shadow_spec('7'),'5')
        self.assertEqual(shadow_spec('0'),'0')
        self.assertEqual(shadow_spec('4'),'4')
        with self.assertRaises(ValueError):shadow_spec('13')
    def test_midnight_interpolates_night_samples(self):
        self.assertEqual(time_bracket((180,780,1380),0),(2,0,.25))
        self.assertEqual(time_bracket((180,780,1380),780),(1,2,0))

    def test_literal_native_defaults_and_supported_overlay(self):
        schema=defaults(b'''Light={Properties={bActive=true, Box=10,
            Color={clrDiffuse={x=1,y=1,z=1}, fVolumetricMultiplier=0.012},
            Options={esGIMode="StaticLight", bOff=false}}}''')
        overlay(schema,E.fromstring('<Properties Box="7" obsolete="1"><Color clrDiffuse=".2,.3,.4"/></Properties>'),True)
        self.assertEqual(schema.get('Box'),'7')
        self.assertIsNone(schema.get('obsolete'))
        self.assertEqual(schema.find('Color').get('clrDiffuse'),'.2,.3,.4')
        self.assertEqual(schema.find('Color').get('fVolumetricMultiplier'),'0.012')
        self.assertEqual(schema.get('bActive'),'1')

    def test_rotated_probe_has_world_aligned_relative_stream_bounds(self):
        p=E.Element('Properties',BoxSizeX='2',BoxSizeY='10',BoxSizeZ='4')
        lo,hi=bounds(p,(2**-.5,0,0,2**-.5),(1,1,1),'EnvironmentLight')
        np.testing.assert_allclose(list(map(float,hi.split(','))),(5,1,2),atol=1e-6)
        np.testing.assert_allclose(list(map(float,lo.split(','))),(-5,-1,-2),atol=1e-6)

    def test_prefiltered_mips_survive_resampling(self):
        levels=[np.full((6,32>>i,32>>i,4),float(i+1),np.float32) for i in range(4)]
        result=atlas_mips(levels)
        self.assertEqual([l.shape[1] for l in result],[128,64,32,16,8,4])
        for i,level in enumerate(result):
            np.testing.assert_allclose(level[:,:,:,:3],1+i*3/5,atol=1e-6)
        # Generating ordinary image mips from the top level would yield 1 at
        # every level and destroy the source's rough reflection bake.

    def test_float_cube_keeps_faces_and_all_mips(self):
        levels=[]
        for i in range(6):
            level=np.empty((6,128>>i,128>>i,4),np.float32)
            for face in range(6):level[face]=face*10+i
            levels.append(level)
        decoded=float_mips(float_dds(levels))
        for a,b in zip(levels,decoded):np.testing.assert_array_equal(a,b)

    def test_split_bc6_cube_is_face_major_after_reassembly(self):
        header=bytearray(float_dds([np.ones((6,128,128,4),np.float32)])[:148])
        struct.pack_into('<II',header,12,8,8)
        struct.pack_into('<I',header,28,2)
        struct.pack_into('<I',header,128,95)
        struct.pack_into('<I',header,140,6)
        base=bytes(header)+b''.join(bytes([face+10])*16 for face in range(6))
        high=b''.join(bytes([face])*64 for face in range(6))
        combined=standard_cube(base,[high])
        self.assertEqual(struct.unpack_from('<I',combined,140)[0],1)
        for face in range(6):
            self.assertEqual(combined[148+face*80:148+(face+1)*80],bytes([face])*64+bytes([face+10])*16)
        with self.assertRaises(ValueError):standard_cube(base,[])

    def test_reflex_interpolates_radiance_not_scalar_multiplier(self):
        p=E.Element('Properties');tod=E.SubElement(p,'ToDData')
        for i in range(12):E.SubElement(tod,f'T{i:02d}',clrColor='1,0,0',fMult='2')
        tod.find('T04').attrib.update(clrColor='0,0,1',fMult='4')
        reflex_times(p)
        sample=tod.find('T04')  # 07:00, still before the 08:00 source sample
        rgb=np.array(list(map(float,sample.get('clrColor').split(','))))*float(sample.get('fMult'))
        np.testing.assert_allclose(rgb,(2,0,0))
        sample=tod.find('T05')  # 13:00 exactly
        rgb=np.array(list(map(float,sample.get('clrColor').split(','))))*float(sample.get('fMult'))
        np.testing.assert_allclose(rgb,(0,0,4))
        self.assertEqual(tod.find('T11').attrib,tod.find('T00').attrib)

    def test_native_stream_pack_roundtrip_preserves_pixels(self):
        header=bytearray(float_dds([np.ones((6,128,128,4),np.float32) for _ in range(6)])[:148])
        struct.pack_into('<I',header,128,95)
        sizes=[16384,4096,1024,256,64,16]
        pixels=b''.join(bytes([face*10+i])*n for face in range(6) for i,n in enumerate(sizes))
        members=cry_cube_members(bytes(header)+pixels)
        self.assertEqual(struct.unpack_from('<I',members[''],36)[0],0x200011)
        self.assertEqual({k:len(v) for k,v in members.items()},{'':2164,'.3':98304,'.2':24576,'.1':6144})
        restored=standard_cube(members[''],[members['.1'],members['.2'],members['.3']])
        self.assertEqual(restored[148:],pixels)


if __name__=='__main__':unittest.main()
