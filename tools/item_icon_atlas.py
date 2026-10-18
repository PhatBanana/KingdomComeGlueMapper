"""Read authored Scaleform inventory bitmap references without rendering Flash."""
import io
import struct
import zlib
from PIL import Image

class Bits:
    def __init__(self, data, offset=0): self.data,self.bit=data,offset*8
    def take(self,n):
        value=0
        for _ in range(n):
            value=(value<<1)|((self.data[self.bit//8]>>(7-self.bit%8))&1);self.bit+=1
        return value
    def skip(self,n): self.take(n)
    def aligned(self): return (self.bit+7)//8
    def matrix(self):
        if self.take(1): self.skip(self.take(5)*2)
        if self.take(1): self.skip(self.take(5)*2)
        self.skip(self.take(5)*2)
    def color(self):
        add,mult=self.take(1),self.take(1);n=self.take(4)
        self.skip(n*4*(add+mult))


def tags(data,offset=0):
    while offset<len(data):
        if offset+2>len(data): raise ValueError('Truncated GFX tag')
        word=struct.unpack_from('<H',data,offset)[0];offset+=2;size=word&63
        if size==63: size=struct.unpack_from('<I',data,offset)[0];offset+=4
        if offset+size>len(data): raise ValueError('Truncated GFX payload')
        yield word>>6,data[offset:offset+size]
        offset+=size


def placement(data):
    flags=data[0]
    if flags&0xe0: raise ValueError('Unsupported icon placement flags')
    pos=3;character=None
    if flags&2: character=struct.unpack_from('<H',data,pos)[0];pos+=2
    if flags&4:
        bits=Bits(data,pos);bits.matrix();pos=bits.aligned()
    if flags&8:
        bits=Bits(data,pos);bits.color();pos=bits.aligned()
    if flags&16: pos+=2
    # HasName is 0x20; handled separately below by callers when present.
    return character,pos


def atlas_index(blob):
    if blob[:3]!=b'CFX': raise ValueError('Expected compressed source GFX')
    body=zlib.decompress(blob[8:])
    if len(body)+8!=struct.unpack_from('<I',blob,4)[0]: raise ValueError('GFX size mismatch')
    bits=Bits(body);bits.skip(5+4*(body[0]>>3));offset=bits.aligned()+4
    images,rects,shapes,sprites={}, {}, {}, {}
    for code,data in tags(body,offset):
        if code==1009:
            image=struct.unpack_from('<H',data)[0];pos=10
            length=data[pos];pos+=1+length
            length=data[pos];pos+=1
            images[image]='Libs/UI/'+data[pos:pos+length].decode().replace('\\','/')
        elif code==1008:
            if len(data)!=12: raise ValueError('Unsupported GFX subimage')
            char,image,x0,y0,x1,y1=struct.unpack('<6H',data)
            rects[char]=(image,(x0,y0,x1,y1))
        elif code==2:
            char=struct.unpack_from('<H',data)[0];bits=Bits(data,2);bits.skip(5+4*(data[2]>>3));pos=bits.aligned()
            if data[pos:pos+2]==b'\x01\x41': shapes[char]=struct.unpack_from('<H',data,pos+2)[0]
        elif code==39:
            char,frames=struct.unpack_from('<HH',data);sprites[char]=(frames,list(tags(data,4)))
    timelines=[(i,s) for i,s in sprites.items() if s[0]>100]
    if len(timelines)!=1: raise ValueError('Ambiguous source inventory timeline')
    frames,sequence=timelines[0][1];result={};frame=0;placed=None
    for code,data in sequence:
        if code==26:
            char,_=placement(data)
            if char is not None: placed=char
        elif code==28: placed=None
        elif code==1:
            if placed in sprites:
                n,children=sprites[placed]
                leaves=[placement(d)[0] for c,d in children if c==26]
                if n!=1 or len(leaves)>1: raise ValueError('Unsupported composite inventory icon')
                if leaves:
                    bitmap=shapes.get(leaves[0])
                    if bitmap not in rects: raise ValueError('Missing source icon bitmap')
                    image,rect=rects[bitmap]
                    result[str(frame+1)]=(images[image],rect)
                else:
                    result[str(frame+1)]=(None,None) # Authored empty frame, not a missing dependency.
            frame+=1
    if frame!=frames: raise ValueError('Inventory timeline frame mismatch')
    return result


def texture(image,rect):
    x0,y0,x1,y1=rect
    if not (0<=x0<x1<=image.width and 0<=y0<y1<=image.height): raise ValueError('Invalid icon atlas bounds')
    icon=image.crop(rect).convert('RGBA')
    if icon.width>64 or icon.height>64:
        icon.thumbnail((64,64),Image.Resampling.LANCZOS)
    canvas=Image.new('RGBA',(64,64));canvas.paste(icon,((64-icon.width)//2,(64-icon.height)//2))
    stream=io.BytesIO();canvas.save(stream,format='DDS');return stream.getvalue()
