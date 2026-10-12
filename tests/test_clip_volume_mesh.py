"""Render-stencil/BSP agreement for geometry-constrained probe clipping."""
from pathlib import Path
import struct
import sys
import unittest
from collections import Counter

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from clothing_regions import Chunk, read_chunks, write_chunks
from clip_volume_mesh import intersect_clip, intersect_triangles, read_clip_mesh
from lighting_clips import clip_geometry, bsp_contains
from build_roof_clip_test import fit_plane


def cube():
    points = np.array([[0,0,0], [1,0,0], [1,1,0], [0,1,0],
                       [0,0,1], [1,0,1], [1,1,1], [0,1,1]], float)
    faces = [[0,2,1], [0,3,2], [4,5,6], [4,6,7], [0,1,5], [0,5,4],
             [1,2,6], [1,6,5], [2,3,7], [2,7,6], [3,0,4], [3,4,7]]
    return points[np.array(faces)]


def fixture():
    tris = cube()
    count = tris.size//3
    pos = Chunk(0x1016, 0x800, 1, struct.pack('<6I',0,0,count,12,0,0)+tris.astype('<f4').tobytes())
    idx = Chunk(0x1016, 0x800, 2, struct.pack('<6I',0,5,count,2,0,0)+np.arange(count,dtype='<u2').tobytes())
    sub = Chunk(0x1017, 0x800, 3, struct.pack('<4I',0,1,0,0)+struct.pack('<5I4f',0,count,0,count,0,1,.5,.5,.5))
    mesh = bytearray(264)
    struct.pack_into('<6I',mesh,0,10,4,count,count,1,3)
    struct.pack_into('<I',mesh,28,1)
    struct.pack_into('<I',mesh,48,2)
    struct.pack_into('<6f',mesh,108,0,0,0,1,1,1)
    node = bytearray(204)
    struct.pack_into('<4i',node,64,4,-1,0,6)
    struct.pack_into('<16f',node,84,*np.eye(4).ravel())
    planes = [(1,0,0,-1), (-1,0,0,0), (0,1,0,-1), (0,-1,0,0), (0,0,1,-1), (0,0,-1,0)]
    bsp = struct.pack('<I',6)+b''.join(struct.pack('<4fii',*p,-1,i+1 if i<5 else -1) for i,p in enumerate(planes))
    return write_chunks([pos,idx,sub,Chunk(0x1000,0x801,4,bytes(mesh)),
                         Chunk(0x100b,0x824,5,bytes(node)),Chunk(0x1014,0x802,6,bytes(136)),
                         Chunk(0x3009,1,7,bsp)], {})


def ray_inside(triangles, point):
    # Independent render-mesh containment: ray intersections, not the BSP.
    direction = np.array([.819, .337, .465])
    a, e1, e2 = triangles[:,0], triangles[:,1]-triangles[:,0], triangles[:,2]-triangles[:,0]
    h = np.cross(np.broadcast_to(direction,e2.shape),e2)
    det = np.einsum('ij,ij->i',e1,h)
    valid = np.abs(det)>1e-10
    inv = np.divide(1,det,out=np.zeros_like(det),where=valid)
    s = point-a
    u = np.einsum('ij,ij->i',s,h)*inv
    q = np.cross(s,e1)
    v = (q @ direction)*inv
    distance = np.einsum('ij,ij->i',e2,q)*inv
    hits = distance[valid & (u>=0) & (v>=0) & (u+v<=1) & (distance>1e-8)]
    return len(np.unique(np.round(hits,8))) % 2 == 1


class ClipVolumeMeshTests(unittest.TestCase):
    def test_sloped_cut_render_mesh_and_bsp_match_analytic_solid(self):
        converted = intersect_clip(fixture(), [-.5, .1, 1, -.4])
        triangles, chunks, mesh, subset, streams = read_clip_mesh(converted)
        info, bsp = clip_geometry(converted)
        self.assertEqual(info['bsp_nodes'],7)
        rng = np.random.default_rng(83)
        for p in rng.uniform(-.2,1.2,(500,3)):
            expected = bool(np.all((p>0)&(p<1)) and -.5*p[0]+.1*p[1]+p[2] < .4)
            self.assertEqual(bsp_contains(bsp,p),expected)
            self.assertEqual(ray_inside(triangles,p),expected)
        # Unrelated node and material dependencies are byte-identical.
        before = {c.id:c.data for c in read_chunks(fixture())}
        for c in chunks:
            if c.kind in (0x100b,0x1014):
                self.assertEqual(c.data,before[c.id])
        self.assertAlmostEqual(max(p[2] for p in triangles.reshape(-1,3)),.9,places=6)
        np.testing.assert_allclose(struct.unpack_from('<6f',mesh.data,108),
                                   np.r_[triangles.min((0,1)),triangles.max((0,1))])

    def test_cap_winding_preserves_positive_solid_volume(self):
        triangles = intersect_triangles(cube(),[0,0,1,-.5])
        volume = np.einsum('ij,ij->i',triangles[:,0],np.cross(triangles[:,1],triangles[:,2])).sum()/6
        self.assertAlmostEqual(volume,.5)
        cap = triangles[np.all(np.abs(triangles[:,:,2]-.5)<1e-8,axis=1)]
        self.assertGreater(len(cap),0)
        self.assertTrue(np.all(np.cross(cap[:,1]-cap[:,0],cap[:,2]-cap[:,0])[:,2]>0))

    def test_complete_removal_and_invalid_plane_fail(self):
        for plane in ([0,0,1,2],[0,0,0,0],[float('nan'),0,1,0]):
            with self.assertRaises(ValueError):
                intersect_clip(fixture(),plane)

    def test_multiple_cut_contours_are_not_silently_filled(self):
        tris=np.concatenate((cube(),cube()+[2,0,0]))
        with self.assertRaisesRegex(ValueError,'Multiple'):
            intersect_triangles(tris,[0,0,1,-.5])

    def test_near_vertex_cut_stays_watertight_after_seam_welding(self):
        result = intersect_triangles(cube(), [-.4, .001, 1, -.9999])
        edges = Counter((tuple(a),tuple(b)) for tri in result for a,b in zip(tri,np.roll(tri,-1,axis=0)))
        for (a,b), count in edges.items():
            self.assertEqual(count, 1)
            self.assertEqual(edges[(b,a)], 1)

    def test_measured_roof_plane_preserves_gap_and_rejects_intersection(self):
        outer=np.array([[[-3,-2,2], [0,-2,5], [0,2,5]],
                        [[-3,-2,2], [0,2,5], [-3,2,2]]],float)
        # This winding faces (-X,+Z); the interior faces the other way.
        inner=(outer-[0,0,.5])[:,::-1]
        plane,report=fit_plane(inner,outer,-1,[-2,2])
        self.assertGreater(report['gap_metres'],.3)
        self.assertTrue(np.all(inner.reshape(-1,3)@plane[:3]+plane[3]<0))
        self.assertTrue(np.all(outer.reshape(-1,3)@plane[:3]+plane[3]>0))
        with self.assertRaisesRegex(ValueError,'No verified gap'):
            fit_plane(outer[:,::-1],outer,-1,[-2,2])


if __name__=='__main__':
    unittest.main()
