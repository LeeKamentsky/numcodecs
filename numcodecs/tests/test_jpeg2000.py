import itertools
import sys
import traceback

import numpy as np
import pytest

import logging
logging.basicConfig(level=logging.DEBUG)
logging.getLogger().info("Hello, world")

try:
    from numcodecs.jpeg2000 import JPEG2000
except ImportError: # pragma: no cover
    pytest.skip(
        "numcodecs.jpeg2000 not available",
        allow_module_level=True
    )
from numcodecs.tests.common import (check_config, check_repr,
                                    compare_arrays,
                                    check_backwards_compatibility,
                                    check_err_decode_object_buffer,
                                    check_err_encode_object_buffer)


codecs = [
    JPEG2000()
]

r = np.random.RandomState(1234)
# mix of dtypes: 8-bit integer, 16-bit integer
# mix of shapes: 1D, 2D, 3D
# mix of orders: C, F
arrays = [
    (r.randint(0, 255, size=(256, 256), dtype='u1'),
     "vanilla"),
    (r.randint(0, 255, size=(32, 40), dtype='u1'),
     "2d-uint8"),
    (r.randint(0, 4096, size=(41, 33), dtype='u2'),
     "2d-uint16"),
    (r.randint(-127, 128, size=(32, 40), dtype='i1'),
     "2d-int8"),
    (r.randint(-2048, 2048, size=(32, 40), dtype='i2'),
     "2d-int16"),
    (r.randint(0, 255, size=(64, 64, 3), dtype='u1'),
     "color-2d"),
    #
    # NB: if last dimension is less than 32, OpenJPEG may run into a bug
    #     described here: https://github.com/uclouvain/openjpeg/issues/215
    (r.randint(0, 255, size=(21, 32, 32), dtype='u1'),
     "3d"),
    (r.randint(0, 255, size=(5, 21, 32, 32), dtype='u1'),
     "4d")
]


# Disallowed types
disallowed_types = [
    ['foo', 'bar', 'baz'], # list
    'foo', # string
    np.random.randint(0, 2 ** 60, size=(64, 64), dtype='u8').view('M8[ns]'),
    np.asfortranarray(np.random.randint(0, 255, size=(30, 40), dtype='u1')),
    # Non contiguous
    np.random.randint(0, 255, size=(100, 100), dtype='u1')[25:74, 30:50]
]

def test_encode_decode():
    for (arr, name), codec in itertools.product(arrays, codecs):
        #
        # Bytes and bytearrays not allowed, only numpy
        #
        try:
            enc = codec.encode(arr)
            dec = codec.decode(enc)
            compare_arrays(arr, dec)

            out = np.empty_like(arr)
            codec.decode(enc, out=out)
            compare_arrays(arr, dec)
        except:
            print("Error on array %s" % name, file=sys.stderr)
            traceback.print_exc()
            raise


def test_config():
    codec = JPEG2000()
    check_config(codec)


def test_repr():
    check_repr("JPEG2000(rate=0, snr=80)")


def test_eq():
    assert JPEG2000() == JPEG2000()
    assert not JPEG2000() != JPEG2000()
#    assert Zlib(1) == Zlib(1)
#    assert Zlib(1) != Zlib(9)
#    assert Zlib() != 'foo'
#    assert 'foo' != Zlib()
#    assert not Zlib() == 'foo'


def test_backwards_compatibility():
    check_backwards_compatibility(JPEG2000.codec_id, [a[0] for a in arrays],
                                  codecs)


def test_err_encode_object_buffer():
    check_err_encode_object_buffer(JPEG2000())


def test_err_encode_disallowed():
    for data in disallowed_types:
        for codec in codecs:
            with pytest.raises(TypeError):
                codec.encode(data)

