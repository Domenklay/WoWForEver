// End-to-end local storage check. No network flags, encryption overrides or writes.
#include <CascLib.h>
#include <openssl/evp.h>
#include <array>
#include <charconv>
#include <cstdio>
#include <memory>
#include <string_view>

static bool WINAPI Progress(void*,CASC_PROGRESS_MSG kind,LPCSTR object,DWORD,DWORD) {
    std::fprintf(stderr,"stage=%u object=%s\n",static_cast<unsigned>(kind),object?object:"");
    return false;
}

int main(int argc,char** argv) {
    if(argc<3) { std::fprintf(stderr,"Usage: check-storage CLIENT_ROOT FILE_ID [...]\n");return 2; }
    CASC_OPEN_STORAGE_ARGS args{};
    args.Size=sizeof(args);args.szLocalPath=argv[1];args.szCodeName="wow_classic_beta";
    args.dwLocaleMask=CASC_LOCALE_ALL_WOW;
    args.PfnProgressCallback=Progress;
    HANDLE storage=nullptr;
    if(!CascOpenStorageEx(nullptr,&args,false,&storage)) {
        std::fprintf(stderr,"STORAGE_OPEN_FAILED error=%u\n",GetCascError());return 1;
    }
    bool all=true;
    std::puts("file_id\tstatus\tbytes\tsha256\ttag_mask\terror\tckey\tlocale_flags\tcontent_flags");
    for(int index=2;index<argc;++index) {
        std::string_view text(argv[index]);DWORD id=0;
        auto parse=std::from_chars(text.data(),text.data()+text.size(),id);
        if(parse.ec!=std::errc{}||parse.ptr!=text.data()+text.size()||id==0) {
            std::fprintf(stderr,"Invalid FileDataID\n");CascCloseStorage(storage);return 2;
        }
        HANDLE file=nullptr;
        if(!CascOpenFile(storage,CASC_FILE_DATA_ID(id),CASC_LOCALE_ALL_WOW,
                         CASC_OPEN_BY_FILEID|CASC_STRICT_DATA_CHECK,&file)) {
            std::printf("%u\tOPEN_FAILED\t0\t-\t-\t%u\t-\t-\t-\n",id,GetCascError());all=false;continue;
        }
        ULONGLONG size=0;
        if(!CascGetFileSize64(file,&size)||size>64ull*1024*1024) {
            std::printf("%u\tSIZE_FAILED\t0\t-\t-\t%u\t-\t-\t-\n",id,GetCascError());
            CascCloseFile(file);all=false;continue;
        }
        std::array<unsigned char,65536> bytes{};
        std::unique_ptr<EVP_MD_CTX,decltype(&EVP_MD_CTX_free)> digest(EVP_MD_CTX_new(),EVP_MD_CTX_free);
        if(!digest||EVP_DigestInit_ex(digest.get(),EVP_sha256(),nullptr)!=1) {
            CascCloseFile(file);CascCloseStorage(storage);return 3;
        }
        DWORD got=0;
        bool ok=true;
        while(got<size) {
            DWORD want=static_cast<DWORD>((size-got)<bytes.size()?(size-got):bytes.size());
            DWORD read=0;
            bool readOk=CascReadFile(file,bytes.data(),want,&read);
            got+=read;
            if(!readOk||read!=want) {ok=false;break;}
            if(EVP_DigestUpdate(digest.get(),bytes.data(),read)!=1) {
                CascCloseFile(file);CascCloseStorage(storage);return 3;
            }
        }
        if(!ok) {
            std::printf("%u\tREAD_FAILED\t%u\t-\t-\t%u\t-\t-\t-\n",id,got,GetCascError());all=false;
        } else {
            unsigned char hash[EVP_MAX_MD_SIZE];unsigned int length=0;
            if(EVP_DigestFinal_ex(digest.get(),hash,&length)!=1||length!=32) {
                CascCloseFile(file);CascCloseStorage(storage);return 3;
            }
            CASC_FILE_FULL_INFO info{};
            if(!CascGetFileInfo(file,CascFileFullInfo,&info,sizeof(info),nullptr)) {
                std::printf("%u\tINFO_FAILED\t%u\t-\t-\t%u\t-\t-\t-\n",id,got,GetCascError());
                CascCloseFile(file);all=false;continue;
            }
            std::printf("%u\tREAD_OK\t%u\t",id,got);
            for(unsigned int i=0;i<length;++i)std::printf("%02x",hash[i]);
            std::printf("\t%llx\t0\t",static_cast<unsigned long long>(info.TagBitMask));
            for(unsigned int i=0;i<16;++i)std::printf("%02x",info.CKey[i]);
            std::printf("\t%x\t%x\n",info.LocaleFlags,info.ContentFlags);
        }
        CascCloseFile(file);
    }
    CascCloseStorage(storage);return all?0:1;
}
