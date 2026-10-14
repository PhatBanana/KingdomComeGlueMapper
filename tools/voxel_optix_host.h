#pragma once
#include "voxel_optix_shared.h"
#include <optix_function_table_definition.h>
#include <optix_stubs.h>
#include <optix_stack_size.h>
#include <fstream>
#include <iterator>
inline void oxcheck(OptixResult r){if(r!=OPTIX_SUCCESS)throw std::runtime_error(std::string("OptiX: ")+optixGetErrorName(r));}
__global__ void make_vertices(const double* tris,int count,float3* vertices){
    int n=blockIdx.x*blockDim.x+threadIdx.x;if(n<count)vertices[n]=make_float3((float)tris[n*3],(float)tris[n*3+1],(float)tris[n*3+2]);
}
__global__ void make_boxes(const double* tris,int nt,OptixAabb* boxes){
    int ti=blockIdx.x*blockDim.x+threadIdx.x;if(ti>=nt)return;
    float lo[3],hi[3];
    for(int k=0;k<3;++k){double a=tris[ti*9+k],b=tris[ti*9+3+k],c=tris[ti*9+6+k];
        double mn=fmin(a,fmin(b,c)),mx=fmax(a,fmax(b,c));
        double pad=.002+fmax(fabs(mn),fabs(mx))*3e-7;
        lo[k]=(float)(mn-pad);hi[k]=(float)(mx+pad);
    }
    boxes[ti]={lo[0],lo[1],lo[2],hi[0],hi[1],hi[2]};
}
struct OptixQuery {
    bool hardware_triangles=false;
    OptixDeviceContext context=nullptr;
    OptixModule module=nullptr;
    OptixProgramGroup rg=nullptr,ms=nullptr,hg=nullptr;
    OptixPipeline pipeline=nullptr;
    Buffer sbt_buffer;
    Buffer scene_gas;
    OptixTraversableHandle scene_handle=0;
    OptixShaderBindingTable sbt={};
    ~OptixQuery(){if(pipeline)optixPipelineDestroy(pipeline);for(auto g:{rg,ms,hg})if(g)optixProgramGroupDestroy(g);if(module)optixModuleDestroy(module);if(context)optixDeviceContextDestroy(context);}
    void init(){
        const char* mode=std::getenv("GLUEMAPPER_OPTIX_TRIANGLES");hardware_triangles=mode && std::string(mode)=="1";
        check(cudaFree(0));oxcheck(optixInit());OptixDeviceContextOptions options={};oxcheck(optixDeviceContextCreate(nullptr,&options,&context));
        const char* env=std::getenv("GLUEMAPPER_OPTIX_PTX");std::ifstream file(env?env:"outputs/cuda/voxel_optix.ptx");
        if(!file)throw std::runtime_error("OptiX PTX missing; run build_voxel_cuda.ps1 -Optix");
        std::string ptx((std::istreambuf_iterator<char>(file)),{});
        OptixModuleCompileOptions mc={};mc.optLevel=OPTIX_COMPILE_OPTIMIZATION_DEFAULT;mc.debugLevel=OPTIX_COMPILE_DEBUG_LEVEL_NONE;
        OptixPipelineCompileOptions pc={};pc.traversableGraphFlags=OPTIX_TRAVERSABLE_GRAPH_FLAG_ALLOW_SINGLE_GAS;pc.numAttributeValues=2;
        pc.pipelineLaunchParamsVariableName="params";pc.usesPrimitiveTypeFlags=hardware_triangles?OPTIX_PRIMITIVE_TYPE_FLAGS_TRIANGLE:OPTIX_PRIMITIVE_TYPE_FLAGS_CUSTOM;
        char log[8192];size_t length=sizeof(log);auto result=optixModuleCreate(context,&mc,&pc,ptx.data(),ptx.size(),log,&length,&module);
        if(result!=OPTIX_SUCCESS)throw std::runtime_error(std::string(log,length));
        OptixProgramGroupOptions pgopt={};OptixProgramGroupDesc desc={};desc.kind=OPTIX_PROGRAM_GROUP_KIND_RAYGEN;desc.raygen.module=module;desc.raygen.entryFunctionName="__raygen__query";
        oxcheck(optixProgramGroupCreate(context,&desc,1,&pgopt,nullptr,nullptr,&rg));
        desc={};desc.kind=OPTIX_PROGRAM_GROUP_KIND_MISS;desc.miss.module=module;desc.miss.entryFunctionName="__miss__query";oxcheck(optixProgramGroupCreate(context,&desc,1,&pgopt,nullptr,nullptr,&ms));
        desc={};desc.kind=OPTIX_PROGRAM_GROUP_KIND_HITGROUP;
        if(hardware_triangles){desc.hitgroup.moduleAH=module;desc.hitgroup.entryFunctionNameAH="__anyhit__query";}
        else {desc.hitgroup.moduleIS=module;desc.hitgroup.entryFunctionNameIS="__intersection__query";}
        oxcheck(optixProgramGroupCreate(context,&desc,1,&pgopt,nullptr,nullptr,&hg));
        OptixProgramGroup groups[]={rg,ms,hg};OptixPipelineLinkOptions link={};link.maxTraceDepth=1;
        oxcheck(optixPipelineCreate(context,&pc,&link,groups,3,nullptr,nullptr,&pipeline));
        OptixStackSizes stacks={};for(auto g:groups)oxcheck(optixUtilAccumulateStackSizes(g,&stacks,pipeline));
        unsigned dct,dcs,css;oxcheck(optixUtilComputeStackSizes(&stacks,1,0,0,&dct,&dcs,&css));oxcheck(optixPipelineSetStackSize(pipeline,dct,dcs,css,1));
        struct alignas(OPTIX_SBT_RECORD_ALIGNMENT) Record {char header[OPTIX_SBT_RECORD_HEADER_SIZE];};Record records[3];
        for(int n=0;n<3;++n)oxcheck(optixSbtRecordPackHeader(groups[n],&records[n]));sbt_buffer.upload(records,sizeof(records));
        sbt.raygenRecord=(CUdeviceptr)sbt_buffer.p;sbt.missRecordBase=sbt.raygenRecord+sizeof(Record);sbt.missRecordStrideInBytes=sizeof(Record);sbt.missRecordCount=1;
        sbt.hitgroupRecordBase=sbt.missRecordBase+sizeof(Record);sbt.hitgroupRecordStrideInBytes=sizeof(Record);sbt.hitgroupRecordCount=1;
    }
    void set_scene(const double* tris,int nt){
        Buffer boxes,temp;
        if(scene_gas.p){check(cudaFree(scene_gas.p));scene_gas.p=nullptr;}scene_handle=0;
        if(!nt)return;
        OptixBuildInput input={};unsigned flags=OPTIX_GEOMETRY_FLAG_NONE;CUdeviceptr boxptr=0;
        if(hardware_triangles){
            boxes.alloc((size_t)nt*3*sizeof(float3));make_vertices<<<(nt*3+255)/256,256>>>(tris,nt*3,(float3*)boxes.p);
            boxptr=(CUdeviceptr)boxes.p;flags=OPTIX_GEOMETRY_FLAG_REQUIRE_SINGLE_ANYHIT_CALL;
            input.type=OPTIX_BUILD_INPUT_TYPE_TRIANGLES;input.triangleArray.vertexBuffers=&boxptr;
            input.triangleArray.numVertices=nt*3;input.triangleArray.vertexFormat=OPTIX_VERTEX_FORMAT_FLOAT3;
            input.triangleArray.vertexStrideInBytes=sizeof(float3);input.triangleArray.flags=&flags;input.triangleArray.numSbtRecords=1;
        }else{
            boxes.alloc((size_t)nt*sizeof(OptixAabb));make_boxes<<<(nt+255)/256,256>>>(tris,nt,(OptixAabb*)boxes.p);
            boxptr=(CUdeviceptr)boxes.p;input.type=OPTIX_BUILD_INPUT_TYPE_CUSTOM_PRIMITIVES;input.customPrimitiveArray.aabbBuffers=&boxptr;input.customPrimitiveArray.numPrimitives=nt;input.customPrimitiveArray.flags=&flags;input.customPrimitiveArray.numSbtRecords=1;
        }
        check(cudaGetLastError());
        OptixAccelBuildOptions opts={};opts.buildFlags=OPTIX_BUILD_FLAG_PREFER_FAST_TRACE;opts.operation=OPTIX_BUILD_OPERATION_BUILD;
        OptixAccelBufferSizes sizes;oxcheck(optixAccelComputeMemoryUsage(context,&opts,&input,1,&sizes));temp.alloc(sizes.tempSizeInBytes);scene_gas.alloc(sizes.outputSizeInBytes);
        oxcheck(optixAccelBuild(context,0,&opts,&input,1,(CUdeviceptr)temp.p,sizes.tempSizeInBytes,(CUdeviceptr)scene_gas.p,sizes.outputSizeInBytes,&scene_handle,nullptr,0));check(cudaDeviceSynchronize());
    }
    void candidates(const double* tris,int nt,const double* origin,const int64_t* shape,double cell,int samples,Buffer& keys,int64_t& key_count,const double* bricks=nullptr,int batches=1){
        Buffer launch,counts,offsets;
        int count=(shape[0]*shape[1]+shape[0]*shape[2]+shape[1]*shape[2])*samples*samples;
        int rays=count;count*=batches;
        counts.alloc(((size_t)count+1)*sizeof(int64_t));offsets.alloc(((size_t)count+1)*sizeof(int64_t));check(cudaMemset(counts.p,0,((size_t)count+1)*sizeof(int64_t)));
        QueryParams p={scene_handle,(int)shape[0],(int)shape[1],(int)shape[2],nt,0,(int64_t*)counts.p,(int64_t*)offsets.p,nullptr,tris,{origin[0],origin[1],origin[2]},cell,samples,bricks};launch.upload(&p,sizeof(p));
        oxcheck(optixLaunch(pipeline,0,(CUdeviceptr)launch.p,sizeof(p),&sbt,rays,batches,1));
        auto c=thrust::device_pointer_cast((int64_t*)counts.p);auto off=thrust::device_pointer_cast((int64_t*)offsets.p);thrust::exclusive_scan(c,c+count+1,off);
        check(cudaMemcpy(&key_count,(int64_t*)offsets.p+count,sizeof(int64_t),cudaMemcpyDeviceToHost));
        size_t free,total;check(cudaMemGetInfo(&free,&total));if((uint64_t)key_count>free/(3*sizeof(uint64_t)))throw std::runtime_error("OptiX candidates exceed VRAM budget");
        keys.alloc((size_t)key_count*sizeof(uint64_t));p.fill=1;p.keys=(uint64_t*)keys.p;check(cudaMemset(counts.p,0,((size_t)count+1)*sizeof(int64_t)));check(cudaMemcpy(launch.p,&p,sizeof(p),cudaMemcpyHostToDevice));
        oxcheck(optixLaunch(pipeline,0,(CUdeviceptr)launch.p,sizeof(p),&sbt,rays,batches,1));auto key=thrust::device_pointer_cast((uint64_t*)keys.p);thrust::sort(key,key+key_count);check(cudaDeviceSynchronize());
    }
};
