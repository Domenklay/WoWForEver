// Syntax-only cross-check using the unchanged Forever CascLib TVFS readers.
// Does not open a CASC storage, resolve subdirectories or validate WowB.exe.
// Compile this TU instead of CascRootFile_TVFS.cpp, with other CascLib sources.
#include "CascRootFile_TVFS.cpp"
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

static void Walk(TRootHandler_TVFS& reader, TVFS_DIRECTORY_HEADER& header,
                 CASC_PATH<char>& path, LPBYTE pos, LPBYTE end, int depth) {
    if(depth>64) throw std::runtime_error("nesting limit");
    auto saved=path.Save();
    while(pos<end) {
        TVFS_PATH_TABLE_ENTRY entry;
        pos=reader.CapturePathEntry(entry,pos,end);
        if(!pos) throw std::runtime_error("bad path entry");
        reader.PathBuffer_AppendNode(path,entry);
        if(!(entry.NodeFlags&TVFS_PTE_NODE_VALUE)) continue;
        if(entry.NodeValue&TVFS_FOLDER_NODE) {
            auto length=entry.NodeValue&TVFS_FOLDER_SIZE_MASK;
            if(length<4||length-4>static_cast<size_t>(end-pos))
                throw std::runtime_error("bad folder length");
            auto stop=pos+length-4;
            Walk(reader,header,path,pos,stop,depth+1);
            pos=stop;
        } else {
            DWORD count=0;
            auto spans=reader.CaptureVfsSpanCount(header,entry.NodeValue,count);
            if(!spans) throw std::runtime_error("bad span count");
            std::vector<CASC_CKEY_ENTRY> entries(count);
            if(!reader.CaptureVfsSpanEntries(header,spans,entries.data(),count))
                throw std::runtime_error("bad spans");
            std::cout<<static_cast<char const*>(path)<<'\t'<<count;
            for(auto const& span:entries) {
                std::cout<<'\t';
                static char const hex[]="0123456789abcdef";
                for(size_t i=0;i<header.EKeySize;++i)
                    std::cout<<hex[span.EKey[i]>>4]<<hex[span.EKey[i]&15];
                std::cout<<':'<<span.ContentSize;
            }
            std::cout<<'\n';
        }
        path.Restore(saved);
    }
}

int main(int argc,char** argv) {
    try {
        if(argc!=2) throw std::runtime_error("usage: check-tvfs DECODED_TVFS");
        std::ifstream input(argv[1],std::ios::binary|std::ios::ate);
        if(!input) throw std::runtime_error("open failed");
        auto size=input.tellg();
        if(size<46||size>1024*1024) throw std::runtime_error("size rejected");
        CASC_BLOB blob;
        if(blob.SetSize(static_cast<size_t>(size))!=ERROR_SUCCESS)
            throw std::runtime_error("allocation failed");
        input.seekg(0);
        if(!input.read(reinterpret_cast<char*>(blob.pbData),size))
            throw std::runtime_error("read failed");
        TVFS_DIRECTORY_HEADER header;
        if(TRootHandler_TVFS::CaptureDirectoryHeader(header,blob)!=ERROR_SUCCESS)
            throw std::runtime_error("bad header");
        if(header.PathTableOffset>header.Data.cbData||
           header.PathTableSize>header.Data.cbData-header.PathTableOffset)
            throw std::runtime_error("bad path table");
        TRootHandler_TVFS reader;
        CASC_PATH<char> path;
        Walk(reader,header,path,header.DataAt(header.PathTableOffset),
             header.DataAt(header.PathTableOffset)+header.PathTableSize,0);
        return 0;
    } catch(std::exception const& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
