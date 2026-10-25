"""Exact normal-segment tests with a conservative spatial broad phase."""
from collections import defaultdict
from itertools import product
import numpy as np
from clothing_coverage import covered_points


class Surface:
    def __init__(self, triangles, accept=None, cell=.2):
        self.triangles=np.asarray(triangles,float);self.accept=accept;self.cell=cell
        self.cells=defaultdict(list)
        if not len(self.triangles):return
        lo=np.floor(self.triangles.min(axis=1)/cell).astype(int)
        hi=np.floor(self.triangles.max(axis=1)/cell).astype(int)
        for i,(a,b) in enumerate(zip(lo,hi)):
            if np.prod(b-a+1)>10000:raise ValueError('Unbounded clothing triangle')
            for k in product(*(range(x,y+1) for x,y in zip(a,b))):self.cells[k].append(i)

    def covers(self,points,directions,inward=.06,outward=.12):
        points,directions=np.asarray(points,float),np.asarray(directions,float)
        ends=np.stack((points-directions*inward,points+directions*outward))
        # Include numerical boundary tolerance from covered_points.
        low=np.floor((ends.min(axis=0)-1e-6)/self.cell).astype(int)
        high=np.floor((ends.max(axis=0)+1e-6)/self.cell).astype(int)
        batches=defaultdict(list)
        for i,(a,b) in enumerate(zip(low,high)):batches[(*a,*b)].append(i)
        answer=np.zeros(len(points),bool)
        for extent,indices in batches.items():
            cells=product(*(range(a,b+1) for a,b in zip(extent[:3],extent[3:])))
            candidates=sorted({i for k in cells for i in self.cells.get(k,())})
            if not candidates:continue
            candidates=np.asarray(candidates);indices=np.asarray(indices)
            accept=(lambda t,u,v:self.accept(candidates[t],u,v)) if self.accept is not None else None
            answer[indices]=covered_points(points[indices],directions[indices],self.triangles[candidates],
                                           inward=inward,outward=outward,accept_hit=accept)
        return answer
