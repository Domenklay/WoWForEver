cmake_minimum_required(VERSION 3.23)
project(ForeverCascReader LANGUAGES C CXX)

# Reuse the pinned core's exact CascLib source list and build definitions.
# Supply only its small dependency interfaces, without configuring TrinityCore.
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY /src/TrinityCore/build/dep/CascLib)
find_package(ZLIB REQUIRED)
add_library(zlib INTERFACE)
target_link_libraries(zlib INTERFACE ZLIB::ZLIB)
add_library(trinity-dependency-interface INTERFACE)
target_compile_definitions(trinity-dependency-interface INTERFACE _FILE_OFFSET_BITS=64)
add_subdirectory(/src/TrinityCore/dep/CascLib casc)
