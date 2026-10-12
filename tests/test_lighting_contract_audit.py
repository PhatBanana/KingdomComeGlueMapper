"""Reject malformed clipping dependencies rather than guessing containment."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from audit_lighting_contract import bsp_contains, clip_geometry
from lighting_clips import associate_probe_clips


class LightingContractAuditTests(unittest.TestCase):
    def test_capture_clip_uses_bake_offset_without_moving_probe(self):
        probe=E.fromstring('<Entity EntityId="1" Pos="5,0,0"><Properties GenOffsetX="-4"><Options bDeferredClipBounds="1"/></Properties></Entity>')
        clip=E.fromstring('<Entity EntityId="2" Pos="0,0,0"><ClipVolume GeometryFileName="%level%/room.cgf"/></Entity>')
        defaults=E.fromstring('<Properties><Options bDeferredClipBounds="0"/></Properties>')
        shape=({'local_bounds': [[-2,-2,-2],[2,2,2]]},[(1,0,0,-2,-1,-1)])
        with patch('lighting_clips.clip_geometry',return_value=shape):
            report=associate_probe_clips([probe],[clip],{'1':probe,'2':clip},lambda _:b'',defaults,apply=True)
        self.assertEqual(report[0]['capture'],(1,0,0))
        self.assertEqual(probe.find('EntityLinks/Link').get('TargetId'),'2')
        self.assertEqual(probe.get('Pos'),'5,0,0')

    def test_containment_does_not_enable_unverified_links_by_default(self):
        probe=E.fromstring('<Entity EntityId="1"><Properties><Options bDeferredClipBounds="1"/></Properties></Entity>')
        clip=E.fromstring('<Entity EntityId="2"><ClipVolume GeometryFileName="%level%/room.cgf"/></Entity>')
        shape=({'local_bounds':[[-2,-2,-2],[2,2,2]]},[(1,0,0,-2,-1,-1)])
        with patch('lighting_clips.clip_geometry',return_value=shape):
            report=associate_probe_clips([probe],[clip],{},lambda _:b'',E.fromstring('<Properties><Options/></Properties>'))
        self.assertEqual(report[0]['status'],'candidate')
        self.assertIsNone(probe.find('EntityLinks'))

    def test_ambiguous_clips_do_not_create_links(self):
        probe=E.fromstring('<Entity EntityId="1"><Properties><Options bDeferredClipBounds="1"/></Properties></Entity>')
        clips=[E.fromstring(f'<Entity EntityId="{i}"><ClipVolume GeometryFileName="%level%/room.cgf"/></Entity>') for i in (2,3)]
        shape=({'local_bounds':[[-2,-2,-2],[2,2,2]]},[(1,0,0,-2,-1,-1)])
        with patch('lighting_clips.clip_geometry',return_value=shape):
            report=associate_probe_clips([probe],clips,{},lambda _:b'',E.fromstring('<Properties><Options/></Properties>'))
        self.assertEqual(report[0]['status'],'ambiguous')
        self.assertIsNone(probe.find('EntityLinks'))

    def test_bsp_terminal_sides_and_border(self):
        nodes = [(1, 0, 0, -2, -1, -1)]
        self.assertTrue(bsp_contains(nodes, (1, 0, 0)))
        self.assertFalse(bsp_contains(nodes, (3, 0, 0)))
        self.assertFalse(bsp_contains(nodes, (2, 0, 0)))

    def test_bsp_cycle_is_not_an_interior_match(self):
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            bsp_contains([(1, 0, 0, 0, 0, -1)], (1, 0, 0))

    def test_clip_chunk_cannot_point_outside_archive_member(self):
        blob = b'CrChF\x07\0\0' + struct.pack('<II', 1, 16)
        blob += struct.pack('<HHIII', 0x3009, 1, 1, 128, 32)
        with self.assertRaisesRegex(ValueError, 'exceeds file'):
            clip_geometry(blob)


if __name__ == '__main__':
    unittest.main()
