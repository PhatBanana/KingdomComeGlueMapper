from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from clothing_fitting import (OutfitFitting, alpha_mips, fit_mask, hiding_mask, source_layer_contracts, higher_layers,
                              shares_authored_subpart)
from clothing_coverage import GARMENT_HIDING_OUTWARD, normals
from character_skin_upgrade import CompiledSkin, upgrade_skin
from clothing_regions import read_chunks, write_chunks
from npc_effects import write_float_dds, decode_dds_family, native_vertex_features
from clothing_coverage import apply_membership
from test_character_upgrade import sample_skin


class OutfitFittingTests(unittest.TestCase):
    def test_converted_fitting_ignores_stale_source_cache_but_respects_texture_cutouts(self):
        # The source cache excludes every triangle, while the converted mesh
        # has cleared hiding. Its real material must decide coverage at LOD0
        # and at a lower authored LOD, even if that cache no longer exists.
        skin=CompiledSkin(sample_skin())
        positions=np.array([[0,0,1],[1,0,1],[0,1,1],[1,1,1],[0,2,1],[1,2,1.]],dtype='<f4')
        internal=bytearray(skin.internal.data)
        for i,j in enumerate(skin.remap):
            struct.pack_into('<3f',internal,32+64*int(j)+12,*positions[i])
        blob=write_chunks(skin.chunks,{skin.streams[0].id:skin.streams[0].data[:24]+positions.tobytes(),
                                      skin.internal.id:bytes(internal)})
        from test_clothing_coverage import encoded
        rows={'item/body_layer':[dict(body_layer_id='1',layer_order='1')],
              'item/armor_archetype2body_subpart':[dict(armor_archetype_id='7',body_subpart_id='torso',body_layer_id='1')],
              'item/clothing':[],
              'item/clothing_raycast':[dict(skin='cloth.skin',material='cloth.mtl',
                  opaque_triangle_mask=encoded([0]*len(skin.faces)),not_culled_triangle_mask=encoded([0]*len(skin.faces)))]}
        part=dict(kind='cloth',gender_id='2',armor_archetype_id='7',model='cloth.skin',material='cloth.mtl')
        with tempfile.TemporaryDirectory() as tmp:
            material=Path(tmp)/'cloth.mtl';texture=Path(tmp)/'texture.dds'
            root=ET.Element('Material');slots=ET.SubElement(root,'SubMaterials')
            for _ in range(10):
                node=ET.SubElement(slots,'Material',Shader='Illum',AlphaTest='0.1')
                ET.SubElement(ET.SubElement(node,'Textures'),'Texture',Map='Diffuse',File='texture.dds')
            ET.ElementTree(root).write(material)
            emitted={str(material):material,'texture.dds':texture}
            for alpha in (255,0):
                Image.new('RGBA',(4,4),(255,255,255,alpha)).save(texture)
                for cache in (rows['item/clothing_raycast'],[]):
                    tables=SimpleNamespace(get=lambda name:dict(rows=cache if name=='item/clothing_raycast' else rows[name]))
                    fitter=OutfitFitting([part],{'cloth.skin':None,'cloth_lod1.skin':None,'cloth.mtl':None},
                        lambda name:blob,lambda name:str(material.with_suffix('')),emitted,tables)
                    for lod in (0,1):
                        upper,visible,accept=fitter.cover(0,lod)
                        self.assertTrue(visible.all())
                        covered=accept(np.arange(len(upper.faces)),np.full(len(upper.faces),.2),np.full(len(upper.faces),.2))
                        np.testing.assert_array_equal(covered,np.full(len(upper.faces),alpha!=0))

    def test_body_keeps_source_shape_with_or_without_equipment_for_both_genders(self):
        source=sample_skin(morph=True)
        chunks=read_chunks(source);chunk=next(c for c in chunks if c.kind==0x2002)
        data=bytearray(chunk.data.replace(b'#V_001\0',b'#A_Shrink\0'))
        struct.pack_into('<I',data,8,len(b'#A_Shrink\0'))
        source=write_chunks(chunks,{chunk.id:bytes(data)})
        fitter=object.__new__(OutfitFitting)
        fitter.contracts={1:{'foot':1},2:{'foot':1}};fitter.memberships={}
        covers=[]
        def cover(i,lod): covers.append((i,lod));return i
        fitter.cover=cover
        for gender in ('1', '2'):
            for equipped in (False, True):
                fitter.parts=[dict(kind='body',gender_id=gender)]
                if equipped:
                    fitter.parts += [dict(kind='cloth',gender_id='1'),dict(kind='cloth',gender_id='2')]
                with self.subTest(gender=gender, equipped=equipped):
                    weights,masks=fitter.weights(0,source,None)
                    self.assertEqual((weights,masks), ({},{}))
                    out,_=upgrade_skin(source,source,morph_weights=weights,morph_masks=masks)
                    np.testing.assert_array_equal(CompiledSkin(out).vertices,CompiledSkin(source).vertices)
        self.assertEqual(covers,[])

    def test_uses_source_layer_order_and_shared_subparts_not_file_names(self):
        parts=[dict(kind='cloth', armor_archetype_id=str(i), gender_id='1', model='arbitrary') for i in range(3)]
        rows={
            'item/body_layer': [dict(body_layer_id='9', layer_order='1'), dict(body_layer_id='2', layer_order='4')],
            'item/armor_archetype2body_subpart': [
                dict(armor_archetype_id='0', body_subpart_id='leg', body_layer_id='9'),
                dict(armor_archetype_id='1', body_subpart_id='torso', body_layer_id='2'),
                dict(armor_archetype_id='1', body_subpart_id='leg', body_layer_id='2'),
                dict(armor_archetype_id='2', body_subpart_id='head', body_layer_id='2')]}
        tables=SimpleNamespace(get=lambda name:dict(rows=rows[name]))
        contracts=source_layer_contracts(parts,tables)
        self.assertEqual(higher_layers(0,parts,contracts),[1])
        self.assertEqual(higher_layers(1,parts,contracts),[])
        self.assertEqual(higher_layers(2,parts,contracts),[])
        parts[1]['gender_id']='2'
        self.assertEqual(higher_layers(0,parts,contracts),[])

    def test_footwear_is_layered_over_legwear_that_reaches_the_lower_leg(self):
        # KCD1: trousers hold only leg subparts, boots only foot subparts, so
        # the pair shared nothing and the trouser foot was neither shrunk nor
        # hidden inside the boot (ska_fatherOfHenry, ska_collierVarlet).
        names={'49':('5','leg_left_upper_front'),'51':('5','leg_left_lower_front'),'53':('5','foot_left_boots'),
               '57':('6','leg_right_lower_front'),'59':('6','foot_right_boots'),'61':('6','foot_spur'),
               '1':('2','body_front_up')}
        rows={
            'item/body_layer':[dict(body_layer_id=str(i),layer_order=str(i)) for i in (1,3,4,6,9)],
            'item/body_subpart':[dict(body_subpart_id=k,body_part_id=part,body_subpart_name=name) for k,(part,name) in names.items()],
            'item/armor_archetype2body_subpart':[
                *[dict(armor_archetype_id='trousers',body_subpart_id=s,body_layer_id='1') for s in ('49','51','57')],
                *[dict(armor_archetype_id='boots',body_subpart_id=s,body_layer_id='3') for s in ('53','59')],
                dict(armor_archetype_id='shorts',body_subpart_id='49',body_layer_id='1'),
                *[dict(armor_archetype_id='greaves',body_subpart_id=s,body_layer_id='6') for s in ('51','57')],
                dict(armor_archetype_id='spurs',body_subpart_id='61',body_layer_id='9'),
                *[dict(armor_archetype_id='coat',body_subpart_id=s,body_layer_id='4') for s in ('1','49')]]}
        tables=SimpleNamespace(get=lambda name:dict(rows=rows[name]))
        order=['trousers','boots','shorts','greaves','spurs','coat']
        parts=[dict(kind='cloth',armor_archetype_id=a,gender_id='1') for a in order]
        contracts=source_layer_contracts(parts,tables)
        above=lambda name:[order[i] for i in higher_layers(order.index(name),parts,contracts)]
        self.assertEqual(above('trousers'),['boots','greaves','coat'])
        # Implied occupancy never makes a garment an upper layer, and reaches
        # neither garments that stop above the lower leg nor unsided spurs.
        self.assertEqual(above('boots'),[])
        self.assertEqual(above('shorts'),['coat'])
        self.assertEqual(above('greaves'),[])
        self.assertEqual(above('spurs'),[])
        self.assertEqual(contracts[0].implied,{'53','59'})
        self.assertEqual(contracts[1].implied,frozenset())
        # Only pairs the tables place on one subpart may delete the lower garment.
        self.assertFalse(shares_authored_subpart(contracts[0],contracts[1]))
        self.assertTrue(shares_authored_subpart(contracts[0],contracts[3]))
        self.assertTrue(shares_authored_subpart(contracts[0],contracts[5]))

    def test_conflicting_subpart_order_is_not_given_an_arbitrary_winner(self):
        parts=[dict(kind='cloth',gender_id='2')]*2
        contracts={0:{'a':1,'b':2},1:{'a':2,'b':1}}
        self.assertEqual(higher_layers(0,parts,contracts),[])
        self.assertEqual(higher_layers(1,parts,contracts),[])

    def test_only_opaque_covered_vertices_shrink_for_either_gender(self):
        lower = SimpleNamespace(n=6, ninternal=6, remap=np.arange(6),
            vertices=np.array([[0,0,0], [1,0,0], [0,1,0], [3,0,0], [4,0,0], [3,1,0.]]),
            faces=np.array([[0,1,2], [3,4,5]]))
        upper = SimpleNamespace(vertices=lower.vertices+[0,0,.01], faces=lower.faces)
        opaque = np.ones(2, bool)
        accepts = lambda triangle,u,v: triangle == 0
        np.testing.assert_array_equal(fit_mask(lower, [(upper, opaque, accepts)]), [1,1,1,0,0,0])
        np.testing.assert_array_equal(fit_mask(lower, []), np.zeros(6))

    def test_garment_is_deleted_only_where_the_upper_garment_touches_or_pierces_it(self):
        # A hood hem 4 cm above a collar covers it along the normal (so the
        # collar still shrinks under it) but must not delete it: from the front
        # the hem does not occlude the collar and skin would show instead.
        lower = SimpleNamespace(n=3, ninternal=3, remap=np.arange(3),
            vertices=np.array([[0,0,0], [1,0,0], [0,1,0.]]), faces=np.array([[0,1,2]]))
        opaque = np.ones(1, bool); accepts = lambda triangle,u,v: np.ones(len(triangle), bool)
        def cover(offset):
            return [(SimpleNamespace(vertices=lower.vertices+[0,0,offset], faces=lower.faces), opaque, accepts)]
        np.testing.assert_array_equal(fit_mask(lower, cover(.04)), [1,1,1])
        np.testing.assert_array_equal(hiding_mask(lower, cover(.04)), [0,0,0])
        np.testing.assert_array_equal(hiding_mask(lower, cover(.005)), [1,1,1])   # lying on it
        np.testing.assert_array_equal(hiding_mask(lower, cover(-.02)), [1,1,1])   # pierced through it
        np.testing.assert_array_equal(hiding_mask(lower, cover(.12)), [0,0,0])
        self.assertLess(GARMENT_HIDING_OUTWARD, .02)

    def test_fitting_memberships_use_the_hiding_band_while_shrink_uses_the_fitting_band(self):
        source=sample_skin(morph=True)
        chunks=read_chunks(source);chunk=next(c for c in chunks if c.kind==0x2002)
        data=bytearray(chunk.data.replace(b'#V_001\0',b'#A_Shrink\0'))
        struct.pack_into('<I',data,8,len(b'#A_Shrink\0'))
        source=write_chunks(chunks,{chunk.id:bytes(data)})
        fitter=object.__new__(OutfitFitting)
        fitter.parts=[dict(kind='cloth',gender_id='1'),dict(kind='cloth',gender_id='1')]
        fitter.contracts={0:{'a':1},1:{'a':2}};fitter.memberships={}
        lower=CompiledSkin(upgrade_skin(source,source,discard_unused_variants=True)[0])
        # The fixture's vertices are collinear (no normals): give it +z normals and a
        # wide planar cover offset along them.
        quad=np.array([[-9,-9,0],[9,-9,0],[9,9,0],[-9,9,0.]]); faces=np.array([[0,1,2],[0,2,3]])
        for offset, shrunk, hidden in ((.04, 1, 0), (.0, 1, 1)):
            with self.subTest(offset=offset):
                raised=SimpleNamespace(vertices=quad+[0,0,1+offset], faces=faces)
                fitter.cover=lambda number,lod: (raised, np.ones(2,bool), lambda t,u,v: np.ones(len(t),bool))
                with patch('clothing_fitting.normals', side_effect=lambda skin: np.tile([0,0,1.],(skin.n,1))):
                    weights,masks=fitter.weights(0,source,None)
                self.assertEqual(weights,{'#A_Shrink':1.})
                np.testing.assert_array_equal(masks['#A_Shrink'], np.full(lower.n, shrunk, float))
                np.testing.assert_array_equal(fitter.memberships[0,0][1], np.full(lower.n, hidden, float))

    def test_masked_morph_preserves_exposed_surface_and_internal_geometry(self):
        source = sample_skin(morph=True)
        before = CompiledSkin(source)
        mask = np.array([1,1,1,0,0,0.])
        out, report = upgrade_skin(source, source, morph_weights={'#V_001':1}, morph_masks={'#V_001':mask})
        after = CompiledSkin(out)
        np.testing.assert_allclose(after.vertices[:3], before.vertices[:3]+[0,0,2])
        np.testing.assert_array_equal(after.vertices[3:], before.vertices[3:])
        np.testing.assert_array_equal(after.faces, before.faces)
        np.testing.assert_array_equal(after.weights, before.weights)
        for i,j in enumerate(after.remap):
            np.testing.assert_allclose(struct.unpack_from('<3f', after.internal.data, 32+64*int(j)+12), after.vertices[i])
        self.assertEqual(report['fitting_masks']['#V_001']['exposed_vertices'], 3)
        self.assertEqual(report['preserved_morphs'], 0)

    def test_native_material_conversion_preserves_only_requested_generated_masks(self):
        source=sample_skin()
        source=upgrade_skin(source,source)[0]
        selected=np.array([True,True,True,False,False,False])
        covered=apply_membership(source,{4:selected})
        result=CompiledSkin(native_vertex_features(covered,preserve_hiding=True))
        alpha=np.frombuffer(result.streams[3].data[24:],np.uint8).reshape(-1,4)[:,3]
        np.testing.assert_array_equal(alpha, np.where(selected,239,255))
        for i,j in enumerate(result.remap):
            self.assertEqual(result.internal.data[32+64*int(j)+63],int(alpha[i]))
        plain=CompiledSkin(native_vertex_features(covered))
        self.assertTrue(np.all(np.frombuffer(plain.streams[3].data[24:],np.uint8).reshape(-1,4)[:,3]==255))

    def test_fitting_rejects_a_seam_with_different_weights(self):
        source=sample_skin(morph=True);skin=CompiledSkin(source)
        positions=skin.vertices.copy();positions[1]=positions[0]
        remap=skin.remap.copy();remap[1]=remap[0]
        source=write_chunks(skin.chunks,{skin.streams[0].id:skin.streams[0].data[:24]+positions.astype('<f4').tobytes(),
                                        skin.remap_chunk.id:remap.astype('<u2').tobytes()})
        with self.assertRaisesRegex(ValueError,'shared internal vertex'):
            upgrade_skin(source,source,morph_weights={'#V_001':1},morph_masks={'#V_001':[1,0,0,0,0,0]})

    def test_rejects_nonfinite_or_wrong_lod_or_unapplied_mask(self):
        source = sample_skin(morph=True)
        for mask in ([1]*5, [float('nan')]*6, [-1]*6, [1.1]*6):
            with self.assertRaisesRegex(ValueError, 'Invalid fitting'):
                upgrade_skin(source, source, morph_weights={'#V_001':1}, morph_masks={'#V_001':mask})
        with self.assertRaisesRegex(ValueError, 'applied shape'):
            upgrade_skin(source, source, morph_masks={'#V_001':[1]*6})
        with self.assertRaisesRegex(ValueError, 'variants cannot'):
            upgrade_skin(source, source, variant='#V_001', morph_masks={'#V_001':[1]*6})

    def test_alpha_mips_match_native_material_bake(self):
        image = Image.fromarray(np.random.default_rng(7).integers(0,256,(16,32,4),np.uint8))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'diff.dds'
            write_float_dds(path, np.asarray(image, np.float32)/255)
            data = path.read_bytes(); offset=148
            for alpha in alpha_mips(image):
                size=alpha.size*8
                native=np.frombuffer(data[offset:offset+size], '<f2').reshape(*alpha.shape,4)
                np.testing.assert_array_equal(native[:,:,3], alpha)
                offset += size
            self.assertEqual(offset,len(data))

    def test_staged_split_texture_rejects_a_missing_mip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'texture.dds'
            Image.new('RGBA',(4,4),(255,255,255,0)).save(path)
            with self.assertRaisesRegex(ValueError, 'Incomplete split'):
                decode_dds_family(path.read_bytes(), {2:b'x'})


if __name__ == '__main__': unittest.main()
