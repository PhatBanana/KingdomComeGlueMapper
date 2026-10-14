"""Build a deterministic offline GI fixture without proprietary game assets."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from voxel_surfaces import Surface, rasterize, build_tile


def quad(a,b,c,d):return np.array([[a,b,c],[a,c,d]],float)


def build(output):
    output=Path(output)
    if output.exists():raise FileExistsError('Use a new fixture output folder')
    # Vertical wall with a real two-metre window opening; opaque floor and
    # a separate alpha-cutout green screen. All positions are positive world units.
    pieces=[quad((1,4,1),(3,4,1),(3,4,5),(1,4,5)),
            quad((5,4,1),(7,4,1),(7,4,5),(5,4,5)),
            quad((3,4,1),(5,4,1),(5,4,2),(3,4,2)),
            quad((3,4,4),(5,4,4),(5,4,5),(3,4,5)),
            quad((1,1,1),(7,1,1),(7,7,1),(1,7,1)),
            quad((2,6,1),(6,6,1),(6,6,4),(2,6,4))]
    uv=np.tile(np.array([[[0,0],[1,0],[1,1]],[[0,0],[1,1],[0,1]]],float),(len(pieces),1,1))
    alpha=np.ones((4,4,4));alpha[::2,::2,3]=0;alpha[1::2,1::2,3]=0
    materials=[Surface(np.ones((1,1,4)),[.65,.12,.06]),Surface(np.ones((1,1,4)),[.3,.3,.3]),Surface(alpha,[.08,.45,.04],alpha_test=.5)]
    triangles=np.concatenate(pieces);ids=np.repeat([0,0,0,0,1,2],2)
    fields=rasterize(triangles,uv,ids,materials,(0,0,0),(32,32,24),.25,4)
    # Opening remains air at the authored wall plane, including its edges' cells.
    if fields['opacity'][9:16,16,13:20].any():raise AssertionError('Window opening filled')
    index,voxels,validation=build_tile(triangles,uv,ids,materials,(0,0,0),16,4,4)
    output.mkdir(parents=True)
    (output/'0008_0008_0008_0016.idx').write_bytes(index)
    (output/'0008_0008_0008_0016.vox').write_bytes(voxels)
    np.savez_compressed(output/'surface-fields.npz',**fields)
    canvas=Image.new('RGB',(1200,450),'#111827');draw=ImageDraw.Draw(canvas)
    for i,(key,label) in enumerate([('opacity','Directional surface coverage'),('albedo','Linear surface albedo'),('normals','World-space geometry normals')]):
        a=fields[key]
        if key=='normals':a=(a*.5+.5)*np.any(fields['opacity'],axis=-1)[...,None]
        # Front projection; these are sampled fields, not a simulated game render.
        picture=Image.fromarray(np.rint(np.clip(a.max(axis=1)[::-1],0,1)*255).astype('uint8'))
        picture=picture.resize((384,288),Image.Resampling.NEAREST)
        canvas.paste(picture,(8+400*i,70));draw.text((12+400*i,35),label,fill='white')
    draw.text((12,390),'Offline analytical fixture: window gap, coloured wall and alpha-cutout screen. Native visual parity is unverified.',fill='#fbbf24')
    canvas.save(output/'channels.png')
    report={'validation':validation,'window_opening_verified':True,'runtime_verified':False,'triangles':len(triangles)}
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path)
    build(p.parse_args().output)
