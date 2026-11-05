// Read-only harness around the pinned core's unmodified GridMap loader.
#include "GridMap.h"
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <cstdlib>

int main(int argc, char** argv)
{
    if (argc != 5) return 2;
    int gx=std::atoi(argv[3]),gy=std::atoi(argv[4]);
    if(gx<0||gx>=64||gy<0||gy>=64) return 2;
    GridMap original,converted;
    auto old=original.loadData(argv[1]),now=converted.loadData(argv[2]);
    bool originalRejected=old==GridMap::LoadResult::InvalidFile;
    bool accepted=now==GridMap::LoadResult::Ok;
    unsigned valid=0;double minimum=std::numeric_limits<double>::infinity(),maximum=-minimum;
    if(accepted)
        for(int ix=0;ix<11;++ix) for(int iy=0;iy<11;++iy)
        {
            float x=(32.0f-gx-(0.05f+0.09f*ix))*533.33333f;
            float y=(32.0f-gy-(0.05f+0.09f*iy))*533.33333f;
            float z=converted.getHeight(x,y);
            if(std::isfinite(z)&&z>-100000.0f&&z<100000.0f)
            { ++valid;minimum=std::min(minimum,double(z));maximum=std::max(maximum,double(z)); }
        }
    std::cout<<std::boolalpha<<"{\"original_v9_rejected\":"<<originalRejected
        <<",\"candidate_loaded\":"<<accepted<<",\"height_samples\":121,\"valid_heights\":"<<valid;
    if(valid) std::cout<<",\"minimum_height\":"<<std::setprecision(10)<<minimum<<",\"maximum_height\":"<<maximum;
    std::cout<<",\"client_or_vmap_validated\":false}\n";
    return originalRejected&&accepted&&valid==121?0:1;
}
