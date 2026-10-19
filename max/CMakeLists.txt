cmake_minimum_required(VERSION 3.25)

# Max 9 external build. max-sdk-base (vendored in third_party/) provides the Max headers and packaging scripts.
set(CMAKE_OSX_ARCHITECTURES "arm64;x86_64" CACHE STRING "macOS architectures")
set(CMAKE_OSX_DEPLOYMENT_TARGET "11.0" CACHE STRING "")

include(FetchContent)
set(_SDK_BASE "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/max-sdk-base")
if(EXISTS "${_SDK_BASE}/script/max-pretarget.cmake")
  set(FETCHCONTENT_SOURCE_DIR_MAX-SDK-BASE "${_SDK_BASE}")
endif()
FetchContent_Declare(max-sdk-base GIT_REPOSITORY https://github.com/Cycling74/max-sdk-base.git GIT_TAG main)
FetchContent_MakeAvailable(max-sdk-base)

project(fidddle_max CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_subdirectory(../core core_build EXCLUDE_FROM_ALL)

# The finished .mxo is written into a Max package skeleton inside this repo
set(C74_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../package/fidddle/externals")

add_subdirectory(fidddle~)
