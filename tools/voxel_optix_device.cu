#include "voxel_optix_shared.h"
#include <optix_device.h>
extern "C" { __constant__ QueryParams params; }
// Keep constant/global loads explicit: selecting a pointer across these address
// spaces produced incorrect generic loads in the tested OptiX module compiler.
static __forceinline__ __device__ double brick_coordinate(int k){return params.bricks?params.bricks[optixGetLaunchIndex().y*4+k]:params.origin[k];}
static __forceinline__ __device__ double brick_cell(){return params.bricks?params.bricks[optixGetLaunchIndex().y*4+3]:params.cell;}
static __forceinline__ __device__ void ray_coordinates(int& axis,int& u,int& v,int& iu,int& iv){
    int r=optixGetLaunchIndex().x,s=params.samples;
    int n0=params.sy*params.sz*s*s,n1=params.sx*params.sz*s*s;
    axis=r<n0?0:(r<n0+n1?1:2);if(axis==1)r-=n0;else if(axis==2)r-=n0+n1;
    u=axis==0?1:0;v=axis==2?1:2;int width=(axis==0?params.sy:params.sx)*s;
    iu=r%width;iv=r/width;
}
extern "C" __global__ void __raygen__query(){
    int axis,u,v,iu,iv;ray_coordinates(axis,u,v,iu,iv);
    double o[3]={brick_coordinate(0),brick_coordinate(1),brick_coordinate(2)};double cell=brick_cell();double p[3]={o[0],o[1],o[2]};
    p[u]+=(iu+.5)/params.samples*cell;p[v]+=(iv+.5)/params.samples*cell;
    int shape[3]={params.sx,params.sy,params.sz};p[axis]-=.01;
    float3 origin=make_float3((float)p[0],(float)p[1],(float)p[2]);float3 direction=make_float3(axis==0,axis==1,axis==2);
    optixTrace(params.gas,origin,direction,0.f,(float)(shape[axis]*cell+.02),0.f,255,OPTIX_RAY_FLAG_NONE,0,1,0);
}
extern "C" __global__ void __miss__query(){}
static __forceinline__ __device__ void record_exact_hit(){
    int batch=optixGetLaunchIndex().y;
    int rays=(params.sx*params.sy+params.sx*params.sz+params.sy*params.sz)*params.samples*params.samples;
    int ray=optixGetLaunchIndex().x+batch*rays,ti=optixGetPrimitiveIndex(),axis,u,v,iu,iv;ray_coordinates(axis,u,v,iu,iv);
    double o[3]={brick_coordinate(0),brick_coordinate(1),brick_coordinate(2)};double cell=brick_cell();
    const double* t=params.triangles+ti*9;double a[3],b[3],c[3];
    for(int k=0;k<3;++k){a[k]=(t[k]-o[k])/cell;b[k]=(t[k+3]-o[k])/cell;c[k]=(t[k+6]-o[k])/cell;}
    double det=(b[u]-a[u])*(c[v]-a[v])-(c[u]-a[u])*(b[v]-a[v]);if(fabs(det)<1e-12)return;
    double du=(iu+.5)/params.samples-a[u],dv=(iv+.5)/params.samples-a[v];
    double beta=(du*(c[v]-a[v])-dv*(c[u]-a[u]))/det,gamma=((b[u]-a[u])*dv-(b[v]-a[v])*du)/det;
    double depth=a[axis]+beta*(b[axis]-a[axis])+gamma*(c[axis]-a[axis]);int shape[3]={params.sx,params.sy,params.sz};
    if(beta < -1e-10 || gamma < -1e-10 || beta+gamma > 1+1e-10 || depth<0 || depth>=shape[axis])return;
    int xyz[3];xyz[u]=iu/params.samples;xyz[v]=iv/params.samples;xyz[axis]=(int)floor(depth);
    int voxel=batch*params.sx*params.sy*params.sz+(xyz[2]*params.sy+xyz[1])*params.sx+xyz[0];int64_t at=params.counts[ray]++;
    if(params.fill)params.keys[params.offsets[ray]+at]=(uint64_t)voxel*params.nt+ti;
    // RT hardware traverses one persistent scene BVH. Exact double intersection
    // arithmetic preserves the accepted reference, including coincident faces.
}
extern "C" __global__ void __intersection__query(){record_exact_hit();}
// Experimental built-in triangles still use the reference predicate and sorted
// accumulation. Hardware candidate rejection itself can differ at boundaries.
extern "C" __global__ void __anyhit__query(){record_exact_hit();optixIgnoreIntersection();}
