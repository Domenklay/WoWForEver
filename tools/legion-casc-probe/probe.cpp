// Read-only local CASC diagnostic. Uses the exact CascLib built by the Forever core.
#include <CascLib.h>
#include <openssl/evp.h>
#include <array>
#include <cstdio>
#include <memory>
#include <string>

struct Target { char const* label; DWORD id; char const* name; };
static Target const targets[] = {
    {"tile_23_33_root",957774,nullptr},
    {"tile_23_33_obj0",956360,nullptr},
    {"tile_23_33_tex0",956397,nullptr},
    {"dalaran_wmo",1120838,nullptr},
    {"dalaran_group_000",1120853,nullptr},
    {"sample_m2",1379264,nullptr},
    {"sample_skin",1379316,nullptr},
    {"wdt_spaced",0,"world/maps/troll raid/troll raid.wdt"},
    {"wdt_compact",0,"world/maps/trollraid/trollraid.wdt"}
};
int main(int argc,char** argv) {
    if(argc!=3) { std::fprintf(stderr,"Usage: legion-casc-probe CLIENT_ROOT PRODUCT\n"); return 2; }
    CASC_OPEN_STORAGE_ARGS args{};
    args.Size=sizeof(args); args.szLocalPath=argv[1]; args.szCodeName=argv[2];
    args.dwLocaleMask=CASC_LOCALE_ALL_WOW;
    HANDLE storage=nullptr;
    // Local storage, no ONLINE or FORCE_DOWNLOAD flags. Never zero-fill encrypted data.
    if(!CascOpenStorageEx(nullptr,&args,false,&storage)) {
        std::fprintf(stderr,"LOCAL_STORAGE_OPEN_FAILED error=%u\n",GetCascError());return 1;
    }
    std::puts("label\tfile_data_id\tstatus\tbytes\tsha256\terror");
    for(auto const& target:targets) {
        HANDLE file=nullptr;
        DWORD flags=(target.id?CASC_OPEN_BY_FILEID:CASC_OPEN_BY_NAME)|CASC_STRICT_DATA_CHECK;
        void const* name=target.id?CASC_FILE_DATA_ID(target.id):static_cast<void const*>(target.name);
        if(!CascOpenFile(storage,name,CASC_LOCALE_ALL_WOW,flags,&file)) {
            std::printf("%s\t%u\tOPEN_FAILED\t0\t-\t%u\n",target.label,target.id,GetCascError());continue;
        }
        ULONGLONG size=0;
        if(!CascGetFileSize64(file,&size)||size>64ULL*1024*1024) {
            std::printf("%s\t%u\tSIZE_UNAVAILABLE_OR_TOO_LARGE\t0\t-\t%u\n",target.label,target.id,GetCascError());CascCloseFile(file);continue;
        }
        std::unique_ptr<EVP_MD_CTX,decltype(&EVP_MD_CTX_free)> digest(EVP_MD_CTX_new(),EVP_MD_CTX_free);
        if(!digest||EVP_DigestInit_ex(digest.get(),EVP_sha256(),nullptr)!=1) { CascCloseFile(file);CascCloseStorage(storage);return 3; }
        std::array<unsigned char,65536> buffer{};ULONGLONG total=0;DWORD error=0;bool ok=true;
        while(total<size) {
            DWORD count=0;
            auto want=static_cast<DWORD>((size-total)<buffer.size()?(size-total):buffer.size());
            if(!CascReadFile(file,buffer.data(),want,&count)||count!=want) { error=GetCascError();ok=false;break; }
            if(EVP_DigestUpdate(digest.get(),buffer.data(),count)!=1) { error=0;ok=false;break; }
            total+=count;
        }
        unsigned char hash[EVP_MAX_MD_SIZE];unsigned int length=0;
        if(ok&&EVP_DigestFinal_ex(digest.get(),hash,&length)==1&&length==32) {
            std::printf("%s\t%u\tREAD_OK\t%llu\t",target.label,target.id,static_cast<unsigned long long>(total));
            for(unsigned int i=0;i<length;++i) std::printf("%02x",hash[i]);
            std::puts("\t0");
        } else std::printf("%s\t%u\tREAD_FAILED\t%llu\t-\t%u\n",target.label,target.id,static_cast<unsigned long long>(total),error);
        CascCloseFile(file);
    }
    CascCloseStorage(storage);
    // Missing files are report outcomes; only inability to run the diagnostic is a command error.
    return 0;
}
