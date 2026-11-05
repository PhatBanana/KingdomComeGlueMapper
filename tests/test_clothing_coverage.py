import base64
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from clothing_coverage import triangle_mask, source_opacity, covered_points, apply_membership, apply_fitted_membership, unculled_garment_visibility, opaque_native_surface, alpha_intersections, native_alpha_surfaces, triangle_safe_membership, register_coverage, register_fixed_body_coverage, body_shadow, culled_triangles, face_safe_membership
from clothing_regions import split_skin_regions
from npc_effects import write_float_dds
from character_skin_upgrade import CompiledSkin, upgrade_skin
from test_character_upgrade import sample_skin


def encoded(bits):
    return base64.b64encode(struct.pack('<H', len(bits)) + np.packbits(bits, bitorder='little').tobytes()).decode()


class ClothingCoverageTests(unittest.TestCase):
    def test_nodraw_material_never_hides_skin(self):
        with tempfile.TemporaryDirectory() as directory:
            material=Path(directory)/'invisible.mtl'
            material.write_text('<Material Shader="Nodraw"/>')
            surfaces,evidence=native_alpha_surfaces(directory,material)
            self.assertFalse(surfaces[0][1][0].any())
            self.assertFalse(evidence[0]['opaque'])
            with self.assertRaisesRegex(ValueError,'Cutout'):
                opaque_native_surface(directory,material,1)

    def test_cutout_ray_hits_use_uv_material_and_wrapped_filter_footprint(self):
        uv = np.array([[.25,.25]]*3 + [[.75,.75]]*3, dtype='<f4')
        skin = SimpleNamespace(n=6, streams={2: SimpleNamespace(data=struct.pack('<6I', 0,2,6,8,0,0)+uv.tobytes())},
                               faces=np.array([[0,1,2],[3,4,5]]),
                               info={'subset_records': [dict(first_index=0,num_indices=6,material_id=0)]})
        alpha = np.ones((8,8)); alpha[5:7,5:7] = 0
        accept = alpha_intersections(skin, [(0.1,[alpha, np.ones((1,1))])], np.ones(2,bool))
        np.testing.assert_array_equal(accept(np.array([0,1]),np.array([.2,.2]),np.array([.2,.2])), [True,False])
        triangles = np.array([[[-1,-1,.02],[1,-1,.02],[0,1,.02]]]*2)
        # A transparent near layer must not prevent a different opaque hit.
        np.testing.assert_array_equal(covered_points([[0,0,0]], [[0,0,1]], triangles, accept_hit=accept), [True])
        skin.info['subset_records'][0]['material_id'] = 1
        with self.assertRaisesRegex(ValueError, 'material subset'):
            alpha_intersections(skin, [(0.1,[alpha])], np.ones(2,bool))

    def test_native_opacity_checks_material_threshold_and_every_mip(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            material = output / 'cloth.mtl'
            material.write_text('<Material Shader="Illum" StringGenMask="%CLOTHING_SYSTEM" '
                                'MtlFlags="524290" Opacity="1" AlphaTest="0.1">'
                                '<Textures><Texture Map="Diffuse" File="cloth.dds"/></Textures></Material>')
            pixels = np.ones((4, 4, 4), dtype=np.float32)
            pixels[:, :, 3] = .25
            write_float_dds(output / 'cloth.dds', pixels)
            mask, evidence = opaque_native_surface(output, material, 3)
            np.testing.assert_array_equal(mask, [True] * 3)
            self.assertEqual(evidence[0]['mips'], 3)
            # A bad distant mip must not be hidden by inspecting only level zero.
            blob = bytearray((output / 'cloth.dds').read_bytes())
            struct.pack_into('<e', blob, len(blob)-2, 0)
            (output / 'cloth.dds').write_bytes(blob)
            with self.assertRaisesRegex(ValueError, 'Cutout'):
                opaque_native_surface(output, material, 3)
            write_float_dds(output / 'cloth.dds', pixels)
            material.write_text(material.read_text().replace('Opacity="1"', 'Opacity="0.5"'))
            with self.assertRaisesRegex(ValueError, 'Unsupported'):
                opaque_native_surface(output, material, 3)

    def test_generated_opacity_keeps_visibility_and_rejects_wrong_topology(self):
        rows = [dict(skin='a.skin', material='a.mtl', opaque_triangle_mask='',
                     not_culled_triangle_mask=encoded([1, 0, 1]))]
        np.testing.assert_array_equal(source_opacity(rows, 'a.skin', 'a.mtl', 3,
                                      generated_opacity=np.ones(3, bool)), [1, 0, 1])
        with self.assertRaisesRegex(ValueError, 'Invalid generated'):
            source_opacity(rows, 'a.skin', 'a.mtl', 3, generated_opacity=np.ones(2, bool))

    def test_source_mask_bit_order_and_topology_guard(self):
        bits = [True, False, False, True, True, False, True, False, True]
        np.testing.assert_array_equal(triangle_mask(encoded(bits), 9), bits)
        for count in (8, 10):
            with self.assertRaises(ValueError):
                triangle_mask(encoded(bits), count)

    def test_opacity_requires_exact_material_and_intersects_visibility(self):
        rows = [dict(skin='Dress.skin', material='Red.mtl',
                     opaque_triangle_mask=encoded([1, 0, 1]),
                     not_culled_triangle_mask=encoded([1, 1, 0]))]
        np.testing.assert_array_equal(source_opacity(rows, 'dress.skin', 'red.mtl', 3), [1, 0, 0])
        with self.assertRaises(ValueError):
            source_opacity(rows, 'dress.skin', 'blue.mtl', 3)
        rows[0]['opaque_triangle_mask'] = ''
        with self.assertRaises(ValueError):
            source_opacity(rows, 'dress.skin', 'red.mtl', 3)

    def test_surface_normal_coverage_preserves_exposed_opening_and_ignores_distant_mesh(self):
        # A sleeve surface only covers the first point, not the exposed shoulder
        # beside it or an unrelated surface half a metre away.
        triangle = np.array([[[-1, -1, .02], [1, -1, .02], [0, 1, .02]]])
        points = [[0, 0, 0], [2, 0, 0], [0, 0, -.5]]
        np.testing.assert_array_equal(covered_points(points, [[0, 0, 1]]*3, triangle), [1, 0, 0])
        # A slightly protruding body vertex still needs coverage from an inner surface.
        np.testing.assert_array_equal(covered_points([[0, 0, .04]], [[0, 0, 1]], triangle), [1])
        np.testing.assert_array_equal(covered_points(points, [[0, 0, 1]]*3, triangle[:0]), [0, 0, 0])

    def test_missing_visibility_can_use_converted_mesh_but_not_replace_opacity(self):
        rows = [dict(skin='dress.skin', material='red.mtl',
                     opaque_triangle_mask=encoded([1, 0, 1]), not_culled_triangle_mask='')]
        visible = np.array([True, True, False])
        np.testing.assert_array_equal(source_opacity(rows, 'dress.skin', 'red.mtl', 3, visible), [1, 0, 0])
        with self.assertRaises(ValueError): source_opacity(rows, 'dress.skin', 'red.mtl', 3, [1, 1, 1])
        rows[0]['opaque_triangle_mask'] = ''
        with self.assertRaises(ValueError): source_opacity(rows, 'dress.skin', 'red.mtl', 3, visible)

    def test_rebuilt_visibility_rejects_retained_hiding_bits(self):
        blob, _ = upgrade_skin(sample_skin(), sample_skin(), clear_hiding=True)
        skin = CompiledSkin(blob)
        self.assertTrue(unculled_garment_visibility(skin).all())
        hidden = apply_membership(blob, {4: np.ones(skin.n, dtype=bool)})
        with self.assertRaisesRegex(ValueError, 'hiding membership'):
            unculled_garment_visibility(CompiledSkin(hidden))

    def test_conditional_masks_restore_body_when_garment_is_removed(self):
        source = sample_skin()
        source, _ = upgrade_skin(source, source)
        before = CompiledSkin(source)
        outer = np.array([1, 1, 0, 0, 0, 0], dtype=bool)
        inner = np.array([0, 1, 1, 0, 0, 0], dtype=bool)
        result = CompiledSkin(apply_membership(source, {4: inner, 5: outer}))
        alpha = np.frombuffer(result.streams[3].data[24:], dtype=np.uint8).reshape(-1, 4)[:, 3]
        hidden_by_outer = (alpha & (1 << 5)) == 0
        hidden_by_inner = (alpha & (1 << 4)) == 0
        np.testing.assert_array_equal(hidden_by_outer, outer)
        np.testing.assert_array_equal(hidden_by_inner, inner)
        # No active group: every body vertex is available again, not deleted.
        np.testing.assert_array_equal(((255 ^ alpha) & 0) != 0, np.zeros(before.n, dtype=bool))
        for stream in (0, 1, 2, 5, 6, 9):
            self.assertEqual(before.streams[stream].data, result.streams[stream].data)
        for i, remap in enumerate(result.remap):
            self.assertEqual(result.internal.data[32+int(remap)*64+63], alpha[i])

    def test_covered_vertex_does_not_erase_uncovered_neighbour_triangle(self):
        skin=SimpleNamespace(n=5,ninternal=5,remap=np.arange(5),faces=np.array([[0,1,2],[1,3,2],[0,2,4]]))
        covered=np.array([1,1,1,0,1],bool)
        safe=triangle_safe_membership(skin,covered)
        culled=safe[skin.faces].any(axis=1)
        self.assertTrue(culled.any())
        self.assertFalse(culled[1])
        self.assertTrue(covered[skin.faces[culled]].all())

    def test_exposed_render_copy_preserves_the_shared_seam(self):
        skin=SimpleNamespace(n=6,ninternal=5,remap=np.array([0,1,2,0,3,4]),faces=np.array([[0,1,2],[3,4,5]]))
        safe=triangle_safe_membership(skin,np.array([1,1,1,0,1,1],bool))
        self.assertFalse(safe[0]);self.assertFalse(safe[3])
        self.assertFalse(safe.any())

    def test_fitted_outfit_preserves_exposed_faces_and_both_native_buffers(self):
        blob, _ = upgrade_skin(sample_skin(), sample_skin(), clear_hiding=True)
        original = CompiledSkin(blob)
        covered = np.ones(original.n, bool)
        covered[original.faces[0, 0]] = False
        result = CompiledSkin(apply_fitted_membership(blob, {'outer': covered}))
        alpha = np.frombuffer(result.streams[3].data[24:], np.uint8).reshape(-1, 4)[:, 3]
        culled = (((255 ^ alpha) & 16) != 0)[result.faces].any(axis=1)
        self.assertFalse(culled[0])
        self.assertTrue(covered[result.faces[culled]].all())
        for i, remap in enumerate(result.remap):
            self.assertEqual(result.internal.data[32+int(remap)*64+63], alpha[i])
        np.testing.assert_array_equal(result.vertices, original.vertices)
        np.testing.assert_array_equal(result.faces, original.faces)

    def test_fixed_outfit_masks_hair_head_and_beard_conditionally(self):
        blob, _ = upgrade_skin(sample_skin(), sample_skin(), clear_hiding=True)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp); folder = output/'objects/characters/example'; folder.mkdir(parents=True)
            tables = output/'Libs/Tables/Character'; tables.mkdir(parents=True)
            (tables/'ClothingHidingGroup__test.xml').write_text('<database><ClothingHidingGroups/></database>')
            component = ET.Element('Component', FilePath='example'); derived = ET.SubElement(component, 'DerivedComponents')
            for kind, region in [('Body','torso'), ('Head','face'), ('Hair','head'), ('Beard','beard'), ('Clothing','head')]:
                (folder/(kind+'.skin')).write_bytes(blob)
                node = ET.SubElement(derived, kind)
                ET.SubElement(ET.SubElement(node,'Elements'),'SkinElement', EquipmentPart=region, Model=kind+'.skin', Material='hood.mtl')
            with patch('clothing_coverage.native_alpha_surfaces', return_value=([(0,[np.ones((1,1))])]*10, [])), \
                 patch('clothing_coverage.normals', side_effect=lambda skin: np.tile([0,0,1], (skin.n,1))), \
                 patch('clothing_coverage.covered_points', side_effect=lambda points,*args,**kwargs: np.ones(len(points),bool)):
                result = register_fixed_body_coverage(output, component, 'test')
            self.assertEqual({row['target'] for row in result['layers']}, {'Body.skin','Head.skin','Hair.skin','Beard.skin'})
            for name in ('Body','Head','Hair','Beard'):
                skin = CompiledSkin((folder/(name+'.skin')).read_bytes())
                alpha = np.frombuffer(skin.streams[3].data[24:], np.uint8).reshape(-1,4)[:,3]
                self.assertTrue(((255 ^ alpha) & 16).all())
                self.assertFalse(((255 ^ alpha) & 0).any())  # Removing the outfit restores these surfaces.
                for i, remap in enumerate(skin.remap):
                    self.assertEqual(skin.internal.data[32+int(remap)*64+63], alpha[i])

    def test_physical_cut_does_not_disappear_when_distant_mip_averages_below_threshold(self):
        from clothing_coverage import physical_alpha_intersections
        uv = np.array([[.2,.2],[.3,.2],[.2,.3],[.7,.7],[.8,.7],[.7,.8]], '<f4')
        skin = SimpleNamespace(n=6, streams={2:SimpleNamespace(data=struct.pack('<6I',0,2,6,8,0,0)+uv.tobytes())},
            faces=np.array([[0,1,2],[3,4,5]]), info={'subset_records':[dict(first_index=0,num_indices=6,material_id=0)]})
        alpha = np.ones((16,16)); alpha[9:,9:] = 0
        surfaces=[(.75,[alpha,np.array([[.47]])])]
        arguments=(np.array([0,1]),np.array([.2,.2]),np.array([.2,.2]))
        np.testing.assert_array_equal(alpha_intersections(skin,surfaces,np.ones(2,bool))(*arguments),[False,False])
        np.testing.assert_array_equal(physical_alpha_intersections(skin,surfaces,np.ones(2,bool))(*arguments),[True,False])

    def test_authored_lods_get_their_own_mask_topology(self):
        blob,_=upgrade_skin(sample_skin(),sample_skin(),clear_hiding=True)
        lower=split_skin_regions(blob,['keep','discard','discard','discard'])['keep']
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);folder=output/'objects/characters/example';folder.mkdir(parents=True)
            (output/'Libs/Tables/Character').mkdir(parents=True)
            for stem in ('body','hair','head','dress'):
                (folder/(stem+'.skin')).write_bytes(blob)
                (folder/(stem+'_lod1.skin')).write_bytes(lower)
            component=ET.fromstring('<Component FilePath="example"><DerivedComponents>'
                '<Body><Elements><SkinElement EquipmentPart="torso" Model="body.skin"/></Elements></Body>'
                '<Hair><Elements><SkinElement EquipmentPart="head" Model="hair.skin"/></Elements></Hair>'
                '<Head><Elements><SkinElement EquipmentPart="face" Model="head.skin"/></Elements></Head>'
                '<Clothing Name="test_dress"><Elements><SkinElement EquipmentPart="torso" Model="dress.skin"/></Elements></Clothing>'
                '</DerivedComponents></Component>')
            tables={'item/body_layer':[dict(body_layer_id='1',layer_order='1')],
                    'item/armor_archetype2body_subpart':[dict(armor_archetype_id='a',body_layer_id='1',body_subpart_id='torso')],
                    'item/clothing_raycast':[dict(skin='source.skin',material='source.mtl',opaque_triangle_mask=encoded([0,0,0,0]),not_culled_triangle_mask=encoded([0,0,0,0]))]}
            garment=dict(part=dict(kind='cloth',gender_id='2',armor_archetype_id='a'),stem='dress',
                         source_model='source.skin',source_material='source.mtl')
            with patch('clothing_coverage.native_alpha_surfaces',return_value=([(0,[np.ones((1,1))])]*10,[])), \
                 patch('clothing_coverage.normals',side_effect=lambda skin: np.tile([0,0,1],(skin.n,1))), \
                 patch('clothing_coverage.covered_points',side_effect=lambda points,*args,**kwargs: np.ones(len(points),bool)):
                result=register_coverage(output,component,[garment],SimpleNamespace(get=lambda key:dict(rows=tables[key])),'test')
            self.assertEqual([(r['lod'],r['candidate_triangles']) for r in result['layers']],[(0,4),(1,1)]*3)
            self.assertEqual([r['lod'] for r in result['layers'] if r['coverage_test']=='outward_head_cone'],[0,1])
            for name in ('body.skin','body_lod1.skin','hair.skin','hair_lod1.skin','head.skin','head_lod1.skin'):
                skin=CompiledSkin((folder/name).read_bytes())
                alpha=np.frombuffer(skin.streams[3].data[24:],np.uint8).reshape(-1,4)[:,3]
                self.assertTrue(((255^alpha)&16).all())


    def test_composed_region_covers_are_eroded_jointly(self):
        dress_blob,_=upgrade_skin(sample_skin(),sample_skin(),clear_hiding=True)
        body_blob=split_skin_regions(dress_blob,['keep','keep','keep','discard'])['keep']
        body=CompiledSkin(body_blob)
        left=body.vertices[:,0] < np.median(body.vertices[:,0])
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);folder=output/'objects/characters/example';folder.mkdir(parents=True)
            (output/'Libs/Tables/Character').mkdir(parents=True)
            for stem in ('hair','head','dress','coat'):
                (folder/(stem+'.skin')).write_bytes(dress_blob)
            (folder/'body.skin').write_bytes(body_blob)
            component=ET.fromstring('<Component FilePath="example"><DerivedComponents>'
                '<Body><Elements><SkinElement EquipmentPart="torso" Model="body.skin"/></Elements></Body>'
                '<Hair><Elements><SkinElement EquipmentPart="head" Model="hair.skin"/></Elements></Hair>'
                '<Head><Elements><SkinElement EquipmentPart="face" Model="head.skin"/></Elements></Head>'
                '<Clothing Name="test_dress"><Elements><SkinElement EquipmentPart="torso" Model="dress.skin"/></Elements></Clothing>'
                '<Clothing Name="test_coat"><Elements><SkinElement EquipmentPart="torso" Model="coat.skin"/></Elements></Clothing>'
                '</DerivedComponents></Component>')
            tables={'item/body_layer':[dict(body_layer_id='1',layer_order='1'),dict(body_layer_id='2',layer_order='2')],
                    'item/armor_archetype2body_subpart':[dict(armor_archetype_id='a',body_layer_id='1',body_subpart_id='torso'),
                                                         dict(armor_archetype_id='b',body_layer_id='2',body_subpart_id='torso')],
                    'item/clothing_raycast':[]}
            garments=[dict(part=dict(kind='cloth',gender_id='2',armor_archetype_id=a),stem=stem,
                           source_model=stem+'.skin',source_material=stem+'.mtl') for stem,a in (('dress','a'),('coat','b'))]
            current={}
            def surfaces(output,material,**kwargs):
                current['stem']=Path(material).stem
                return [(0,[np.ones((1,1))])]*10,[]
            def covered(points,*args,**kwargs):
                if len(points)!=body.n: return np.ones(len(points),bool)
                # The coat's cutout hands cover to the dress beneath along one boundary.
                return left.copy() if current['stem']=='coat' else ~left
            with patch('clothing_coverage.native_alpha_surfaces',side_effect=surfaces),                  patch('clothing_coverage.normals',side_effect=lambda skin: np.tile([0,0,1],(skin.n,1))),                  patch('clothing_coverage.covered_points',side_effect=covered):
                register_coverage(output,component,garments,SimpleNamespace(get=lambda key:dict(rows=tables[key])),'test')
            skin=CompiledSkin((folder/'body.skin').read_bytes())
            alpha=np.frombuffer(skin.streams[3].data[24:],np.uint8).reshape(-1,4)[:,3]
            used=np.zeros(skin.n,bool);used[skin.faces.ravel()]=True
            coat_bit=1<<(4+1)
            self.assertTrue(((255^alpha)[used]&coat_bit).all())     # no one-ring gap where the covers meet
            self.assertFalse(((255^alpha)[used]&(1<<4)).all())       # the dress alone keeps its own erosion
            groups=ET.parse(output/'Libs/Tables/Character/ClothingHidingGroup__test.xml').getroot()
            self.assertIn('test_coat_covers_torso',{g.get('Name') for g in groups.iter('HidingGroup')})
            self.assertIn('test_coat_covers_torso',component.find("DerivedComponents/Clothing[@Name='test_coat']").get('HidingGroups'))

    def test_body_shadow_hides_head_skin_only_over_culled_body_surface(self):
        body=SimpleNamespace(vertices=np.array([[0,0,0],[1,0,0],[0,1,0],[1,1,0],[2,0,0],[2,1,0]],float),faces=np.array([[0,1,2],[1,3,2],[3,4,5]]))
        hidden=np.array([1,1,1,0,0,0],bool)
        culled=culled_triangles(body,hidden)
        self.assertEqual(len(culled),2)                      # faces touching a hidden vertex; the last one is drawn
        heads=np.array([[.3,.3,.02],[.3,.3,-.02],[.3,.3,.08],[1.8,.5,.01],[5,5,0]])
        up=np.tile([0,0,1.],(len(heads),1))
        np.testing.assert_array_equal(body_shadow(heads,up,culled),[True,True,False,False,False])
        self.assertFalse(body_shadow(heads,up,culled[:0]).any())

    def test_fixed_outfit_head_follows_the_culled_body_surface(self):
        blob, _ = upgrade_skin(sample_skin(), sample_skin(), clear_hiding=True)
        def run(body_covered):
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp); folder = output/'objects/characters/example'; folder.mkdir(parents=True)
                tables = output/'Libs/Tables/Character'; tables.mkdir(parents=True)
                (tables/'ClothingHidingGroup__test.xml').write_text('<database><ClothingHidingGroups/></database>')
                component = ET.Element('Component', FilePath='example'); derived = ET.SubElement(component, 'DerivedComponents')
                for kind, region in [('Head','face'), ('Body','torso'), ('Clothing','torso')]:
                    (folder/(kind+'.skin')).write_bytes(blob)
                    node = ET.SubElement(derived, kind)
                    ET.SubElement(ET.SubElement(node,'Elements'),'SkinElement', EquipmentPart=region, Model=kind+'.skin', Material='coat.mtl')
                def covered(points, *args, **kwargs):
                    if kwargs.get('inward') == 0: return np.zeros(len(points), bool)      # strict exterior head test: a gap
                    if kwargs.get('inward') == .04: return np.ones(len(points), bool)     # the head lies on the body surface
                    return np.full(len(points), body_covered)
                with patch('clothing_coverage.native_alpha_surfaces', return_value=([(0,[np.ones((1,1))])]*10, [])),                      patch('clothing_coverage.normals', side_effect=lambda skin: np.tile([0,0,1], (skin.n,1))),                      patch('clothing_coverage.covered_points', side_effect=covered):
                    register_fixed_body_coverage(output, component, 'test')
                skin = CompiledSkin((folder/'Head.skin').read_bytes())
                alpha = np.frombuffer(skin.streams[3].data[24:], np.uint8).reshape(-1,4)[:,3]
                used = np.zeros(skin.n, bool); used[skin.faces.ravel()] = True
                return ((255 ^ alpha)[used] & 16) != 0
        self.assertTrue(run(True).all())      # body culled beneath: the duplicate head skin is hidden with it
        self.assertFalse(run(False).any())    # body drawn: the strict head test alone decides

    def test_composed_outfit_head_follows_the_culled_body_surface(self):
        blob,_=upgrade_skin(sample_skin(),sample_skin(),clear_hiding=True)
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);folder=output/'objects/characters/example';folder.mkdir(parents=True)
            (output/'Libs/Tables/Character').mkdir(parents=True)
            for stem in ('head','body','dress'):
                (folder/(stem+'.skin')).write_bytes(blob)
            component=ET.fromstring('<Component FilePath="example"><DerivedComponents>'
                '<Head><Elements><SkinElement EquipmentPart="face" Model="head.skin"/></Elements></Head>'
                '<Body><Elements><SkinElement EquipmentPart="torso" Model="body.skin"/></Elements></Body>'
                '<Clothing Name="test_dress"><Elements><SkinElement EquipmentPart="torso" Model="dress.skin"/></Elements></Clothing>'
                '</DerivedComponents></Component>')
            tables={'item/body_layer':[dict(body_layer_id='1',layer_order='1')],
                    'item/armor_archetype2body_subpart':[dict(armor_archetype_id='a',body_layer_id='1',body_subpart_id='torso')],
                    'item/clothing_raycast':[]}
            garments=[dict(part=dict(kind='cloth',gender_id='2',armor_archetype_id='a'),stem='dress',source_model='dress.skin',source_material='dress.mtl')]
            def covered(points,*args,**kwargs):
                if kwargs.get('inward')==0: return np.zeros(len(points),bool)
                return np.ones(len(points),bool)
            with patch('clothing_coverage.native_alpha_surfaces',return_value=([(0,[np.ones((1,1))])]*10,[])),                  patch('clothing_coverage.normals',side_effect=lambda skin: np.tile([0,0,1],(skin.n,1))),                  patch('clothing_coverage.covered_points',side_effect=covered):
                register_coverage(output,component,garments,SimpleNamespace(get=lambda key:dict(rows=tables[key])),'test')
            skin=CompiledSkin((folder/'head.skin').read_bytes())
            alpha=np.frombuffer(skin.streams[3].data[24:],np.uint8).reshape(-1,4)[:,3]
            used=np.zeros(skin.n,bool);used[skin.faces.ravel()]=True
            self.assertTrue((((255^alpha)[used]&16)!=0).all())
            self.assertIn('test_dress_covers_face',component.find("DerivedComponents/Clothing[@Name='test_dress']").get('HidingGroups'))

    def test_face_safety_releases_culled_triangles_with_an_uncovered_interior(self):
        # Two triangles, all four corners covered. The outer garment is cut away over the middle of the first.
        skin=SimpleNamespace(n=4,ninternal=4,remap=np.arange(4),faces=np.array([[0,1,2],[1,3,2]]),
                             vertices=np.array([[0,0,0],[1,0,0],[0,1,0],[1,1,0]],float))
        hidden=np.ones(4,bool); up=np.tile([0,0,1.],(4,1))
        cutout=lambda points,rays: ~((np.abs(points[:,0]-1/3)<.05)&(np.abs(points[:,1]-1/3)<.05))
        safe=face_safe_membership(skin,hidden,up,cutout)
        self.assertFalse(safe[[0,1,2]].any())
        self.assertFalse(safe[skin.faces[0]].any() or safe[skin.faces].any(axis=1)[0])
        np.testing.assert_array_equal(face_safe_membership(skin,hidden,up,lambda p,r: np.ones(len(p),bool)),hidden)
        self.assertFalse(face_safe_membership(skin,np.zeros(4,bool),up,cutout).any())

    def test_inner_garment_keeps_the_outer_cutout(self):
        blob,_=upgrade_skin(sample_skin(),sample_skin(),clear_hiding=True)
        inner=CompiledSkin(blob)
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);folder=output/'objects/characters/example';folder.mkdir(parents=True)
            (output/'Libs/Tables/Character').mkdir(parents=True)
            for stem in ('body','dress','coat'):
                (folder/(stem+'.skin')).write_bytes(blob)
            component=ET.fromstring('<Component FilePath="example"><DerivedComponents>'
                '<Body><Elements><SkinElement EquipmentPart="torso" Model="body.skin"/></Elements></Body>'
                '<Clothing Name="test_dress"><Elements><SkinElement EquipmentPart="torso" Model="dress.skin"/></Elements></Clothing>'
                '<Clothing Name="test_coat"><Elements><SkinElement EquipmentPart="torso" Model="coat.skin"/></Elements></Clothing>'
                '</DerivedComponents></Component>')
            tables={'item/body_layer':[dict(body_layer_id='1',layer_order='1'),dict(body_layer_id='2',layer_order='2')],
                    'item/armor_archetype2body_subpart':[dict(armor_archetype_id='a',body_layer_id='1',body_subpart_id='torso'),
                                                         dict(armor_archetype_id='b',body_layer_id='2',body_subpart_id='torso')],
                    'item/clothing_raycast':[]}
            garments=[dict(part=dict(kind='cloth',gender_id='2',armor_archetype_id=a),stem=stem,
                           source_model=stem+'.skin',source_material=stem+'.mtl') for stem,a in (('dress','a'),('coat','b'))]
            centroid=np.array([4,1,1])/6@inner.vertices[inner.faces[0]]   # an interior sample of the first triangle, not a vertex
            def covered(points,*args,**kwargs):
                # Every vertex is covered; the coat is cut away over the middle of the dress's first triangle.
                return ~(np.linalg.norm(points-centroid,axis=1)<1e-6)
            with patch('clothing_coverage.native_alpha_surfaces',return_value=([(0,[np.ones((1,1))])]*10,[])),                  patch('clothing_coverage.normals',side_effect=lambda skin: np.tile([0,0,1],(skin.n,1))),                  patch('clothing_coverage.covered_points',side_effect=covered):
                register_coverage(output,component,garments,SimpleNamespace(get=lambda key:dict(rows=tables[key])),'test')
            skin=CompiledSkin((folder/'dress.skin').read_bytes())
            alpha=np.frombuffer(skin.streams[3].data[24:],np.uint8).reshape(-1,4)[:,3]
            coat_bit=1<<(4+1)
            culled=(((255^alpha)&coat_bit)!=0)[skin.faces].any(axis=1)
            self.assertFalse(culled[0])            # the cutout triangle stays drawn
            self.assertTrue(culled.any())          # the rest of the dress under the coat is still hidden

if __name__ == '__main__':
    unittest.main()
