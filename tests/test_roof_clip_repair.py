"""Map-wide roof ownership, placement, packing and rebuild regressions."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from build_roof_clip_test import material_triangles, fit_plane
from clothing_regions import read_chunks, write_chunks
from roof_clip_repair import containment, entity_transform, repair
from test_clip_volume_mesh import fixture, cube


class RoofClipRepairTests(unittest.TestCase):
    def scene(self, rotation='1,0,0,0', scale='1,1,1', position='0,0,0'):
        root = ET.fromstring('<Objects><Entities/></Objects>')
        entities = root.find('Entities')
        clip = ET.SubElement(entities, 'Entity', EntityClass='ClipVolume', Name='room', EntityId='1',
                             EntityGuid='clip-guid', Pos=position, Rotate=rotation, Scale=scale)
        ET.SubElement(clip, 'ClipVolume', GeometryFileName='%level%/brush/gm_lighting_room.cgf')
        linear, translation = entity_transform(clip)
        origin = translation+linear @ [-.1, .5, .3]
        probe = ET.SubElement(entities, 'Entity', EntityClass='EnvironmentLight', Name='probe', EntityId='2',
                              Pos=','.join(map(str, origin)), Rotate=rotation, Scale=scale)
        props = ET.SubElement(probe, 'Properties', bActive='1', GenOffsetX='.4')
        ET.SubElement(props, 'Options', bIgnoresVisAreas='1', bDeferredClipBounds='0', bAffectsThisAreaOnly='0')
        outer = np.array([[[.1,.1,.5], [.6,.1,1], [.6,.9,1]],
                          [[.1,.1,.5], [.6,.9,1], [.1,.9,.5]]])
        self.model = {'outer': outer, 'inner': (outer-[0,0,.2])[:, ::-1], 'material': 'roof.mtl', 'sha256': 'fixture'}
        self.place = {'mesh': 'roof.cgf', 'material': '', 'transform': np.column_stack((linear, translation)).ravel().tolist()}
        return root

    def run_repair(self, root, overrides=None):
        files = {'objects_mission0.xml': ET.tostring(root), 'terrain/hlods.dat': b'',
                 'brush/gm_lighting_room.cgf': fixture()}
        files.update(overrides or {})
        assets = type('Assets', (), {'entries': {'roof.cgf': None}})()
        with patch('roof_clip_repair.placements', return_value=[self.place]), \
             patch('roof_clip_repair.roof_model', return_value=self.model):
            changes, report = repair(files, b'', assets, {'probe'})
        return files, changes, report

    def test_rotated_scaled_placement_and_capture_offset_then_idempotence(self):
        root = self.scene('0.923879533,0,0,0.382683432', '2,3,1.5', '2400,3100,90')
        files, changes, report = self.run_repair(root)
        self.assertEqual(report['changed_clip_count'], 1)
        self.assertEqual(report['linked_probe_count'], 1)
        probe = ET.fromstring(changes['objects_mission0.xml']).find(".//Entity[@Name='probe']")
        self.assertEqual(probe.find('EntityLinks/Link').attrib,
                         dict(Name='ClipVolume', TargetId='1', TargetGuid='clip-guid'))
        self.assertEqual(probe.find('Properties/Options').get('bAffectsThisAreaOnly'), '1')
        # The fitted surface is defined by the roof, independent of world pose.
        plane = report['clips'][0]['fits'][0]['clip_plane']
        self.assertTrue(np.all(self.model['inner'].reshape(-1,3) @ plane[:3]+plane[3] < 0))
        self.assertTrue(np.all(self.model['outer'].reshape(-1,3) @ plane[:3]+plane[3] > 0))
        _, again, _ = self.run_repair(root, changes)
        self.assertEqual(again, {})

    def test_overlapping_volume_does_not_get_guessed_probe_owner(self):
        root = self.scene()
        extra = ET.fromstring(ET.tostring(root.find(".//Entity[@Name='room']")))
        extra.set('Name', 'overlapping'); extra.set('EntityId', '3')
        extra.find('ClipVolume').set('GeometryFileName', '%level%/brush/gm_lighting_second.cgf')
        root.find('Entities').append(extra)
        _, changes, report = self.run_repair(root, {'brush/gm_lighting_second.cgf': fixture()})
        self.assertEqual(report['changed_clip_count'], 2)
        self.assertEqual(report['linked_probe_count'], 0)
        self.assertNotIn('objects_mission0.xml', changes)

    def test_disabled_probe_and_explicit_other_owner_are_preserved(self):
        for disabled in (True, False):
            root = self.scene()
            probe = root.find(".//Entity[@Name='probe']")
            if disabled:
                probe.find('Properties').set('bActive', '0')
            else:
                ET.SubElement(ET.SubElement(probe, 'EntityLinks'), 'Link', Name='Authored', TargetId='99')
            _, changes, report = self.run_repair(root)
            self.assertEqual(report['changed_clip_count'], 1)
            self.assertNotIn('objects_mission0.xml', changes)

    def test_bsp_halfspace_is_bounded_and_boundary_points_excluded(self):
        nodes = [(0,0,1,-1,-1,-1)]
        result = containment(nodes, [[0,0,0],[1,1,1]], [[.5,.5,.5], [100,.5,.5], [.5,.5,-100], [0,.5,.5]])
        self.assertEqual(result.tolist(), [True, False, False, False])

    def test_node_transform_and_interleaved_position_stream(self):
        chunks = read_chunks(fixture())
        replacements = {}
        for c in chunks:
            if c.kind == 0x100b:
                data = bytearray(c.data)
                tm = np.array([[0,1,0,0],[-1,0,0,0],[0,0,1,0],[200,300,400,0]], dtype='<f4')
                struct.pack_into('<16f', data, 84, *tm.ravel())
                replacements[c.id] = bytes(data)
            elif c.kind == 0x1000:
                data = bytearray(c.data)
                struct.pack_into('<I', data, 28, 0)
                struct.pack_into('<I', data, 28+15*4, 1)
                replacements[c.id] = bytes(data)
            elif c.id == 1:
                positions = cube().reshape(-1,3)
                packed = np.zeros((len(positions),8), dtype='<f2')
                packed[:,:3] = positions
                replacements[c.id] = struct.pack('<6I',0,15,len(positions),16,0,0)+packed.tobytes()
        result = material_triangles(write_chunks(chunks, replacements), 0)
        expected = cube() @ np.array([[0,1,0],[-1,0,0],[0,0,1]])+[2,3,4]
        np.testing.assert_allclose(result, expected)
        self.assertEqual(material_triangles(fixture(), [0, 99]).shape, (12,3,3))
        self.assertEqual(material_triangles(fixture(), 99, allow_empty=True).shape, (0,3,3))

    def test_opposite_ends_are_not_paired_as_roof_thickness(self):
        self.scene()
        with self.assertRaisesRegex(ValueError, 'footprint'):
            fit_plane(self.model['inner'], self.model['outer']+[-10,0,0], -1, [0,1])


if __name__ == '__main__':
    unittest.main()
