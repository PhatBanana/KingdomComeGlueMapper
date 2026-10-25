from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from clothing_fitting import OutfitFitting, alpha_mips, fit_mask, source_layer_contracts, higher_layers
from character_skin_upgrade import CompiledSkin, upgrade_skin
from clothing_regions import read_chunks, write_chunks
from npc_effects import write_float_dds, decode_dds_family, native_vertex_features
from clothing_coverage import apply_membership
from test_character_upgrade import sample_skin


class OutfitFittingTests(unittest.TestCase):
    def test_authored_body_fit_uses_only_same_gender_cover_and_preserves_exposed_skin(self):
        source=sample_skin(morph=True)
        chunks=read_chunks(source);chunk=next(c for c in chunks if c.kind==0x2002)
        data=bytearray(chunk.data.replace(b'#V_001\0',b'#A_Shrink\0'))
        struct.pack_into('<I',data,8,len(b'#A_Shrink\0'))
        source=write_chunks(chunks,{chunk.id:bytes(data)})
        fitter=object.__new__(OutfitFitting)
        fitter.parts=[dict(kind='body',gender_id='1'),dict(kind='cloth',gender_id='1'),dict(kind='cloth',gender_id='2')]
        fitter.contracts={1:{'foot':1},2:{'foot':1}};fitter.memberships={}
        covers=[]
        def cover(i,lod): covers.append((i,lod));return i
        fitter.cover=cover
        covered=np.array([1,1,1,0,0,0.])
        with patch('clothing_fitting.fit_mask',return_value=covered):
            weights,masks=fitter.weights(0,source,None)
        self.assertEqual(covers,[(1,0)])
        out,_=upgrade_skin(source,source,morph_weights=weights,morph_masks=masks)
        before,after=CompiledSkin(source),CompiledSkin(out)
        np.testing.assert_allclose(after.vertices[:3],before.vertices[:3]+[0,0,2])
        np.testing.assert_array_equal(after.vertices[3:],before.vertices[3:])

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
