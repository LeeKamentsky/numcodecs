import itertools


import numpy as np
import pytest

try:
    from numcodecs.jpeg2000 import JPEG2000
except ImportError: # pragma: no cover
    pytest.skip(
        "numcodecs.jpeg2000 not available",
        allow_module_level=True
    )
from numcodecs.tests.common import (check_encode_decode, check_config, check_repr,
                                    check_backwards_compatibility,
                                    check_err_decode_object_buffer,
                                    check_err_encode_object_buffer)


codecs = [
    JPEG2000()
]


# mix of dtypes: 8-bit integer, 16-bit integer
# mix of shapes: 1D, 2D, 3D
# mix of orders: C, F
arrays = [
    np.arange(255, dtype='u1'),
    np.arange(1000, dtype='u2'),
    np.random.randint(0, 255, size=(30, 40), dtype='u1'),     # 2d
    np.random.randint(0, 4096, size=(41, 29), dtype='u2'),
    np.random.randint(0, 255, size=(21, 22, 23), dtype='u1'), # 3d
    np.asfortranarray(0, 255, size=(30, 40), dtype='u1'),     # fortran
    # Non contiguous
    np.random.randint(0, 255, size=(100, 100), dtype='u1')[25:74, 30:50]
]


# Disallowed types
disallowed_types = [
    ['foo', 'bar', 'baz'], # list
    'foo', # string
    np.arange(-100, 100).astype('i8'),
    np.arange(-100, 100).astype('i16'),
    np.arange(-100, 100).astype('i32'),
    np.arange(-100, 100).astype('i64'),
    np.arange(-100, 100).astype('u32'),
    np.arange(-100, 100).astype('u64'),
    np.linspace(0, 100, 200).astype('f32'),
    np.linspace(0, 100, 200).astype('f64'),
    np.linspace(0, 100, 200).astype('f128'),
    np.random.randint(0, 2 ** 60, size=1000, dtype='u8').view('M8[ns]')
]

def test_encode_decode():
    for arr, codec in itertools.product(arrays, codecs):
        check_encode_decode(arr, codec)


def test_config():
    codec = JPEG2000()
    check_config(codec)


def test_repr():
    check_repr("JPEG2000()")


def test_eq():
    assert JPEG2000() == JPEG2000()
    assert not JPEG2000() != JPEG2000()
#    assert Zlib(1) == Zlib(1)
#    assert Zlib(1) != Zlib(9)
#    assert Zlib() != 'foo'
#    assert 'foo' != Zlib()
#    assert not Zlib() == 'foo'


def test_backwards_compatibility():
    check_backwards_compatibility(JPEG2000.codec_id, arrays, codecs)


def test_err_decode_object_buffer():
    check_err_decode_object_buffer(JPEG2000())


def test_err_encode_object_buffer():
    check_err_encode_object_buffer(JPEG2000())


def test_err_encode_disallowed():
    for data in disallowed_types:
        for codec in codecs:
            with pytest.raises(TypeError):
                codec.encode(data)

