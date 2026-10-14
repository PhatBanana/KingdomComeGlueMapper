"""Analytical coverage and transform tests for the independent voxel experiment."""
from pathlib import Path
import sys
import struct
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from geometry_opacity import coverage, transform_triangles, cgf_triangles
from clothing_regions import Chunk, write_chunks, read_chunks


def quad(x0, x1, y0, y1, z):
    return np.array([[[x0,y0,z], [x1,y0,z], [x1,y1,z]],
                     [[x0,y0,z], [x1,y1,z], [x0,y1,z]]], dtype=float)


class GeometryOpacityTests(unittest.TestCase):
    def mesh_fixture(self, transform=None, bad_index=False):
        positions = np.array([[0,0,0], [1,0,0], [0,1,0]], dtype='<f4')
        pos = Chunk(0x1016, 0x800, 1, struct.pack('<6I',0,0,3,12,0,0)+positions.tobytes())
        idx = Chunk(0x1016, 0x800, 2, struct.pack('<6I',0,5,3,2,0,0)+struct.pack('<3H',0,1,4 if bad_index else 2))
        sub = Chunk(0x1017, 0x800, 3, struct.pack('<4I',0,1,0,0)+struct.pack('<5I4f',0,3,0,3,0,1,0,0,0))
        mesh = bytearray(264)
        struct.pack_into('<6I',mesh,0,0,0,3,3,1,3)
        struct.pack_into('<I',mesh,28,1)
        struct.pack_into('<I',mesh,48,2)
        node = bytearray(204)
        node[:4] = b'wall'
        struct.pack_into('<4i',node,64,4,-1,0,6)
        tm = np.eye(4) if transform is None else transform
        struct.pack_into('<16f',node,84,*tm.flatten())
        material = Chunk(0x1014,0x802,6,b'wall_material'.ljust(128,b'\0'))
        proxy = bytearray(node)
        proxy[:64] = b'$physics_proxy'.ljust(64,b'\0')
        return write_chunks([pos,idx,sub,Chunk(0x1000,0x800,4,bytes(mesh)),
                             Chunk(0x100b,0x824,5,bytes(node)),material,
                             Chunk(0x100b,0x824,7,bytes(proxy))], {})

    def test_cgf_reads_render_mesh_without_duplicate_physics(self):
        triangles, info = cgf_triangles(self.mesh_fixture())
        self.assertEqual(triangles.shape, (1,3,3))
        self.assertEqual(info['excluded_nodes'], ['$physics_proxy'])
        self.assertEqual(info['bindings'][0]['material'], 'wall_material')
        self.assertEqual(info['bindings'][0]['subset_triangles'], {0:1})

    def test_cgf_centimetre_translation_and_rotation(self):
        tm = np.eye(4)
        tm[:3,:3] = [[0,1,0],[-1,0,0],[0,0,1]]
        tm[3,:3] = [100,200,300]
        tri,_ = cgf_triangles(self.mesh_fixture(transform=tm))
        np.testing.assert_allclose(tri[0],[[1,2,3],[1,3,3],[0,2,3]])
        with self.assertRaises(ValueError):cgf_triangles(self.mesh_fixture(bad_index=True))

    def test_packed_vertices_uv_and_helper_exclusion(self):
        chunks = read_chunks(self.mesh_fixture())
        packed = np.zeros((3,8),dtype='<f2')
        packed[:,:3] = [[0,0,0],[1,0,0],[0,1,0]]
        packed[:,6:] = [[0,0],[1,0],[0,1]]
        chunks[0] = Chunk(0x1016,0x800,1,struct.pack('<6I',0,15,3,16,0,0)+packed.tobytes())
        for i,c in enumerate(chunks):
            if c.kind == 0x1000:
                data=bytearray(c.data)
                struct.pack_into('<I',data,28,0)
                struct.pack_into('<I',data,28+15*4,1)
                chunks[i]=Chunk(c.kind,c.version,c.id,bytes(data))
        helper=bytearray(next(c.data for c in chunks if c.id==5))
        helper[:64]=b'slt_0'.ljust(64,b'\0')
        struct.pack_into('<i',helper,64,9)
        chunks += [Chunk(0x100b,0x824,8,bytes(helper)),Chunk(0x1001,0x744,9,bytes(16))]
        tri,info=cgf_triangles(write_chunks(chunks,{}),with_surface=True)
        np.testing.assert_array_equal(tri[0],packed[:,:3])
        np.testing.assert_array_equal(info['surfaces'][0]['uv'][0],packed[:,6:])
        self.assertIn('slt_0',info['excluded_nodes'])

    def test_parent_helper_transform_and_cycle_detection(self):
        chunks=read_chunks(self.mesh_fixture())
        child=next(c for c in chunks if c.id==5)
        data=bytearray(child.data);struct.pack_into('<i',data,68,8)
        parent=bytearray(child.data);parent[:64]=b'parent'.ljust(64,b'\0')
        struct.pack_into('<4i',parent,64,9,-1,1,6)
        matrix=np.eye(4);matrix[3,:3]=[200,300,400]
        struct.pack_into('<16f',parent,84,*matrix.flatten())
        chunks=[Chunk(c.kind,c.version,c.id,bytes(data)) if c.id==5 else c for c in chunks]
        chunks += [Chunk(0x100b,0x824,8,bytes(parent)),Chunk(0x1001,0x744,9,bytes(16))]
        triangles,_=cgf_triangles(write_chunks(chunks,{}))
        np.testing.assert_array_equal(triangles[0],[[2,3,4],[3,3,4],[2,4,4]])
        struct.pack_into('<i',parent,68,5)
        chunks[-2]=Chunk(0x100b,0x824,8,bytes(parent))
        with self.assertRaisesRegex(ValueError,'Cyclic'):cgf_triangles(write_chunks(chunks,{}))

    def test_plane_direction_and_location(self):
        grid = coverage(quad(1, 3, 0, 2, 2.5), (0,0,0), (4,3,4), 1)
        self.assertFalse(grid[..., :2].any())
        expected = np.zeros((4,3,4), np.uint8)
        expected[2, :2, 1:3] = 255
        np.testing.assert_array_equal(grid[..., 2], expected)

    def test_overlap_does_not_double_count(self):
        tris = quad(0, .5, 0, 1, .5)
        one = coverage(tris, (0,0,0), (1,1,1), 1)
        many = coverage(np.concatenate([tris, tris, tris[:, ::-1]]), (0,0,0), (1,1,1), 1)
        self.assertEqual(one[0,0,0,2], 128)
        np.testing.assert_array_equal(one, many)

    def test_open_window_remains_empty(self):
        tris = np.concatenate([quad(0,1,0,4,.5), quad(3,4,0,4,.5),
                               quad(1,3,0,1,.5), quad(1,3,3,4,.5)])
        grid = coverage(tris, (0,0,0), (4,4,1), 1)
        self.assertFalse(grid[0,1:3,1:3].any())
        self.assertEqual(np.count_nonzero(grid[...,2]), 12)

    def test_rotated_translated_plane_uses_world_axes(self):
        # Rotate +90 around Y, then translate; original horizontal plane becomes
        # an X-facing wall. A forgotten/doubled rotation hits the wrong channel.
        matrix = [0,0,1,10, 0,1,0,20, -1,0,0,32]
        tris = transform_triangles(quad(0,2,0,2,.5), matrix)
        grid = coverage(tris, (10,20,30), (2,2,2), 1)
        self.assertEqual(np.count_nonzero(grid[...,0]), 4)
        self.assertTrue((grid[:,:,0,0] == 255).all())
        self.assertFalse(grid[...,1:].any())

    def test_sloped_roof_coverage_and_empty_space(self):
        tris = quad(0,4,0,4,0)
        tris[:,:,2] = tris[:,:,0]+.25
        grid = coverage(tris, (0,0,0), (4,4,5), 1)
        self.assertFalse(grid[...,1].any())
        self.assertTrue(grid[...,0].any())
        self.assertTrue(grid[...,2].any())
        z, y, x = np.nonzero(grid[...,2])
        self.assertTrue(np.all((z == x) | (z == x+1)))
        # Each complete projected column still covers exactly one cell face.
        np.testing.assert_array_equal(grid[...,2].astype(int).sum(axis=0), np.full((4,4),255))

    def test_half_open_grid_boundary(self):
        grid = coverage(quad(0,2,0,2,2), (0,0,0), (2,2,2), 1)
        self.assertFalse(grid.any())

    def test_degenerate_and_outside_triangles(self):
        tris = np.concatenate([np.zeros((1,3,3)), quad(-10,-9,-10,-9,.5)])
        self.assertFalse(coverage(tris,(0,0,0),(2,2,2),1).any())

    def test_grid_parameters_rejected(self):
        tris = quad(0,1,0,1,.5)
        for shape, size, samples in [((0,1,1),1,4), ((257,1,1),1,4),
                                      ((1.5,1,1),1,4), ((1,1,1),0,4),
                                      ((1,1,1),float('nan'),4), ((1,1,1),1,3)]:
            with self.assertRaises(ValueError):
                coverage(tris,(0,0,0),shape,size,samples)

    def test_nonfinite_and_singular_geometry_rejected(self):
        with self.assertRaises(ValueError):
            transform_triangles(quad(0,1,0,1,.5), [0]*12)
        with self.assertRaises(ValueError):
            coverage(np.full((1,3,3),np.nan),(0,0,0),(1,1,1),1)


if __name__ == '__main__':
    unittest.main()
