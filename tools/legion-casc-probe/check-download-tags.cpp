// Verify DOWNLOAD tag memberships through the pinned CascLib, not Python.
#include <CascLib.h>
#include <charconv>
#include <cstdio>
#include <string_view>

int main(int argc, char** argv) {
    if (argc != 4) {
        std::fprintf(stderr,"Usage: check-download-tags CLIENT_ROOT FILE_ID EXPECTED_MASK_HEX\n");
        return 2;
    }
    DWORD id=0; unsigned long long expected=0;
    std::string_view fid(argv[2]), mask(argv[3]);
    auto a=std::from_chars(fid.data(),fid.data()+fid.size(),id);
    auto b=std::from_chars(mask.data(),mask.data()+mask.size(),expected,16);
    if(a.ec!=std::errc{}||a.ptr!=fid.data()+fid.size()||!id||
       b.ec!=std::errc{}||b.ptr!=mask.data()+mask.size()) return 2;
    CASC_OPEN_STORAGE_ARGS args{};
    args.Size=sizeof(args);args.szLocalPath=argv[1];args.szCodeName="wow_classic_beta";
    args.dwLocaleMask=CASC_LOCALE_ALL_WOW;
    HANDLE storage=nullptr,file=nullptr;
    if(!CascOpenStorageEx(nullptr,&args,false,&storage)) return 1;
    CASC_FILE_FULL_INFO info{};
    bool ok=CascOpenFile(storage,CASC_FILE_DATA_ID(id),CASC_LOCALE_ALL_WOW,
                        CASC_OPEN_BY_FILEID|CASC_STRICT_DATA_CHECK,&file);
    if(ok) ok=CascGetFileInfo(file,CascFileFullInfo,&info,sizeof(info),nullptr);
    if(ok) {
        std::printf("file_id=%u tag_mask=%llx expected=%llx\n",id,
                    static_cast<unsigned long long>(info.TagBitMask),expected);
        ok=info.TagBitMask==expected;
    }
    if(file) CascCloseFile(file);
    CascCloseStorage(storage);
    return ok?0:1;
}
