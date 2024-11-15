cmake_minimum_required(VERSION 3.15)

project(
    verify
    VERSION 5.1.3 # Managed by waf
    DESCRIPTION "a meta assertion library focused on high compatibility"
    HOMEPAGE_URL "https://github.com/steinwurf/verify"
    LANGUAGES CXX)

if(MSVC)
    cmake_policy(SET CMP0091 NEW)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()

find_package(Python COMPONENTS Interpreter)

# Use waf to resolve dependencies
if(NOT DEFINED STEINWURF_RESOLVE)
    message(STATUS "Resolving dependencies...")
    execute_process(
    COMMAND ${Python_EXECUTABLE} waf resolve ${STEINWURF_RESOLVE_OPTIONS}
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    RESULT_VARIABLE STATUS)

    if(STATUS AND NOT STATUS EQUAL 0)
        message(FATAL_ERROR "Failed: ${STATUS}")
    endif()

    set(STEINWURF_RESOLVE "${CMAKE_CURRENT_SOURCE_DIR}/resolve_symlinks")
    set(STEINWURF_TOP_NAME ${PROJECT_NAME})
endif()

if(NOT DEFINED STEINWURF_VERIFY_USE_LIBASSERT)
    message(STATUS "STEINWURF_VERIFY_USE_LIBASSERT not defined, using YES")
    #if(WIN32)
    #    # Currently libassert doesn't seem to build against windows with our wrapping
    #    # https://github.com/steinwurf/libassert/pull/1
    #    set(STEINFWURF_VERIFY_USE_LIBASSERT NO)
    #    message(STATUS "STEINWURF_VERIFY_USE_LIBASSERT autodetected to NO due to WIN32 environment")
    #else()
    #    # MacOS / *UNIX-likes build correctly with libassert. Enable these by default.
    #    set(STEINWURF_VERIFY_USE_LIBASSERT YES)
    #    message(STATUS "STEINWURF_VERIFY_USE_LIBASSERT autodetected to YES")
    #endif()
    set(STEINWURF_VERIFY_USE_LIBASSERT YES)
endif()

add_library(${PROJECT_NAME} STATIC src/verify.cpp)
set_property(TARGET ${PROJECT_NAME} PROPERTY CXX_STANDARD 17)
set_property(TARGET ${PROJECT_NAME} PROPERTY CXX_EXTENSIONS OFF)
target_include_directories(${PROJECT_NAME} INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)
add_library(steinwurf::verify ALIAS ${PROJECT_NAME})

install(
    DIRECTORY ./include
    DESTINATION ${CMAKE_INSTALL_PREFIX}/include
    FILES_MATCHING
    PATTERN *.hpp)

if(STEINWURF_VERIFY_USE_LIBASSERT)
    if (NOT TARGET ZLIB::ZLIB)
        message(STATUS "Building zlib for libassert")
        set(ZLIB_BUILD_EXAMPLES NO)
        add_subdirectory("${STEINWURF_RESOLVE}/zlib-source" zlib EXCLUDE_FROM_ALL)
    endif()
    if (NOT TARGET libassert::assert)
        add_subdirectory("${STEINWURF_RESOLVE}/libassert-source" libassert EXCLUDE_FROM_ALL)
    endif()
    target_link_libraries(${PROJECT_NAME} PUBLIC libassert::assert)
    target_compile_definitions(${PROJECT_NAME} PUBLIC LIBASSERT_PREFIX_ASSERTIONS)
    target_compile_definitions(${PROJECT_NAME} PUBLIC STEINWURF_VERIFY_USE_LIBASSERT)
endif()

if (${PROJECT_NAME} STREQUAL ${STEINWURF_TOP_NAME})
    enable_testing()

    if (CMAKE_C_COMPILER_ID MATCHES "MSVC")
       # For Windows: Prevent overriding the parent project's compiler/linker
       # settings
       set(gtest_force_shared_crt
               ON
               CACHE BOOL "" FORCE)
    endif ()

    # Google Test dependency
    add_subdirectory("${STEINWURF_RESOLVE}/gtest-source" gtest_main EXCLUDE_FROM_ALL)
    # Define library
    file(GLOB_RECURSE verify_test_sources test/**/*.cpp)

    # Build test executable
    add_executable(verify_tests ${verify_test_sources})
    target_link_libraries(verify_tests PUBLIC steinwurf::verify)
    target_link_libraries(verify_tests PUBLIC gtest_main)

    # Make sure we compile with C++17 and do not use compiler specific extensions
    set_property(TARGET verify_tests PROPERTY CXX_STANDARD 17)
    set_property(TARGET verify_tests PROPERTY CXX_EXTENSIONS OFF)

    if (MSVC)
        add_compile_options(/W4)
        # Make Release builds explicitly keep NDEBUG unset.
        string(REGEX REPLACE "/DNDEBUG" "" CMAKE_C_FLAGS_RELEASE "${CMAKE_C_FLAGS_RELEASE}")
        string(REGEX REPLACE "/DNDEBUG" "" CMAKE_CXX_FLAGS_RELEASE "${CMAKE_C_FLAGS_RELEASE}")
    else()
        add_compile_options(-Wall -Wextra -Wpedantic -Werror)
        # Make Release builds explicitly keep NDEBUG unset.
        string(REGEX REPLACE "-DNDEBUG" "" CMAKE_C_FLAGS_RELEASE "${CMAKE_C_FLAGS_RELEASE}")
        string(REGEX REPLACE "-DNDEBUG" "" CMAKE_CXX_FLAGS_RELEASE "${CMAKE_C_FLAGS_RELEASE}")
    endif()

    add_test(verify_tests verify_tests)
endif()
