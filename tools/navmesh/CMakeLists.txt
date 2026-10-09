cmake_minimum_required(VERSION 3.16)
project(boz_navmesh CXX)

# Recast and Detour from the tools/recast submodule (zlib licence), built as static libraries.
set(RECAST ${CMAKE_CURRENT_SOURCE_DIR}/../recast)
file(GLOB RECAST_SOURCES ${RECAST}/Recast/Source/*.cpp)
file(GLOB DETOUR_SOURCES ${RECAST}/Detour/Source/*.cpp)

add_executable(boz-navmesh boz_navmesh.cpp ${RECAST_SOURCES} ${DETOUR_SOURCES})
target_include_directories(boz-navmesh PRIVATE ${RECAST}/Recast/Include ${RECAST}/Detour/Include)
target_compile_features(boz-navmesh PRIVATE cxx_std_17)
if(NOT MSVC)
  target_compile_options(boz-navmesh PRIVATE -O2)
  # Self-contained binary so Blender can run it without the SDK's toolchain.
  target_link_options(boz-navmesh PRIVATE -static-libstdc++ -static-libgcc)
endif()
