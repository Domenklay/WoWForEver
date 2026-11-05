// End-to-end local storage check. No network flags, encryption overrides or writes.
#include <CascLib.h>
#include <openssl/evp.h>
#include <array>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <vector>
#include <charconv>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <string_view>

static bool WINAPI Progress(void*,CASC_PROGRESS_MSG kind,LPCSTR object,DWORD,DWORD) {
    std::fprintf(stderr,"stage=%u object=%s\n",static_cast<unsigned>(kind),object?object:"");
    return false;
}


static std::uint32_t ReadLe32(unsigned char const* ptr) {
    return std::uint32_t(ptr[0]) | (std::uint32_t(ptr[1]) << 8) |
           (std::uint32_t(ptr[2]) << 16) | (std::uint32_t(ptr[3]) << 24);
}

static bool ParsePositive(std::string_view text, std::uint32_t& value) {
    auto parsed=std::from_chars(text.data(),text.data()+text.size(),value);
    return parsed.ec==std::errc{} && parsed.ptr==text.data()+text.size() && value>0;
}

static bool ParseContentKey(std::string_view hex, std::array<unsigned char,16>& key) {
    if(hex.size()!=32) return false;
    auto digit=[](char c)->int {
        if(c>='0' && c<='9') return c-'0';
        if(c>='a' && c<='f') return c-'a'+10;
        if(c>='A' && c<='F') return c-'A'+10;
        return -1;
    };
    for(std::size_t i=0;i<16;++i) {
        int hi=digit(hex[2*i]),lo=digit(hex[2*i+1]);
        if(hi<0 || lo<0) return false;
        key[i]=static_cast<unsigned char>((hi<<4)|lo);
    }
    return true;
}

// Read-only, bounded discovery of real BLP assets in the selected product.
// ROOT metadata is decoded by CascLib; every reported ID is independently
// opened by FileDataID and checked for a BLP magic, not guessed from its number.
static int FindRootBlps(HANDLE storage, DWORD locale, int argc, char** argv) {
    std::array<unsigned char,16> rootKey{};
    std::uint32_t maxChecks=3000,maxHits=12;
    if(argc<4 || argc>6 || !ParseContentKey(argv[3],rootKey) ||
       (argc>=5 && !ParsePositive(argv[4],maxChecks)) ||
       (argc==6 && !ParsePositive(argv[5],maxHits)) ||
       maxChecks>20000 || maxHits>100) {
        std::fprintf(stderr,
            "Usage: check-storage CLIENT_ROOT --root-blp ROOT_CKEY [MAX_CHECKS<=20000] [MAX_HITS<=100]\n");
        return 2;
    }
    HANDLE rootFile=nullptr;
    if(!CascOpenFile(storage,rootKey.data(),locale,
                     CASC_OPEN_BY_CKEY|CASC_STRICT_DATA_CHECK,&rootFile)) {
        std::fprintf(stderr,"ROOT_OPEN_FAILED error=%u\n",GetCascError());
        return 1;
    }
    ULONGLONG rootSize=0;
    if(!CascGetFileSize64(rootFile,&rootSize) || rootSize<24 ||
       rootSize>256ull*1024*1024) {
        std::fprintf(stderr,"ROOT_SIZE_UNSUPPORTED bytes=%llu error=%u\n",
                     static_cast<unsigned long long>(rootSize),GetCascError());
        CascCloseFile(rootFile);
        return 1;
    }
    std::vector<unsigned char> raw(static_cast<std::size_t>(rootSize));
    for(std::size_t pos=0;pos<raw.size();) {
        DWORD want=static_cast<DWORD>(std::min<std::size_t>(raw.size()-pos,1024*1024));
        DWORD got=0;
        if(!CascReadFile(rootFile,raw.data()+pos,want,&got) || got!=want) {
            std::fprintf(stderr,"ROOT_READ_FAILED at=%zu error=%u\n",pos,GetCascError());
            CascCloseFile(rootFile);
            return 1;
        }
        pos+=got;
    }
    CascCloseFile(rootFile);
    if(std::memcmp(raw.data(),"TSFM",4)!=0 || ReadLe32(raw.data()+4)!=24 ||
       ReadLe32(raw.data()+8)!=2) {
        std::fprintf(stderr,"ROOT_FORMAT_UNSUPPORTED (expected TSFM version 2)\n");
        return 1;
    }
    std::uint32_t total=ReadLe32(raw.data()+12),named=ReadLe32(raw.data()+16);
    if(named>total || total>15000000) {
        std::fprintf(stderr,"ROOT_RECORD_COUNT_UNSUPPORTED count=%u\n",total);
        return 1;
    }
    std::vector<std::uint32_t> ids;
    ids.reserve(total);
    std::uint64_t seen=0,seenNamed=0;
    std::uint32_t groups=0;
    for(std::size_t pos=24;pos<raw.size();) {
        if(raw.size()-pos<17) {
            std::fprintf(stderr,"ROOT_GROUP_TRUNCATED\n");return 1;
        }
        std::uint32_t count=ReadLe32(raw.data()+pos);
        std::uint32_t f1=ReadLe32(raw.data()+pos+8);
        std::uint32_t f2=ReadLe32(raw.data()+pos+12);
        std::uint32_t f3=raw[pos+16];
        bool hasNames=!((f1|f2|(f3<<17))&0x10000000u);
        pos+=17;
        std::uint64_t groupBytes=std::uint64_t(count)*(hasNames?28u:20u);
        if(groupBytes>raw.size()-pos || seen+count>total) {
            std::fprintf(stderr,"ROOT_GROUP_BOUNDS_INVALID\n");return 1;
        }
        std::uint64_t current=0;
        for(std::uint32_t i=0;i<count;++i) {
            current+=ReadLe32(raw.data()+pos+4ull*i);
            if(current>0xffffffffull) {
                std::fprintf(stderr,"ROOT_FILEDATAID_OVERFLOW\n");return 1;
            }
            if(current) ids.push_back(static_cast<std::uint32_t>(current));
            ++current;
        }
        pos+=static_cast<std::size_t>(groupBytes);
        seen+=count;
        if(hasNames) seenNamed+=count;
        ++groups;
    }
    if(seen!=total || seenNamed!=named) {
        std::fprintf(stderr,"ROOT_GROUP_COUNTS_MISMATCH\n");return 1;
    }
    std::sort(ids.begin(),ids.end());
    ids.erase(std::unique(ids.begin(),ids.end()),ids.end());
    auto checks=std::min<std::size_t>(maxChecks,ids.size());
    std::size_t opened=0,hits=0;
    std::puts("file_id\tbytes\tckey\tmagic");
    for(std::size_t i=0;i<checks && hits<maxHits;++i) {
        std::size_t index=checks==1?0:static_cast<std::size_t>(
            std::uint64_t(i)*(ids.size()-1)/(checks-1));
        HANDLE file=nullptr;
        if(!CascOpenFile(storage,CASC_FILE_DATA_ID(ids[index]),locale,
                         CASC_OPEN_BY_FILEID|CASC_STRICT_DATA_CHECK,&file)) continue;
        ++opened;
        ULONGLONG size=0;
        unsigned char magic[4]{};
        DWORD got=0;
        if(CascGetFileSize64(file,&size) && size>=4 && size<=64ull*1024*1024 &&
           CascReadFile(file,magic,4,&got) && got==4 &&
           (std::memcmp(magic,"BLP2",4)==0 || std::memcmp(magic,"BLP1",4)==0)) {
            std::array<unsigned char,16> ckey{};
            bool hasKey=CascGetFileInfo(file,CascFileContentKey,ckey.data(),ckey.size(),nullptr);
            std::printf("%u\t%llu\t",ids[index],static_cast<unsigned long long>(size));
            if(hasKey) for(auto byte:ckey) std::printf("%02x",byte);
            else std::printf("-");
            std::printf("\t%c%c%c%c\n",magic[0],magic[1],magic[2],magic[3]);
            ++hits;
        }
        CascCloseFile(file);
    }
    std::fprintf(stderr,
        "ROOT_SCAN records=%u groups=%u unique_ids=%zu attempted=%zu opened=%zu blp_hits=%zu\n",
        total,groups,ids.size(),checks,opened,hits);
    return 0;
}

int main(int argc,char** argv) {
    if(argc<3) { std::fprintf(stderr,"Usage: check-storage CLIENT_ROOT FILE_ID [...]\n");return 2; }
    DWORD locale=CASC_LOCALE_ALL_WOW;
    if(char const* setting=std::getenv("CASC_CHECK_LOCALE")) {
        std::string_view name(setting);
        if(name=="ruRU") locale=CASC_LOCALE_RURU;
        else if(name=="enUS") locale=CASC_LOCALE_ENUS;
        else if(name!="all") { std::fprintf(stderr,"CASC_CHECK_LOCALE must be all, ruRU or enUS\n");return 2; }
    }
    std::fprintf(stderr,"locale_mask=%x\n",locale);
    CASC_OPEN_STORAGE_ARGS args{};
    args.Size=sizeof(args);args.szLocalPath=argv[1];
    // Launcher 2.x uses a separate release product; keep beta as the default.
    char const* product=std::getenv("CASC_CHECK_PRODUCT");
    std::string_view name=(product&&*product)?std::string_view(product):std::string_view("wow_classic_beta");
    if(name!="wow_classic_beta" && name!="wowf") {
        std::fprintf(stderr,"CASC_CHECK_PRODUCT must be wow_classic_beta or wowf\n");return 2;
    }
    args.szCodeName=(product&&*product)?product:"wow_classic_beta";
    args.dwLocaleMask=locale;
    args.PfnProgressCallback=Progress;
    HANDLE storage=nullptr;
    if(!CascOpenStorageEx(nullptr,&args,false,&storage)) {
        std::fprintf(stderr,"STORAGE_OPEN_FAILED error=%u\n",GetCascError());return 1;
    }
    if(std::string_view(argv[2])=="--root-blp") {
        int result=FindRootBlps(storage,locale,argc,argv);
        CascCloseStorage(storage);
        return result;
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
        if(!CascOpenFile(storage,CASC_FILE_DATA_ID(id),locale,
                         CASC_OPEN_BY_FILEID|CASC_STRICT_DATA_CHECK,&file)) {
            std::printf("%u\tOPEN_FAILED\t0\t-\t-\t%u\t-\t-\t-\n",id,GetCascError());all=false;continue;
        }
        std::array<unsigned char,16> selectedKey{};
        bool hasSelectedKey=CascGetFileInfo(file,CascFileContentKey,selectedKey.data(),selectedKey.size(),nullptr);
        ULONGLONG size=0;
        if(!CascGetFileSize64(file,&size)) {
            DWORD error=GetCascError();
            std::printf("%u\tSIZE_FAILED\t0\t-\t-\t%u\t",id,error);
            if(hasSelectedKey) for(unsigned char byte:selectedKey)std::printf("%02x",byte);
            else std::printf("-");
            std::puts("\t-\t-");
            CascCloseFile(file);all=false;continue;
        }
        if(size>64ull*1024*1024) {
            std::printf("%u\tSIZE_LIMIT\t%llu\t-\t-\t0\t-\t-\t-\n",id,static_cast<unsigned long long>(size));
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
