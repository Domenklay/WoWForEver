cmake_minimum_required(VERSION 3.16)
project(ForeverSubclassPrototype VERSION 0.2.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(forever_subclass
    src/SubclassSystem.cpp
)
target_include_directories(forever_subclass PUBLIC include)

add_executable(forever_subclass_demo src/main.cpp)
target_link_libraries(forever_subclass_demo PRIVATE forever_subclass)

enable_testing()
add_executable(forever_subclass_tests tests/test_subclass.cpp)
target_link_libraries(forever_subclass_tests PRIVATE forever_subclass)
add_test(NAME forever_subclass_tests COMMAND forever_subclass_tests)
