# Host build of the portable core: unit tests and the parity CLI.
#   cmake -S firmware -B build/firmware -DSANITIZE=ON && cmake --build build/firmware
#   ctest --test-dir build/firmware --output-on-failure
cmake_minimum_required(VERSION 3.20)
project(dragonfly_core_host CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
option(SANITIZE "Build with address and undefined-behaviour sanitizers" OFF)

add_compile_options(-Wall -Wextra -Wpedantic -Werror -Wconversion -Wshadow)
if(SANITIZE)
  add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=all)
  add_link_options(-fsanitize=address,undefined)
endif()

file(GLOB CORE_SOURCES CONFIGURE_DEPENDS lib/dragonfly_core/src/*.cpp)
add_library(dragonfly_core STATIC ${CORE_SOURCES})
target_include_directories(dragonfly_core PUBLIC lib/dragonfly_core/src)

add_executable(core_tests test/host/test_main.cpp)
target_link_libraries(core_tests PRIVATE dragonfly_core)

add_executable(core_cli tools/core_cli.cpp)
target_link_libraries(core_cli PRIVATE dragonfly_core)

enable_testing()
add_test(NAME core_tests COMMAND core_tests)
