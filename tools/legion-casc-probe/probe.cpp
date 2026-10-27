// Read-only local CASC diagnostic. Uses the exact CascLib built by the Forever core.
#include <CascLib.h>
#include <openssl/evp.h>
#include <array>
#include <cstdio>
#include <memory>
#include <string>
#include <string_view>
#include <span>
#include <vector>

static bool ParseCKey(std::string_view text, std::array<unsigned char,16>& key) {
    if(text.size()!=32) return false;
    auto digit=[](char c)->int {
        if(c>='0'&&c<='9') return c-'0';
        if(c>='a'&&c<='f') return c-'a'+10;
        if(c>='A'&&c<='F') return c-'A'+10;
        return -1;
    };
    for(size_t i=0;i<key.size();++i) {
        int hi=digit(text[2*i]),lo=digit(text[2*i+1]);
        if(hi<0||lo<0) return false;
        key[i]=static_cast<unsigned char>((hi<<4)|lo);
    }
    return true;
}

// Inspect legacy ROOT's header and the small TVFS top-level directory only.
// No data files are exported. A prefix is not a full-file integrity check.
static bool ManifestMetadata(HANDLE storage, char const* label, char const* ckey,
                             std::array<unsigned char,16> const& key, bool whole) {
    HANDLE file=nullptr;
    if(!CascOpenFile(storage,key.data(),CASC_LOCALE_ALL_WOW,
                     CASC_OPEN_BY_CKEY|CASC_STRICT_DATA_CHECK,&file)) {
        std::printf("%s\t%s\tOPEN_FAILED\t0\t0\t-\t%u\n",label,ckey,GetCascError());
        return false;
    }
    ULONGLONG size=0;
    if(!CascGetFileSize64(file,&size)) {
        std::printf("%s\t%s\tSIZE_FAILED\t0\t0\t-\t%u\n",label,ckey,GetCascError());
        CascCloseFile(file);return false;
    }
    if(size==0||(whole&&size>65536)) {
        std::printf("%s\t%s\tSIZE_REJECTED\t%llu\t0\t-\t0\n",label,ckey,
                    static_cast<unsigned long long>(size));
        CascCloseFile(file);return false;
    }
    std::array<unsigned char,65536> bytes{};
    DWORD want=static_cast<DWORD>(whole?size:(size<64?size:64)),got=0;
    if(!CascReadFile(file,bytes.data(),want,&got)||got!=want) {
        std::printf("%s\t%s\tREAD_FAILED\t%llu\t%u\t-\t%u\n",label,ckey,
                    static_cast<unsigned long long>(size),got,GetCascError());
        CascCloseFile(file);return false;
    }
    std::printf("%s\t%s\t%s\t%llu\t%u\t",label,ckey,whole?"FULL_READ_OK":"PREFIX_READ_OK",
                static_cast<unsigned long long>(size),got);
    for(DWORD i=0;i<got;++i) std::printf("%02x",bytes[i]);
    std::puts("\t0");
    CascCloseFile(file);return true;
}

struct Target { char const* label; DWORD id; char const* name; unsigned char const* ckey=nullptr; };
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
    bool metadata=argc==6&&std::string_view(argv[3])=="--manifest-metadata";
    bool contentKeys=argc>=5&&std::string_view(argv[3])=="--content-keys";
    std::array<unsigned char,16> rootKey{},vfsKey{};
    if((argc!=3&&!metadata&&!contentKeys)||(metadata&&
       (!ParseCKey(argv[4],rootKey)||!ParseCKey(argv[5],vfsKey)))) {
        std::fprintf(stderr,"Usage: legion-casc-probe CLIENT_ROOT PRODUCT [--manifest-metadata ROOT_CKEY VFS_ROOT_CKEY | --content-keys CKEY ...]\n");
        return 2;
    }
    std::vector<std::array<unsigned char,16>> keys(contentKeys?argc-4:0);
    std::vector<Target> keyTargets;
    for(size_t i=0;i<keys.size();++i) {
        if(!ParseCKey(argv[i+4],keys[i])) {
            std::fprintf(stderr,"Invalid content key: expected 32 hexadecimal digits\n");return 2;
        }
        keyTargets.push_back({argv[i+4],0,nullptr,keys[i].data()});
    }
    std::span<Target const> selected=contentKeys?std::span<Target const>(keyTargets):std::span<Target const>(targets);
    CASC_OPEN_STORAGE_ARGS args{};
    args.Size=sizeof(args); args.szLocalPath=argv[1]; args.szCodeName=argv[2];
    args.dwLocaleMask=CASC_LOCALE_ALL_WOW;
    HANDLE storage=nullptr;
    // Local storage, no ONLINE or FORCE_DOWNLOAD flags. Never zero-fill encrypted data.
    if(!CascOpenStorageEx(nullptr,&args,false,&storage)) {
        std::fprintf(stderr,"LOCAL_STORAGE_OPEN_FAILED error=%u\n",GetCascError());return 1;
    }
    if(metadata) {
        std::puts("label\tckey\tstatus\tfile_bytes\tread_bytes\thex\terror");
        bool rootOk=ManifestMetadata(storage,"root_prefix",argv[4],rootKey,false);
        bool vfsOk=ManifestMetadata(storage,"vfs_root",argv[5],vfsKey,true);
        CascCloseStorage(storage);
        return rootOk&&vfsOk?0:1;
    }
    std::puts("label\tfile_data_id\tstatus\tbytes\tsha256\terror");
    for(auto const& target:selected) {
        HANDLE file=nullptr;
        DWORD flags=(target.ckey?CASC_OPEN_BY_CKEY:(target.id?CASC_OPEN_BY_FILEID:CASC_OPEN_BY_NAME))|CASC_STRICT_DATA_CHECK;
        void const* name=target.ckey?static_cast<void const*>(target.ckey):
                         (target.id?CASC_FILE_DATA_ID(target.id):static_cast<void const*>(target.name));
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
