#pragma once
#include <optix.h>
#include <cuda_runtime.h>
#include <cstdint>
struct QueryParams {
    OptixTraversableHandle gas;
    int sx,sy,sz,nt,fill;
    int64_t* counts;
    const int64_t* offsets;
    uint64_t* keys;
    const double* triangles;
    double origin[3];
    double cell;
    int samples;
    const double* bricks; // Optional packed x,y,z,cell records for launch.y.
};
