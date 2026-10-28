// Read-only validation through the pinned core loader. No opaque-section keys.
#include "DB2FileLoader.h"
#include "DB2Meta.h"
#include "DB2Metadata.h"
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <vector>

class Source final : public DB2FileSource
{
    std::vector<char> _bytes;
    std::size_t _position = 0;
    std::string _path;
public:
    explicit Source(char const* path) : _path(path)
    {
        std::ifstream file(path, std::ios::binary);
        _bytes.assign(std::istreambuf_iterator<char>(file), {});
    }
    bool IsOpen() const override { return !_bytes.empty(); }
    bool Read(void* destination, std::size_t count) override
    {
        if (count > _bytes.size() - _position)
            return false;
        std::memcpy(destination, _bytes.data() + _position, count);
        _position += count;
        return true;
    }
    int64 GetPosition() const override { return _position; }
    bool SetPosition(int64 position) override
    {
        if (position < 0 || std::size_t(position) > _bytes.size())
            return false;
        _position = position;
        return true;
    }
    int64 GetFileSize() const override { return _bytes.size(); }
    char const* GetFileName() const override { return _path.c_str(); }
    DB2EncryptedSectionHandling HandleEncryptedSection(DB2SectionHeader const&) const override
    {
        return DB2EncryptedSectionHandling::Skip;
    }
};

int main(int argc, char** argv)
{
    if (argc != 2)
        return 2;
    DB2FieldMeta fields[30]{};
    fields[0] = {false, FT_INT, "ID"};
    std::size_t index = 1;
    for (auto const& meta : MapMeta::Fields)
        for (int i = 0; i < meta.ArraySize; ++i)
            fields[index++] = {(meta.Type == FT_FLOAT || meta.Type == FT_STRING ||
                                meta.Type == FT_STRING_NOT_LOCALIZED) ? false : meta.IsSigned,
                               meta.Type, "field"};
    DB2FileLoadInfo info(fields, 30, &MapMeta::Instance);
    try
    {
        Source source(argv[1]);
        DB2FileLoader loader;
        loader.Load(&source, &info);
        for (uint32 i = 0; i < loader.GetRecordCount(); ++i)
        {
            auto record = loader.GetRecord(i);
            if (!record)
                continue;
            std::cout << record.GetId();
            for (uint32 field = 0; field < 26; ++field)
                for (uint32 element = 0; element < MapMeta::Fields[field].ArraySize; ++element)
                {
                    std::cout << '\t';
                    if (field < 6)
                    {
                        auto text = record.GetString(field, element);
                        if (text)
                            for (; *text; ++text)
                                std::printf("%02x", static_cast<unsigned char>(*text));
                    }
                    else
                        std::cout << record.GetUInt32(field, element);
                }
            std::cout << '\n';
        }
    }
    catch (std::exception const& error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
