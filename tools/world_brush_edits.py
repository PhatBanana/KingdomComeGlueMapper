"""Bounded static-furniture edits, preserving every unrelated HLOD record."""
import math
import struct
import xml.etree.ElementTree as E
from upgrade_map import xml
from vegetation import verify_target_hlods


def edit(data, metadata, edits):
    """Match position and bounds, translate or remove, then rebuild block offsets.

    Each edit has an authored position/bbox and optional translation delta.
    A missing delta removes the record. No record scanning or hidden flags.
    """
    verify_target_hlods(data)
    root = E.fromstring(metadata)
    nodes = {int(e.get('DataOffset')): e for e in root.iter('HLod')}
    output = bytearray(data[:4]); cursor = 4; counts = [0]*len(edits)
    while cursor < len(data):
        start = cursor; end = start+4+struct.unpack_from('<I', data, start)[0]
        node = nodes.pop(start, None)
        if node is None or int(node.get('DataSize')) != end-start:
            raise ValueError('HLOD block metadata mismatch')
        block = bytearray(); cursor += 4
        while cursor < end:
            kind = struct.unpack_from('<I', data, cursor)[0]
            size = {1:104, 2:64}[kind]; record = bytearray(data[cursor:cursor+size])
            if kind == 1:
                matrix = list(struct.unpack_from('<12f', record, 44))
                pos = tuple(matrix[i] for i in (3,7,11))
                bounds = list(struct.unpack_from('<6f', record, 4))
                matches = [i for i,e in enumerate(edits) if math.dist(pos,e['position']) < .002
                           and max(abs(a-b) for a,b in zip(bounds,e['bbox'])) < .002
                           and ('target_mesh' not in e or e['target_mesh'] == struct.unpack_from('<H',record,40)[0])]
                if len(matches)>1: raise ValueError('Ambiguous brush edit')
                if matches:
                    i=matches[0]; counts[i]+=1; delta=edits[i].get('delta')
                    if delta is None: record=b''
                    else:
                        if len(delta)!=3 or not all(map(math.isfinite,delta)):
                            raise ValueError('Invalid brush translation')
                        # Keep the brush in its existing spatial cluster.
                        center=tuple(map(float,node.get('Pos').split(',')))
                        for j in range(6): bounds[j]+=delta[j%3]
                        if any(math.dist(tuple(bounds[j+3*b[j]] for j in range(3)),center) > float(node.get('Radius'))
                               for b in ((x,y,z) for x in (0,1) for y in (0,1) for z in (0,1))):
                            raise ValueError('Moved brush exceeds its HLOD cluster')
                        for j,index in enumerate((3,7,11)): matrix[index]+=delta[j]
                        struct.pack_into('<12f',record,44,*matrix)
                        struct.pack_into('<6f',record,4,*bounds)
            block.extend(record); cursor+=size
        node.set('DataOffset',str(len(output))); node.set('DataSize',str(len(block)+4))
        output.extend(struct.pack('<I',len(block))); output.extend(block)
    if nodes or counts != [1]*len(edits):
        raise ValueError('Missing or duplicate furniture placements: '+str(counts))
    verify_target_hlods(output)
    return bytes(output),xml(root)
