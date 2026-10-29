// Offline, read-only CASC path probe. Failed name resolution does not prove asset absence.
#include <CascLib.h>
#include <openssl/evp.h>
#include <array>
#include <cstdio>
int main(int argc,char** argv)
{
    if(argc!=2) return 2;
    HANDLE storage=nullptr;
    CASC_OPEN_STORAGE_ARGS args{};args.Size=sizeof(args);args.szLocalPath=argv[1];
    args.szCodeName="wow_classic_beta";args.dwLocaleMask=CASC_LOCALE_RURU;
    if(!CascOpenStorageEx(nullptr,&args,false,&storage))
    { std::printf("{\"storage_opened\":false,\"error\":%u}\n",GetCascError());return 1; }
    char const* names[]={"world/maps/Azeroth/Azeroth.wdt","world/maps/Expansion01/Expansion01.wdt",
        "world/maps/Expansion01/Expansion01_24_33.adt","world/maps/Expansion01/Expansion01_24_33_obj0.adt",
        "world/maps/Expansion01/Expansion01_24_33_tex0.adt",
        "world/maps/Expansion01/Expansion01_33_24.adt"};
    std::printf("{\"storage_opened\":true,\"negative_name_lookup_proves_absence\":false,\"files\":[");
    bool first=true;
    for(char const* name:names)
    {
        if(!first) std::printf(",");first=false;
        std::printf("{\"path\":\"%s\"",name);
        HANDLE file=nullptr;
        if(!CascOpenFile(storage,name,CASC_LOCALE_RURU,CASC_OPEN_BY_NAME|CASC_STRICT_DATA_CHECK,&file))
        { std::printf(",\"status\":\"OPEN_FAILED\",\"error\":%u}",GetCascError());continue; }
        ULONGLONG size=0;
        if(!CascGetFileSize64(file,&size)||size>64ULL*1024*1024)
        { std::printf(",\"status\":\"SIZE_FAILED_OR_LIMIT\",\"error\":%u}",GetCascError());CascCloseFile(file);continue; }
        EVP_MD_CTX* digest=EVP_MD_CTX_new();
        if(!digest||EVP_DigestInit_ex(digest,EVP_sha256(),nullptr)!=1) return 3;
        std::array<unsigned char,65536> block{};ULONGLONG total=0;bool ok=true;DWORD error=0;
        while(total<size)
        {
            DWORD want=DWORD((size-total)<block.size()?size-total:block.size()),got=0;
            if(!CascReadFile(file,block.data(),want,&got)||got!=want) { ok=false;error=GetCascError();break; }
            if(EVP_DigestUpdate(digest,block.data(),got)!=1) return 3;
            total+=got;
        }
        unsigned char hash[EVP_MAX_MD_SIZE];unsigned int count=0;
        if(ok&&EVP_DigestFinal_ex(digest,hash,&count)!=1) return 3;
        std::printf(",\"status\":\"%s\",\"bytes_read\":%llu,\"error\":%u",ok?"READ_OK":"READ_FAILED",(unsigned long long)total,error);
        if(ok) { std::printf(",\"sha256\":\"");for(unsigned int i=0;i<count;++i) std::printf("%02x",hash[i]);std::printf("\""); }
        std::printf("}");EVP_MD_CTX_free(digest);CascCloseFile(file);
    }
    std::printf("]}\n");CascCloseStorage(storage);return 0;
}
