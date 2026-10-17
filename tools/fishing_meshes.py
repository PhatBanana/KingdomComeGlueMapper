"""Bake fishing geometry dimensions and materials into native streamed meshes."""
import io
import math
import struct
from PIL import Image
from clothing_regions import Chunk, read_chunks, write_chunks
from upgrade_map import read, xml
import xml.etree.ElementTree as ET


def rod_resources(archive):
    """Clone the equipped static rod, adding a helper at its measured mesh tip.

    Node transforms are stored in centimetres in this compiled CGF; mesh bounds
    are metres. Preserve pickup/slot helpers, materials and streaming geometry.
    """
    source='Objects/manmade/task_specific_props/foraging/fishing/fishing_rod'
    target='Objects/GMFishing/rod'
    chunks=read_chunks(read(archive,source+'.cgf'))
    root=next(c for c in chunks if c.kind==0x100b and c.data[:7]==b'Box001\0')
    template=next(c for c in chunks if c.kind==0x100b and c.data[:7]==b'plc_01\0')
    mesh_id=struct.unpack_from('<i',root.data,64)[0]
    mesh=next(c for c in chunks if c.id==mesh_id)
    top=struct.unpack_from('<6f',mesh.data,108)[5]
    assert 1.8<top<1.9
    helper_id=max(c.id for c in chunks)+1
    object_id=struct.unpack_from('<i',template.data,64)[0]
    helper=next(c for c in chunks if c.id==object_id)
    node=bytearray(template.data)
    name=b'gm_fishing_tip';node[:64]=name+bytes(64-len(name))
    struct.pack_into('<4i',node,64,helper_id,root.id,0,0)
    struct.pack_into('<16f',node,84,1,0,0,0,0,1,0,0,0,0,1,0,0,0,top*100,0)
    parent=bytearray(root.data)
    struct.pack_into('<i',parent,72,struct.unpack_from('<i',parent,72)[0]+1)
    chunks.extend([Chunk(helper.kind,helper.version,helper_id,helper.data),
                   Chunk(template.kind,template.version,helper_id+1,bytes(node))])
    return {target+'.cgf':write_chunks(chunks,{root.id:bytes(parent)}),
            target+'.cgfm':read(archive,source+'.cgfm')}


def bake(blob,scale,material,irregular=False):
    chunks=read_chunks(blob);changes={}
    for c in chunks:
        d=bytearray(c.data)
        if c.kind==0x1014 and c.version==0x802:
            name=material.encode();assert len(name)<128
            d[:128]=name+bytes(128-len(name))
        elif c.kind==0x1016:
            _,kind,count,width=struct.unpack_from('<4I',d)
            if kind==15:
                assert width==16 and len(d)==24+count*16
                for i in range(count):
                    off=24+i*width
                    p=struct.unpack_from('<3e',d,off)
                    if irregular:
                        # Mild egg taper and uneven hand-cut silhouette; only
                        # shrink XY, retaining the conservative original bounds.
                        taper=.92-.065*p[2]+.015*math.sin(p[2]*9+p[0]*3)
                        p=(p[0]*taper,p[1]*(taper-.025*math.sin(p[0]*7)),p[2])
                    struct.pack_into('<3e',d,off,*(p[j]*scale[j] for j in range(3)))
        elif c.kind==0x1000:
            assert c.version==0x801 and len(d)==264
            bounds=struct.unpack_from('<6f',d,108)
            struct.pack_into('<6f',d,108,*(bounds[j]*scale[j%3] for j in range(6)))
        elif c.kind==0x1017:
            count=struct.unpack_from('<I',d,4)[0]
            for i in range(count):
                off=16+i*36
                radius,*center=struct.unpack_from('<4f',d,off+20)
                struct.pack_into('<4f',d,off+20,radius*max(scale),*(center[j]*scale[j] for j in range(3)))
        changes[c.id]=bytes(d)
    return write_chunks(chunks,changes)


def resources(archive):
    result={}
    for name,shape,scale,color in [
        ('float','sphere',(.010,.009,.015),'1,1,1'),
        ('stem','cylinder',(.00065,.00065,.019),'0.65,0.46,0.24'),
        ('knot','sphere',(.0012,.0012,.0018),'0.40,0.30,0.17'),
        ('quill','sphere',(.0022,.0018,.04),'0.87,0.84,0.68'),
        ('quill_tip','sphere',(.0018,.0015,.012),'0.60,0.055,0.025'),
        ('line','cylinder',(.0015,.0015,.5),'0.65,0.57,0.4')]:
        stem='Objects/GMFishing/'+name
        for ext in ('cgf','cgfm'):
            result[stem+'.'+ext]=bake(read(archive,'Objects/special/primitive_'+shape+'.'+ext),scale,stem,irregular=name=='float')
        m=ET.Element('Material',MtlFlags='524288',Shader='Illum',GenMask='0',StringGenMask='',Diffuse=color,Specular='0.01,0.01,0.01',Emissive='0,0,0',Shininess='4',Opacity='1')
        ET.SubElement(ET.SubElement(m,'Textures'),'Texture',Map='Diffuse',File='Objects/GMFishing/'+('cork.dds' if name=='float' else 'white.dds'))
        result[stem+'.mtl']=xml(m)
    stream=io.BytesIO();Image.new('RGBA',(4,4),(255,255,255,255)).save(stream,format='DDS')
    result['Objects/GMFishing/white.dds']=stream.getvalue()
    # Granular tan cork with irregular dark pores, not longitudinal wood grain.
    import random
    from PIL import ImageDraw
    rng=random.Random(731)
    cork=Image.new('RGBA',(128,128))
    for y in range(128):
        for x in range(128):
            fleck=rng.randrange(-20,21)
            cork.putpixel((x,y),(190+fleck,151+fleck,102+fleck,255))
    draw=ImageDraw.Draw(cork)
    for _ in range(350):
        x,y=rng.randrange(128),rng.randrange(128)
        draw.ellipse((x,y,x+rng.randrange(1,4),y+rng.randrange(1,3)),fill=(110,79,48,255))
    stream=io.BytesIO();cork.save(stream,format='DDS')
    result['Objects/GMFishing/cork.dds']=stream.getvalue()
    return result
