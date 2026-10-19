"""Build native parent-payload proxy links and bounded spatial HLOD trees.

ProxyIndex is an index into the parent's render-node list, verified against
native KCD2 compiled groups. Near records are preserved byte-for-byte.
"""
from dataclasses import dataclass, field
import math
import struct
import xml.etree.ElementTree as ET
import zlib


@dataclass
class Group:
    name: str
    kind: str
    center: tuple
    radius: float
    records: list = field(default_factory=list)
    proxy: bytes | None = None
    children: list = field(default_factory=list)


def records(payload):
    offset=0;result=[]
    while offset<len(payload):
        if offset+4>len(payload):raise ValueError('Truncated HLOD record')
        kind=struct.unpack_from('<I',payload,offset)[0]
        size={1:104,2:64}.get(kind)
        if size is None or offset+size>len(payload):raise ValueError('Unsupported HLOD record')
        result.append(payload[offset:offset+size]);offset+=size
    return result


def read_groups(document, data):
    if struct.unpack_from('<I',data)[0]!=2:raise ValueError('Unsupported HLOD version')
    result=[];spans=[]
    for node in document.iter('HLod'):
        offset,size=int(node.get('DataOffset')),int(node.get('DataSize'))
        if offset<4 or size<4 or offset+size>len(data):raise ValueError('Invalid HLOD block extent')
        if struct.unpack_from('<I',data,offset)[0]!=size-4:raise ValueError('HLOD block size mismatch')
        spans.append((offset,offset+size))
        if node.get('ProxyIndex','-1')!='-1':raise ValueError('Already contains proxy links; refusing duplicate conversion')
        result.extend(records(data[offset+4:offset+size]))
    spans.sort()
    if not spans or spans[0][0]!=4 or spans[-1][1]!=len(data) or any(a[1]!=b[0] for a,b in zip(spans,spans[1:])):
        raise ValueError('Overlapping or uncovered HLOD payloads')
    return result


def bounds(items):
    low=[min(g.center[a]-g.radius for g in items) for a in range(3)]
    high=[max(g.center[a]+g.radius for g in items) for a in range(3)]
    center=tuple((x+y)/2 for x,y in zip(low,high))
    return center,max(math.dist(center,g.center)+g.radius for g in items)


def hierarchy(leaves, name='world', fanout=16):
    if not leaves or fanout<2:raise ValueError('Invalid spatial grouping input')
    for g in leaves:
        if not all(math.isfinite(x) for x in (*g.center,g.radius)) or g.radius<0:raise ValueError('Invalid group bounds')
    center,radius=bounds(leaves)
    if len(leaves)<=fanout:
        return Group(name,'Cluster',center,radius,children=leaves)
    axis=max(range(3),key=lambda a:max(g.center[a] for g in leaves)-min(g.center[a] for g in leaves))
    ordered=sorted(leaves,key=lambda g:(g.center[axis],g.name))
    middle=len(ordered)//2
    children=[hierarchy(ordered[:middle],name+'_0',fanout),hierarchy(ordered[middle:],name+'_1',fanout)]
    # Child enclosing spheres can extend beyond the original leaf envelope.
    center,radius=bounds(children)
    return Group(name,'Cluster',center,radius,children=children)


def world_hierarchy(leaves, cell_size=64, *, height=None):
    """Native topology: Main layer and a separate three-tier vegetation grid.

    KCD2 indexes vegetation switching distances by hierarchy tier. Arbitrarily
    deep mixed Cluster/Vegetation trees do not preserve that runtime contract.
    Intermediate vegetation tiers have no proxy until a coarser source exists.
    """
    from collections import defaultdict
    from dataclasses import replace
    from hlod_spatial_metadata import instance_cells, grid_metadata
    if height is not None and cell_size != 64:
        raise ValueError('Native vegetation metadata requires 64m cells')
    vegetation=defaultdict(lambda: defaultdict(list)); brushes=[]
    for leaf in leaves:
        if leaf.kind != 'Vegetation':
            brushes.append(leaf);continue
        if height is not None:
            cells = instance_cells(leaf.records)
            center, radius = grid_metadata(cells, 4, height)
            leaf = replace(leaf, center=center, radius=radius)
            x, y = next(iter(cells))
        else:
            x,y=(math.floor(leaf.center[i]/cell_size) for i in range(2))
        vegetation[(x//16,y//16)][(x//4,y//4)].append(leaf)
    root=Group('root','Cluster',(2048,2048,128),8000)
    main=Group('Main','Layer',(2048,2048,128),8000,children=brushes)
    veg=Group('vegetation','Vegetation',(2048,2048,height(2048,2048) if height else 128),8000)
    root.children=[main,veg]
    for outer,quarters in sorted(vegetation.items()):
        region=Group('vegetation_'+'_'.join(map(str,outer)),'Vegetation',
                     ((outer[0]+.5)*cell_size*16,(outer[1]+.5)*cell_size*16,128),cell_size*16/math.sqrt(2))
        if height is not None:
            region.center = (*region.center[:2], height(*region.center[:2]))
        for quarter,items in sorted(quarters.items()):
            center=((quarter[0]+.5)*cell_size*4,(quarter[1]+.5)*cell_size*4,128)
            if height is not None:
                center = (*center[:2], height(*center[:2]))
            region.children.append(Group('vegetation_cell_'+'_'.join(map(str,quarter)),
                                         'Vegetation',center,cell_size*4/math.sqrt(2),children=items))
        veg.children.append(region)
    return root


def serialize(root):
    data=bytearray(struct.pack('<I',2));names=set();proxy_count=0
    def visit(group,parent=None,index=-1):
        nonlocal proxy_count
        if group.name in names:raise ValueError('Duplicate HLOD identity')
        names.add(group.name)
        own=list(group.records);child_indices=[]
        for child in group.children:
            child_indices.append(len(own) if child.proxy is not None else -1)
            if child.proxy is not None:
                if len(child.proxy)!=104 or struct.unpack_from('<I',child.proxy)[0]!=1:
                    raise ValueError('Proxy must be a native brush record')
                own.append(child.proxy);proxy_count+=1
        payload=b''.join(own);records(payload)
        offset=len(data);data.extend(struct.pack('<I',len(payload))+payload)
        node=ET.Element('HLod',DataOffset=str(offset),DataSize=str(len(payload)+4),
                        ProxyIndex=str(index),Type=group.kind,Pos=','.join(format(v,'.9g') for v in group.center),
                        Radius=format(group.radius,'.9g'),NearestObserverDistance='0',Name=group.name)
        if parent is not None:parent.append(node)
        for child,i in zip(group.children,child_indices):visit(child,node,i)
        return node
    document=visit(root)
    document.set('Hash',str(zlib.crc32(bytes(data))))
    return document,bytes(data),{'groups':len(names),'proxies':proxy_count}


def record_bounds(record):
    box=struct.unpack_from('<6f',record,4)
    if not all(map(math.isfinite,box)) or any(box[a]>box[a+3] for a in range(3)):
        raise ValueError('Invalid render-node bounds')
    center=tuple((box[a]+box[a+3])/2 for a in range(3))
    return center,math.dist(box[:3],box[3:])/2
