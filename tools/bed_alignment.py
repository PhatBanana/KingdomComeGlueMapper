"""Align native bed interactions to source furniture using authored helpers."""
import math
import xml.etree.ElementTree as ET
from cooking_pots import rotate
from entity_visuals import quaternion_product as qmul


def alignment(source_xml, native_xml, source_family='Bed', native_family='Bed_1Place_High'):
    source=ET.fromstring(source_xml)
    native=ET.fromstring(native_xml)
    transforms=[]
    for name in ('sittingLeft','sittingRight'):
        def helper(root,family):
            matches=[e for e in root.iter('Helper') if e.get('className')==family and e.get('name')==name]
            if len(matches)!=1:raise ValueError('Missing or ambiguous bed helper: '+family+'/'+name)
            e=matches[0]
            p=tuple(map(float,e.get('pos').split(',')))
            q=tuple(map(float,e.get('rot').split(',')))
            length=math.sqrt(sum(x*x for x in q))
            return p,tuple(x/length for x in q)
        sp,sq=helper(source,source_family);np,nq=helper(native,native_family)
        correction=qmul(sq,(nq[0],-nq[1],-nq[2],-nq[3]))
        rotated=rotate(correction,np)
        transforms.append((tuple(sp[i]-rotated[i] for i in range(3)),correction))
    offset,rotation=transforms[0]
    other_offset,other_rotation=transforms[1]
    if max(abs(a-b) for a,b in zip(offset,other_offset))>0.001 or abs(sum(a*b for a,b in zip(rotation,other_rotation)))<0.99999:
        raise ValueError('Bed helpers do not share one rigid alignment')
    return offset,rotation
