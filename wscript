#! /usr/bin/env python
# encoding: utf-8

import shutil
import os
import platform
import waflib
import hashlib
import os.path

from waflib import Build, Errors, Logs

APPNAME = "verify"
VERSION = "5.1.2"

def options(opt):
    opts = opt.add_option_group("Verify Options")
    opts.add_option(
        "--no-use-system-zlib",
        default=False,
        dest="no_use_system_zlib",
        action="store_true",
        help="Whether to not use system zlib when building verify",
    )
    opts.add_option(
        "--no-use-libassert",
        default=False,
        dest="no_use_libassert",
        action="store_true",
        help="Whether to not use libassert when building verify",
    )
    opts.add_option(
        "--force-use-libassert",
        default=False,
        dest="force_use_libassert",
        action="store_true",
        help="Whether to force the use of libassert regardless of build failures",
    )

def configure(conf):
    conf.set_cxx_std(17)

    if conf.options.force_use_libassert:
        # Allow overriding the default handling of --use-libassert/--no-use-libassert.
        conf.env.USE_LIBASSERT = True
    elif platform.system() == "Windows":
        # BUG: Disabled libassert on Windows when using Waf due to
        # dllimport related issues in assert.lib and cpptrace.lib.
        # See: https://github.com/steinwurf/verify/issues/3
        conf.env.USE_LIBASSERT = False
    elif conf.options.no_use_libassert:
        conf.env.USE_LIBASSERT = False
    else:
        conf.env.USE_LIBASSERT = True

    if conf.env.USE_LIBASSERT:
        if conf.options.no_use_system_zlib:
            conf.env.LIB_Z = []
        else:
            conf.check(lib="z", mandatory=False)

        if platform.system() == "Windows":
            conf.check(lib="dbghelp", mandatory=True)
        else:
            conf.check(lib="dl", mandatory=True)

        if conf.env.COMPILER_CXX == 'msvc':
            conf.env.CXXFLAGS += ['/DSTEINWURF_VERIFY_USE_LIBASSERT']
        else:
            conf.env.CXXFLAGS += ['-DSTEINWURF_VERIFY_USE_LIBASSERT']


def build(bld):
    bld.post_mode = Build.POST_LAZY

    use = []
    # Build libassert dependency if we are using it.
    if bld.env.USE_LIBASSERT:
        # Find the source directory for the external library
        src_dir = bld.dependency_node("libassert-source")

        # Declare the temporary build directory for the external library
        # it is best to keep it under the project build directory
        build_dir = bld.bldnode.make_node("libassert_build")

        # Declare the install directory for the external library
        install_dir = build_dir.make_node("install")

        # Declare the include directory for the external library
        include_dir = install_dir.make_node("include")

        lib_dir = install_dir.make_node("lib")
        lib64_dir = install_dir.make_node("lib64")

        zlib_src_dir = bld.dependency_node("zlib-source")
        zlib_build_dir = bld.bldnode.make_node("zlib_build")
        zlib_install_dir = zlib_build_dir.make_node("install")
        zlib_include_dir = zlib_install_dir.make_node("include")
        zlib_lib_dir = zlib_install_dir.make_node("lib")

        # Zlib is not always available, therefore we compile our own.
        # TODO: Rely on platforms that we can't compile zlib on, instead of just looking for where we don't have it?
        if not 'z' in bld.env.LIB_Z:
            #bld.stlib(
            #    features = 'c',
            #    cflags = ['/D_CRT_SECURE_NO_DEPRECATE', '/D_CRT_NONSTDC_NO_DEPRECATE'] if (platform.system() == "Windows") else [],
            #    source = zlib_src_dir.ant_glob('*.c'),
            #    export_includes = [zlib_src_dir.abspath()],
            #    includes = [zlib_src_dir.abspath()],
            #    target = 'z',
            #)
            bld(
                rule=CMakeBuildTask,
                target=zlib_build_dir.make_node("flag.lock"),
                install_dir=zlib_install_dir,
                source=zlib_src_dir,
            )


        # Build the external library through an external process
        bld(
            rule=CMakeBuildTask,
            target=build_dir.make_node("flag.lock"),
            install_dir=install_dir,
            source=src_dir,
        )

        # once it is done create a second build group
        bld.add_group()


        bld.read_stlib("assert", paths=[lib_dir, lib64_dir], export_includes=[include_dir])
        bld.read_stlib("cpptrace", paths=[lib_dir, lib64_dir], export_includes=[include_dir])

        use += ["assert", "cpptrace"];

        if platform.system() == "Windows":
            use += ["DBGHELP"]
        else:
            use += ["DL"]
            bld.read_stlib("dwarf", paths=[lib_dir, lib64_dir], export_includes=[include_dir])
            use += ["dwarf"]
            bld.read_stlib("zstd", paths=[lib_dir, lib64_dir], export_includes=[include_dir])
            use += ["zstd"]

        if 'z' in bld.env.LIB_Z:
            use += ["Z"]
        else:
            bld.read_stlib("z", paths=[zlib_lib_dir], export_includes=[zlib_include_dir])
            use += ["z"]

    bld.stlib(
        target="verify",
        features="cxx",
        source=["src/verify.cpp"],
        export_includes=[bld.path.find_dir("include")],
        includes=[bld.path.find_dir("include")],
        use=use,
    )

    if bld.is_toplevel():
        bld.program(
            features="cxx test",
            source=bld.path.ant_glob("test/**/*.cpp"),
            target="verify_tests",
            use=["verify", "gtest"],
        )


def prepare_release(ctx):
    # Rewrite versions
    with ctx.rewrite_file(filename="CMakeLists.txt") as f:
        pattern = r"VERSION \d+\.\d+\.\d+ # Managed by waf"
        replacement = "VERSION {} # Managed by waf".format(VERSION)

        f.regex_replace(pattern=pattern, replacement=replacement)


def CMakeBuildTask(task):
    CMAKE_BUILD_TYPE = "Release"
    if task.env["stored_options"]["cxx_debug"]:
        CMAKE_BUILD_TYPE = "Debug"

    # This is the directory where the external library will be installed the
    # task.outputs[0] is the flag file that will be created once the external
    # library is installed
    output_dir = task.outputs[0].parent

    # This is the directory where the external library source code is located
    source_dir = task.inputs[0]

    # The install dir is passed as a parameter to the task
    install_dir = task.generator.install_dir

    # remove the output directory if it exists
    shutil.rmtree(output_dir.abspath())

    # create the output directory
    os.makedirs(output_dir.abspath())

    flags = []
    # Our waf mkspec hardcodes the windows runtime to be mutlithreaded static i.e. /MT
    # so we need to pass this to cmake as well so that it can link properly
    # See https://cmake.org/cmake/help/latest/prop_tgt/MSVC_RUNTIME_LIBRARY.html
    if platform.system() == "Windows":
        flags.append("-DCMAKE_POLICY_DEFAULT_CMP0091:STRING=NEW")
        if CMAKE_BUILD_TYPE == "Debug":
            flags.append("-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreadedDebug")
        elif CMAKE_BUILD_TYPE == "Release":
            flags.append("-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded")
        # For 32 bit builds we need to pass -A Win32 for cross compiling with mkspec
        if task.env["DEST_CPU"] == "x86":
            flags.append("-A Win32")

    # cmake flags
    flags += [
        f"-DCMAKE_BUILD_TYPE={CMAKE_BUILD_TYPE}",
        f"-DCMAKE_INSTALL_PREFIX={install_dir}",
        f"-DZLIB_COMPAT=YES",
        f"-DZLIB_ENABLE_TESTS=NO",
        f"-DZLIBNG_ENABLE_TESTS=NO",
    ]
    flags = " ".join(flags)

    # Run all commands in the output directory
    cwd = output_dir.abspath()

    try:
        task.generator.bld.cmd_and_log(
            f"cmake {flags} -S {source_dir}", cwd=cwd, quiet=0, output=0
        )
        task.generator.bld.cmd_and_log(
            f"cmake --build . --parallel --config {CMAKE_BUILD_TYPE}",
            cwd=cwd,
            quiet=0,
            output=0,
        )

        task.generator.bld.cmd_and_log(
            f"cmake --install . --prefix {install_dir} --config {CMAKE_BUILD_TYPE}",
            cwd=cwd,
            quiet=0,
            output=0,
        )

    except Errors.WafError as e:
        Logs.error(e.stderr)
        return -1

    Logs.info(f"Installed lib to {output_dir}")

    # write a lock file so that a rebuild occurs if files are removed manually
    task.outputs[0].write("ok")
