from glob import glob
import os
from setuptools import setup, Extension
import cpuinfo
import pathlib
import sys
from distutils.errors import CCompilerError, DistutilsExecError, \
    DistutilsPlatformError
from distutils.command.build_ext import build_ext

try:
    from Cython.Build import cythonize
except ImportError:
    have_cython = False
else:
    have_cython = True

# determine CPU support for SSE2 and AVX2
cpu_info = cpuinfo.get_cpu_info()
flags = cpu_info.get('flags', [])
have_sse2 = 'sse2' in flags
have_avx2 = 'avx2' in flags
disable_sse2 = 'DISABLE_NUMCODECS_SSE2' in os.environ
disable_avx2 = 'DISABLE_NUMCODECS_AVX2' in os.environ

# setup common compile arguments
have_cflags = 'CFLAGS' in os.environ
base_compile_args = list()
if have_cflags:
    # respect compiler options set by user
    pass
elif os.name == 'posix':
    if disable_sse2:
        base_compile_args.append('-mno-sse2')
    elif have_sse2:
        base_compile_args.append('-msse2')
    if disable_avx2:
        base_compile_args.append('-mno-avx2')
    elif have_avx2:
        base_compile_args.append('-mavx2')
# On macOS, force libc++ in case the system tries to use `stdlibc++`.
# The latter is often absent from modern macOS systems.
if sys.platform == 'darwin':
    base_compile_args.append('-stdlib=libc++')


def info(*msg):
    kwargs = dict(file=sys.stdout)
    print('[numcodecs]', *msg, **kwargs)


def error(*msg):
    kwargs = dict(file=sys.stderr)
    print('[numcodecs]', *msg, **kwargs)


def blosc_extension():
    info('setting up Blosc extension')

    extra_compile_args = list(base_compile_args)
    define_macros = []

    # setup blosc sources
    blosc_sources = [f for f in glob('c-blosc/blosc/*.c')
                     if 'avx2' not in f and 'sse2' not in f]
    include_dirs = [os.path.join('c-blosc', 'blosc')]

    # add internal complibs
    blosc_sources += glob('c-blosc/internal-complibs/lz4*/*.c')
    blosc_sources += glob('c-blosc/internal-complibs/snappy*/*.cc')
    blosc_sources += glob('c-blosc/internal-complibs/zlib*/*.c')
    blosc_sources += glob('c-blosc/internal-complibs/zstd*/common/*.c')
    blosc_sources += glob('c-blosc/internal-complibs/zstd*/compress/*.c')
    blosc_sources += glob('c-blosc/internal-complibs/zstd*/decompress/*.c')
    blosc_sources += glob('c-blosc/internal-complibs/zstd*/dictBuilder/*.c')
    include_dirs += [d for d in glob('c-blosc/internal-complibs/*')
                     if os.path.isdir(d)]
    include_dirs += [d for d in glob('c-blosc/internal-complibs/*/*')
                     if os.path.isdir(d)]
    define_macros += [('HAVE_LZ4', 1),
                      ('HAVE_SNAPPY', 1),
                      ('HAVE_ZLIB', 1),
                      ('HAVE_ZSTD', 1)]
    # define_macros += [('CYTHON_TRACE', '1')]

    # SSE2
    if have_sse2 and not disable_sse2:
        info('compiling Blosc extension with SSE2 support')
        extra_compile_args.append('-DSHUFFLE_SSE2_ENABLED')
        blosc_sources += [f for f in glob('c-blosc/blosc/*.c') if 'sse2' in f]
        if os.name == 'nt':
            define_macros += [('__SSE2__', 1)]
    else:
        info('compiling Blosc extension without SSE2 support')

    # AVX2
    if have_avx2 and not disable_avx2:
        info('compiling Blosc extension with AVX2 support')
        extra_compile_args.append('-DSHUFFLE_AVX2_ENABLED')
        blosc_sources += [f for f in glob('c-blosc/blosc/*.c') if 'avx2' in f]
        if os.name == 'nt':
            define_macros += [('__AVX2__', 1)]
    else:
        info('compiling Blosc extension without AVX2 support')

    if have_cython:
        sources = ['numcodecs/blosc.pyx']
    else:
        sources = ['numcodecs/blosc.c']

    # define extension module
    extensions = [
        Extension('numcodecs.blosc',
                  sources=sources + blosc_sources,
                  include_dirs=include_dirs,
                  define_macros=define_macros,
                  extra_compile_args=extra_compile_args,
                  ),
    ]

    if have_cython:
        extensions = cythonize(extensions)

    return extensions


def zstd_extension():
    info('setting up Zstandard extension')

    zstd_sources = []
    extra_compile_args = list(base_compile_args)
    include_dirs = []
    define_macros = []

    # setup sources - use zstd bundled in blosc
    zstd_sources += glob('c-blosc/internal-complibs/zstd*/common/*.c')
    zstd_sources += glob('c-blosc/internal-complibs/zstd*/compress/*.c')
    zstd_sources += glob('c-blosc/internal-complibs/zstd*/decompress/*.c')
    zstd_sources += glob('c-blosc/internal-complibs/zstd*/dictBuilder/*.c')
    include_dirs += [d for d in glob('c-blosc/internal-complibs/zstd*')
                     if os.path.isdir(d)]
    include_dirs += [d for d in glob('c-blosc/internal-complibs/zstd*/*')
                     if os.path.isdir(d)]
    # define_macros += [('CYTHON_TRACE', '1')]

    if have_cython:
        sources = ['numcodecs/zstd.pyx']
    else:
        sources = ['numcodecs/zstd.c']

    # define extension module
    extensions = [
        Extension('numcodecs.zstd',
                  sources=sources + zstd_sources,
                  include_dirs=include_dirs,
                  define_macros=define_macros,
                  extra_compile_args=extra_compile_args,
                  ),
    ]

    if have_cython:
        extensions = cythonize(extensions)

    return extensions


def lz4_extension():
    info('setting up LZ4 extension')

    extra_compile_args = list(base_compile_args)
    define_macros = []

    # setup sources - use LZ4 bundled in blosc
    lz4_sources = glob('c-blosc/internal-complibs/lz4*/*.c')
    include_dirs = [d for d in glob('c-blosc/internal-complibs/lz4*') if os.path.isdir(d)]
    include_dirs += ['numcodecs']
    # define_macros += [('CYTHON_TRACE', '1')]

    if have_cython:
        sources = ['numcodecs/lz4.pyx']
    else:
        sources = ['numcodecs/lz4.c']

    # define extension module
    extensions = [
        Extension('numcodecs.lz4',
                  sources=sources + lz4_sources,
                  include_dirs=include_dirs,
                  define_macros=define_macros,
                  extra_compile_args=extra_compile_args,
                  ),
    ]

    if have_cython:
        extensions = cythonize(extensions)

    return extensions


def vlen_extension():
    info('setting up vlen extension')

    extra_compile_args = list(base_compile_args)
    define_macros = []

    # setup sources
    include_dirs = ['numcodecs']
    # define_macros += [('CYTHON_TRACE', '1')]

    if have_cython:
        sources = ['numcodecs/vlen.pyx']
    else:
        sources = ['numcodecs/vlen.c']

    # define extension module
    extensions = [
        Extension('numcodecs.vlen',
                  sources=sources,
                  include_dirs=include_dirs,
                  define_macros=define_macros,
                  extra_compile_args=extra_compile_args,
                  ),
    ]

    if have_cython:
        extensions = cythonize(extensions)

    return extensions


def compat_extension():
    info('setting up compat extension')

    extra_compile_args = list(base_compile_args)

    if have_cython:
        sources = ['numcodecs/compat_ext.pyx']
    else:
        sources = ['numcodecs/compat_ext.c']

    # define extension module
    extensions = [
        Extension('numcodecs.compat_ext',
                  sources=sources,
                  extra_compile_args=extra_compile_args),
    ]

    if have_cython:
        extensions = cythonize(extensions)

    return extensions


def jpeg2000_extension():
    info('Setting up JPEG 2000 extension')

    extra_compile_args = list(base_compile_args)

    # Test for presence and location of openjpeg.h
    openjpeg_libdir = 'OPENJPEG_LIBDIR'
    openjpeg_includedir = 'OPENJPEG_INCLUDEDIR'
    if openjpeg_libdir not in os.environ or \
       openjpeg_includedir not in os.environ:
        info('Not building JPEG2000: OPENJPEG_LIBDIR and OPENJPEG_INCLUDEDIR '
             'must be defined.')
        return []

    openjpeg_include_path = pathlib.Path(os.environ[openjpeg_includedir])
    openjpeg_lib_path = pathlib.Path(os.environ[openjpeg_libdir])
    if not openjpeg_include_path.exists():
        raise BuildFailed("OPENJPEG_INCLUDEDIR directory does not exist:" +
                          str(openjpeg_include_path))
    if not openjpeg_lib_path.exists():
        raise BuildFailed('OPENJPEG_LIBDIR directory does not exist' +
                          str(openjpeg_lib_path))
    #
    # Test for openjpeg-N.M/openjpeg.h
    #
    if not (openjpeg_include_path / 'openjpeg.h').exists():
        best = (0, 0)
        include_dir = None
        for subdir in openjpeg_include_path.glob('openjpeg-*/openjpeg.h'):
            try:
                majorminorstr = subdir.parent.name.split('-')[1]
                majorminor = tuple([int(_) for _ in majorminorstr.split(".")])
                if majorminor > best:
                    include_dir = os.fspath(subdir.parent)
                    best = majorminor
            except:
                pass
        if include_dir is None:
            raise BuildFailed('Could not find openjpeg.h')
    else:
        include_dir = os.fspath(openjpeg_include_path)

    include_dirs = [os.fspath(openjpeg_include_path), include_dir,
                    '3rdparty/openjpeg']
    if have_cython:
        sources = ['numcodecs/_jpeg2k.pyx']
    else:
        sources = ['numcodecs/_jpeg2k.cpp']
    extensions = [
        Extension(
            name='numcodecs._jpeg2k',
            sources=sources,
            include_dirs=include_dirs,
            extra_compile_args=extra_compile_args,
            libraries=['openjp2'],
            library_dirs=[os.fspath(openjpeg_lib_path)]
        )
    ]
    if have_cython:
        extensions = cythonize(extensions)
    return extensions


if sys.platform == 'win32':
    ext_errors = (CCompilerError, DistutilsExecError, DistutilsPlatformError,
                  IOError, ValueError)
else:
    ext_errors = (CCompilerError, DistutilsExecError, DistutilsPlatformError)


class BuildFailed(Exception):
    pass


class ve_build_ext(build_ext):
    # This class allows C extension building to fail.

    def run(self):
        try:
            build_ext.run(self)
        except DistutilsPlatformError as e:
            error(e)
            raise BuildFailed()

    def build_extension(self, ext):
        try:
            build_ext.build_extension(self, ext)
        except ext_errors as e:
            error(e)
            raise BuildFailed()

    def finalize_options(self):
        build_ext.finalize_options(self)
        # Prevent numpy from thinking it is still in its setup process:
        __builtins__.__NUMPY_SETUP__ = False
        import numpy
        self.include_dirs.append(numpy.get_include())


DESCRIPTION = ("A Python package providing buffer compression and "
               "transformation codecs for use in data storage and "
               "communication applications.")

with open('README.rst') as f:
    LONG_DESCRIPTION = f.read()


def run_setup(with_extensions):

    if with_extensions:
        ext_modules = (blosc_extension() + zstd_extension() + lz4_extension() +
                       compat_extension() + vlen_extension() +
                       jpeg2000_extension())
        cmdclass = dict(build_ext=ve_build_ext)
    else:
        ext_modules = []
        cmdclass = dict()

    setup(
        name='numcodecs',
        description=DESCRIPTION,
        long_description=LONG_DESCRIPTION,
        use_scm_version={
            'version_scheme': 'guess-next-dev',
            'local_scheme': 'dirty-tag',
            'write_to': 'numcodecs/version.py'
        },
        setup_requires=[
            'setuptools>18.0',
            'setuptools-scm>1.5.4'
        ],
        install_requires=[
            'numpy>=1.7',
        ],
        extras_require={
            'msgpack':  ["msgpack"],
        },
        ext_modules=ext_modules,
        cmdclass=cmdclass,
        package_dir={"": "."},
        python_requires=">=3.6, <4",
        packages=["numcodecs", "numcodecs.tests"],
        classifiers=[
            "Development Status :: 4 - Beta",
            "Intended Audience :: Developers",
            "Intended Audience :: Information Technology",
            "Intended Audience :: Science/Research",
            "License :: OSI Approved :: MIT License",
            "Programming Language :: Python",
            "Topic :: Software Development :: Libraries :: Python Modules",
            "Operating System :: Unix",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.6",
            "Programming Language :: Python :: 3.7",
            "Programming Language :: Python :: 3.8",
            "Programming Language :: Python :: 3.9",
        ],
        author='Alistair Miles',
        author_email='alimanfoo@googlemail.com',
        maintainer='Alistair Miles',
        maintainer_email='alimanfoo@googlemail.com',
        url='https://github.com/zarr-developers/numcodecs',
        license='MIT',
    )


if __name__ == '__main__':
    is_pypy = hasattr(sys, 'pypy_translation_info')
    with_extensions = not is_pypy and 'DISABLE_NUMCODECS_CEXT' not in os.environ
    run_setup(with_extensions)
