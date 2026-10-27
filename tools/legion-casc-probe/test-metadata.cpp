// Controlled CASC I/O stubs exercise bounds and errors; this is not a real-client test.
#define main ProbeMain
#include "probe.cpp"
#undef main
#include <cassert>
#include <vector>
#include <cstring>
static std::vector<unsigned char> input;
static bool shortRead=false, openFail=false;
static int closed=0;
DWORD GetCascError(){return 2;}
bool WINAPI CascOpenStorageEx(LPCTSTR,PCASC_OPEN_STORAGE_ARGS,bool,HANDLE*){return false;}
bool WINAPI CascCloseStorage(HANDLE){return true;}
bool WINAPI CascOpenFile(HANDLE,void const* key,DWORD,DWORD flags,HANDLE* file){
 assert(flags==(CASC_OPEN_BY_CKEY|CASC_STRICT_DATA_CHECK));
 assert(static_cast<unsigned char const*>(key)[0]==0x6e);
 if(openFail)return false;
 *file=reinterpret_cast<HANDLE>(1);return true;
}
bool WINAPI CascGetFileSize64(HANDLE,PULONGLONG size){*size=input.size();return true;}
bool WINAPI CascReadFile(HANDLE,void* out,DWORD n,PDWORD count){
 *count=shortRead?n-1:n;memcpy(out,input.data(),*count);return true;
}
bool WINAPI CascCloseFile(HANDLE){++closed;return true;}
int main(){
 std::array<unsigned char,16> key{};
 assert(!ParseCKey("1234",key));
 assert(!ParseCKey("6g2657526d320facacb6f3dfff62d8a2",key));
 assert(ParseCKey("6E2657526d320facacb6f3dfff62d8a2",key));
 assert(key[0]==0x6e&&key[15]==0xa2);
 input.assign(128,0x42);
 assert(ManifestMetadata(nullptr,"prefix","key",key,false));
 input.assign(37324,0x43);
 assert(ManifestMetadata(nullptr,"full","key",key,true));
 input.assign(65537,0x44);
 assert(!ManifestMetadata(nullptr,"oversize","key",key,true));
 input.assign(0,0);
 assert(!ManifestMetadata(nullptr,"empty","key",key,true));
 input.assign(128,0x42);shortRead=true;
 assert(!ManifestMetadata(nullptr,"short","key",key,false));
 openFail=true;
 assert(!ManifestMetadata(nullptr,"missing","key",key,false));
 assert(closed==5);
}
