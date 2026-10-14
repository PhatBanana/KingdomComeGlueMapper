// Deterministic surface voxelization: one thread owns one voxel. No unordered
// floating-point atomics; triangle and sample order follows the CPU reference.
#include <cuda_runtime.h>
#include <cmath>
#include <cstdint>
#include <new>
#include <vector>
#include <stdexcept>
#include <string>
#include <cstring>
#include <thrust/device_ptr.h>
#include <thrust/scan.h>
#include <thrust/sort.h>
#define API extern "C" __declspec(dllexport)
static thread_local std::string last_error;
static void check(cudaError_t e) { if(e != cudaSuccess) throw std::runtime_error(cudaGetErrorString(e)); }
struct Buffer {
    void* p=nullptr;
    ~Buffer(){if(p) cudaFree(p);}
    void alloc(size_t n){if(p){check(cudaFree(p));p=nullptr;}check(cudaMalloc(&p,n?n:1));}
    void upload(const void* src,size_t n){alloc(n);if(n)check(cudaMemcpy(p,src,n,cudaMemcpyHostToDevice));}
};

// Reusable stream/graph experiment. Graph covers raster + readback only;
// data-dependent OptiX candidate generation remains outside the graph.
struct Transfer {
    cudaStream_t stream=nullptr;void* pinned=nullptr;size_t capacity=0;
    cudaGraph_t graph=nullptr;cudaGraphExec_t executable=nullptr;
    cudaGraphNode_t kernel_node=nullptr,copy_node=nullptr;
    ~Transfer(){if(stream)cudaStreamSynchronize(stream);if(executable)cudaGraphExecDestroy(executable);if(graph)cudaGraphDestroy(graph);if(pinned)cudaFreeHost(pinned);if(stream)cudaStreamDestroy(stream);}
    void run(cudaKernelNodeParams& kernel,void* device,size_t bytes,void* destination,bool graphs){
        if(!stream)check(cudaStreamCreateWithFlags(&stream,cudaStreamNonBlocking));
        if(bytes>capacity){if(pinned){check(cudaFreeHost(pinned));pinned=nullptr;}capacity=0;check(cudaHostAlloc(&pinned,bytes,cudaHostAllocDefault));capacity=bytes;}
        if(graphs){
            if(!executable){
                check(cudaGraphCreate(&graph,0));check(cudaGraphAddKernelNode(&kernel_node,graph,nullptr,0,&kernel));
                check(cudaGraphAddMemcpyNode1D(&copy_node,graph,&kernel_node,1,pinned,device,bytes,cudaMemcpyDeviceToHost));
                check(cudaGraphInstantiate(&executable,graph,nullptr,nullptr,0));
            }else{
                check(cudaGraphExecKernelNodeSetParams(executable,kernel_node,&kernel));
                check(cudaGraphExecMemcpyNodeSetParams1D(executable,copy_node,pinned,device,bytes,cudaMemcpyDeviceToHost));
            }
            check(cudaGraphLaunch(executable,stream));
        }else{
            check(cudaLaunchKernel(kernel.func,kernel.gridDim,kernel.blockDim,kernel.kernelParams,kernel.sharedMemBytes,stream));
            check(cudaMemcpyAsync(pinned,device,bytes,cudaMemcpyDeviceToHost,stream));
        }
        check(cudaStreamSynchronize(stream));std::memcpy(destination,pinned,bytes);
    }
};
#ifdef WITH_OPTIX
#include "voxel_optix_host.h"
#endif
struct Context { Transfer transfer;Buffer tex,sizes,starts,params,scene_t,scene_u,scene_i;int scene_nt=0;bool float_tex=false;
#ifdef WITH_OPTIX
    OptixQuery optix;
#endif
};
API const char* vr_error(){return last_error.c_str();}
API void* vr_create(const void* tex,int64_t pixels,const int64_t* sizes,
                    const int64_t* starts,const double* params,int materials,int float_tex){
    Context* c=nullptr;
    try { c=new Context;c->float_tex=float_tex!=0;c->tex.upload(tex,pixels*4*(float_tex?sizeof(float):sizeof(double)));
        c->sizes.upload(sizes,materials*2*sizeof(int64_t));
        c->starts.upload(starts,materials*sizeof(int64_t));
        c->params.upload(params,materials*12*sizeof(double));
#ifdef WITH_OPTIX
        c->optix.init();
#endif
        return c;
    } catch(const std::exception& e){last_error=e.what();delete c;return nullptr;}
}
API void vr_destroy(void* c){delete static_cast<Context*>(c);}
API int vr_scene_upload(void* ctx,const double* tris,const double* uv,const int64_t* ids,int nt){
    try{
        auto c=static_cast<Context*>(ctx);c->scene_t.upload(tris,(size_t)nt*9*sizeof(double));c->scene_u.upload(uv,(size_t)nt*6*sizeof(double));c->scene_i.upload(ids,(size_t)nt*sizeof(int64_t));c->scene_nt=nt;
#ifdef WITH_OPTIX
        c->optix.set_scene((double*)c->scene_t.p,nt);
#endif
        return 0;
    }catch(const std::exception& e){last_error=e.what();return 1;}
}
__device__ int address(int x,int n,bool repeat){return repeat?((x%n+n)%n):min(max(x,0),n-1);}
__device__ void bounds(const double* t,const double* o,double cell,const int* shape,int* lo,int* hi){
    for(int k=0;k<3;++k){
        double a=(t[k]-o[k])/cell,b=(t[k+3]-o[k])/cell,c=(t[k+6]-o[k])/cell;
        lo[k]=max(0,(int)floor(fmin(a,fmin(b,c))));hi[k]=min(shape[k]-1,(int)floor(fmax(a,fmax(b,c))));
    }
}
__global__ void count_bins(const double* tris,int nt,double ox,double oy,double oz,double cell,int sx,int sy,int sz,int64_t* counts){
    int ti=blockIdx.x*blockDim.x+threadIdx.x;if(ti>nt)return;
    if(ti==nt){counts[ti]=0;return;}
    double o[3]={ox,oy,oz};int shape[3]={sx,sy,sz},lo[3],hi[3];bounds(tris+ti*9,o,cell,shape,lo,hi);
    counts[ti]=(int64_t)max(0,hi[0]-lo[0]+1)*max(0,hi[1]-lo[1]+1)*max(0,hi[2]-lo[2]+1);
}
__global__ void fill_bins(const double* tris,int nt,double ox,double oy,double oz,double cell,int sx,int sy,int sz,const int64_t* offsets,uint64_t* keys){
    int ti=blockIdx.x*blockDim.x+threadIdx.x;if(ti>=nt)return;
    double o[3]={ox,oy,oz};int shape[3]={sx,sy,sz},lo[3],hi[3];bounds(tris+ti*9,o,cell,shape,lo,hi);
    int64_t at=offsets[ti];
    for(int z=lo[2];z<=hi[2];++z)for(int y=lo[1];y<=hi[1];++y)for(int x=lo[0];x<=hi[0];++x)
        keys[at++]=(uint64_t)((z*sy+y)*sx+x)*nt+ti;
}
__device__ int64_t lower_key(const uint64_t* keys,int64_t n,uint64_t target){
    int64_t lo=0,hi=n;while(lo<hi){int64_t mid=lo+(hi-lo)/2;if(keys[mid]<target)lo=mid+1;else hi=mid;}return lo;
}
template<int Samples>
__global__ void raster(const double* tris,const double* uv,const int64_t* ids,int nt,
 const void* tex,bool float_tex,const int64_t* sizes,const int64_t* starts,const double* params,
 double ox,double oy,double oz,int sx,int sy,int sz,double cell,int samples,double* out,const uint64_t* keys,int64_t key_count,const double* bricks){
    int local=blockIdx.x*blockDim.x+threadIdx.x;
    if(local>=sx*sy*sz)return;
    int flat=local+blockIdx.y*sx*sy*sz;
    if(bricks){ox=bricks[blockIdx.y*4];oy=bricks[blockIdx.y*4+1];oz=bricks[blockIdx.y*4+2];cell=bricks[blockIdx.y*4+3];}
    int xyz[3]={local%sx,(local/sx)%sy,local/(sx*sy)};
    double origin[3]={ox,oy,oz}, colour[3]={}, normal[3]={}, weight=0;
    int64_t begin=keys?lower_key(keys,key_count,(uint64_t)flat*nt):0;
    int64_t end=keys?lower_key(keys,key_count,(uint64_t)(flat+1)*nt):nt;
    samples=Samples;
    for(int axis=0;axis<3;++axis){
        int u=axis==0?1:0,v=axis==2?1:2;
        float rays[Samples*Samples]={};
        for(int64_t candidate=begin;candidate<end;++candidate){
            int ti=keys?(int)(keys[candidate]%nt):(int)candidate;
            if(keys && candidate>begin && keys[candidate]==keys[candidate-1])continue;
            int mi=ids[ti];const double* p=params+mi*12;
            if(p[3]==0 || p[5]==0)continue;
            const double* t=tris+ti*9; double a[3],b[3],c[3];
            bool outside=false;
            for(int k=0;k<3;++k){
                a[k]=(t[k]-origin[k])/cell;b[k]=(t[3+k]-origin[k])/cell;c[k]=(t[6+k]-origin[k])/cell;
                if(fmax(a[k],fmax(b[k],c[k]))<xyz[k] || fmin(a[k],fmin(b[k],c[k]))>=xyz[k]+1)outside=true;
            }
            if(outside)continue;
            double det=(b[u]-a[u])*(c[v]-a[v])-(c[u]-a[u])*(b[v]-a[v]);
            if(fabs(det)<1e-12)continue;
            int lu=max(xyz[u]*samples,(int)ceil(fmin(a[u],fmin(b[u],c[u]))*samples-.5));
            int lv=max(xyz[v]*samples,(int)ceil(fmin(a[v],fmin(b[v],c[v]))*samples-.5));
            int hu=min((xyz[u]+1)*samples-1,(int)floor(fmax(a[u],fmax(b[u],c[u]))*samples-.5));
            int hv=min((xyz[v]+1)*samples-1,(int)floor(fmax(a[v],fmax(b[v],c[v]))*samples-.5));
            if(lu>hu || lv>hv)continue;
            double e[3],f[3],n[3];for(int k=0;k<3;++k){e[k]=t[3+k]-t[k];f[k]=t[6+k]-t[k];}
            n[0]=e[1]*f[2]-e[2]*f[1];n[1]=e[2]*f[0]-e[0]*f[2];n[2]=e[0]*f[1]-e[1]*f[0];
            double length=fmax(sqrt(n[0]*n[0]+n[1]*n[1]+n[2]*n[2]),1e-30);
            for(int k=0;k<3;++k)n[k]/=length;
            int h=sizes[mi*2],w=sizes[mi*2+1];
            for(int iv=lv;iv<=hv;++iv)for(int iu=lu;iu<=hu;++iu){
                double du=(iu+.5)/samples-a[u],dv=(iv+.5)/samples-a[v];
                double beta=(du*(c[v]-a[v])-dv*(c[u]-a[u]))/det;
                double gamma=((b[u]-a[u])*dv-(b[v]-a[v])*du)/det;
                double depth=a[axis]+beta*(b[axis]-a[axis])+gamma*(c[axis]-a[axis]);
                if(beta < -1e-10 || gamma < -1e-10 || beta+gamma > 1+1e-10 || depth<xyz[axis] || depth>=xyz[axis]+1)continue;
                const double* q=uv+ti*6;
                double s=(q[0]+beta*(q[2]-q[0])+gamma*(q[4]-q[0]))*p[6]+p[8];
                double tt=(q[1]+beta*(q[3]-q[1])+gamma*(q[5]-q[1]))*p[7]+p[9];
                double qx=s*w-.5,qy=tt*h-.5;int lx=(int)floor(qx),ly=(int)floor(qy);
                double fx=qx-lx,fy=qy-ly,rgba[4]={};
                for(int dy=0;dy<2;++dy)for(int dx=0;dx<2;++dx){
                    double ww=(dx?fx:1-fx)*(dy?fy:1-fy);
                    int ix=address(lx+dx,w,p[10]!=0),iy=address(ly+dy,h,p[11]!=0);
                    int64_t pixel=(starts[mi]+(int64_t)iy*w+ix)*4;
                    for(int k=0;k<4;++k)rgba[k]+=(float_tex?(double)((const float*)tex)[pixel+k]:((const double*)tex)[pixel+k])*ww;
                }
                double alpha=rgba[3]>=p[4]?rgba[3]*p[3]*p[5]:0;
                int ray=iu%samples+samples*(iv%samples);
                double gain=fmax(0.,alpha-rays[ray]);rays[ray]=(float)(rays[ray]+gain);weight+=gain;
                for(int k=0;k<3;++k){colour[k]+=rgba[k]*p[k]*gain;normal[k]+=n[k]*gain;}
            }
        }
        // Numba's float32 mean sums in float32, then divides.
        float sum=0;for(int r=0;r<samples*samples;++r)sum+=rays[r];
        out[flat*9+axis]=(double)sum/(samples*samples);
    }
    for(int k=0;k<3;++k){out[flat*9+3+k]=colour[k]/fmax(weight,1e-30);out[flat*9+6+k]=normal[k]/fmax(weight,1e-30);}
}
API int vr_raster(void* ctx,const double* tris,const double* uv,const int64_t* ids,int nt,
 const double* origin,const int64_t* shape,double cell,int samples,double* output){
    try {
        if(samples<1 || samples>8)throw std::runtime_error("CUDA samples must be 1..8");
        auto c=static_cast<Context*>(ctx);Buffer t,u,i,o,offsets,keys;int64_t key_count=0;
        if(tris){t.upload(tris,(size_t)nt*9*sizeof(double));u.upload(uv,(size_t)nt*6*sizeof(double));i.upload(ids,(size_t)nt*sizeof(int64_t));}
        else nt=c->scene_nt;
        double* dt=(double*)(tris?t.p:c->scene_t.p);double* du=(double*)(tris?u.p:c->scene_u.p);int64_t* di=(int64_t*)(tris?i.p:c->scene_i.p);
        int count=shape[0]*shape[1]*shape[2];o.alloc((size_t)count*9*sizeof(double));
        if(nt>128){
#ifdef WITH_OPTIX
            if(tris)c->optix.set_scene(dt,nt);
            c->optix.candidates(dt,nt,origin,shape,cell,samples,keys,key_count);
#else
            offsets.alloc(((size_t)nt+1)*sizeof(int64_t));
            count_bins<<<(nt+256)/256,256>>>(dt,nt,origin[0],origin[1],origin[2],cell,shape[0],shape[1],shape[2],(int64_t*)offsets.p);
            check(cudaGetLastError());
            auto off=thrust::device_pointer_cast((int64_t*)offsets.p);thrust::exclusive_scan(off,off+nt+1,off);
            check(cudaMemcpy(&key_count,(int64_t*)offsets.p+nt,sizeof(int64_t),cudaMemcpyDeviceToHost));
            size_t free_bytes,total_bytes;check(cudaMemGetInfo(&free_bytes,&total_bytes));
            if((uint64_t)key_count>free_bytes/(3*sizeof(uint64_t)))throw std::runtime_error("CUDA spatial bins exceed available VRAM; use compiled backend");
            keys.alloc((size_t)key_count*sizeof(uint64_t));
            fill_bins<<<(nt+255)/256,256>>>(dt,nt,origin[0],origin[1],origin[2],cell,shape[0],shape[1],shape[2],(int64_t*)offsets.p,(uint64_t*)keys.p);
            check(cudaGetLastError());auto key=thrust::device_pointer_cast((uint64_t*)keys.p);thrust::sort(key,key+key_count);
#endif
        }
#define LAUNCH_RASTER(S) raster<S><<<(count+127)/128,128>>>(dt,du,di,nt, \
          c->tex.p,c->float_tex,(int64_t*)c->sizes.p,(int64_t*)c->starts.p,(double*)c->params.p, \
          origin[0],origin[1],origin[2],shape[0],shape[1],shape[2],cell,samples,(double*)o.p,(uint64_t*)keys.p,key_count,nullptr)
        switch(samples){case 1:LAUNCH_RASTER(1);break;case 2:LAUNCH_RASTER(2);break;case 4:LAUNCH_RASTER(4);break;case 8:LAUNCH_RASTER(8);break;default:throw std::runtime_error("Invalid samples");}
#undef LAUNCH_RASTER
        check(cudaGetLastError());check(cudaMemcpy(output,o.p,(size_t)count*9*sizeof(double),cudaMemcpyDeviceToHost));return 0;
    }catch(const std::exception& e){last_error=e.what();return 1;}
}

// One launch grid covers a bounded batch of independent 16^3 bricks.
API int vr_batch(void* ctx,const double* bricks,int batches,int samples,double* output){
    try{
#ifndef WITH_OPTIX
        throw std::runtime_error("Batched scene raster requires OptiX");
#else
        if(batches<1 || batches>64)throw std::runtime_error("Batch count must be 1..64");
        auto c=static_cast<Context*>(ctx);int nt=c->scene_nt;
        Buffer positions,keys,o;positions.upload(bricks,(size_t)batches*4*sizeof(double));
        int64_t shape[3]={16,16,16};int64_t key_count=0;
        if(nt>128)c->optix.candidates((double*)c->scene_t.p,nt,bricks,shape,bricks[3],samples,keys,key_count,(double*)positions.p,batches);
        o.alloc((size_t)batches*4096*9*sizeof(double));

        dim3 grid(32,batches);
        auto dt=(double*)c->scene_t.p;auto du=(double*)c->scene_u.p;auto di=(int64_t*)c->scene_i.p;
        auto sizes=(int64_t*)c->sizes.p;auto starts=(int64_t*)c->starts.p;auto params=(double*)c->params.p;
        auto out=(double*)o.p;auto key=(uint64_t*)keys.p;auto pos=(double*)positions.p;
        double zero=0,one=1;int side=16;
        void* args[]={&dt,&du,&di,&nt,&c->tex.p,&c->float_tex,&sizes,&starts,&params,&zero,&zero,&zero,&side,&side,&side,&one,&samples,&out,&key,&key_count,&pos};
        cudaKernelNodeParams kernel={};kernel.gridDim=grid;kernel.blockDim=dim3(128);kernel.kernelParams=args;
        switch(samples){case 1:kernel.func=(void*)raster<1>;break;case 2:kernel.func=(void*)raster<2>;break;case 4:kernel.func=(void*)raster<4>;break;case 8:kernel.func=(void*)raster<8>;break;default:throw std::runtime_error("Invalid samples");}
        const char* graph_env=std::getenv("GLUEMAPPER_GPU_GRAPHS");bool graphs=graph_env && std::string(graph_env)=="1";
        const char* async_env=std::getenv("GLUEMAPPER_GPU_ASYNC");bool async=async_env && std::string(async_env)=="1";
        size_t bytes=(size_t)batches*4096*9*sizeof(double);
        if(graphs || async)c->transfer.run(kernel,o.p,bytes,output,graphs);
        else {
            check(cudaLaunchKernel(kernel.func,kernel.gridDim,kernel.blockDim,args,0,0));
            check(cudaGetLastError());check(cudaMemcpy(output,o.p,bytes,cudaMemcpyDeviceToHost));
        }
        return 0;
#endif
    }catch(const std::exception& e){last_error=e.what();cudaGetLastError();return 1;}
}
