import enum
import logging
import typing

import numpy as np

from .abc import Codec
from .compat import ensure_ndarray, ensure_contiguous_ndarray
from ._jpeg2k import jpeg2k_encode, jpeg2k_decode
import numcodecs._jpeg2k
logging.getLogger(numcodecs._jpeg2k.__name__).setLevel(logging.DEBUG)
#
# These are headers for JP2 and J2K
#
JP2_RFC3745_MAGIC = b"\x00\x00\x00\x0c\x6a\x50\x20\x20\x0d\x0a\x87\x0a"
JP2_MAGIC = b"\x0d\x0a\x87\x0a"
J2K_CODESTREAM_MAGIC = b"\xff\x4f\xff\x51"


class ProgOrder(enum.Enum):
    OPJ_LRCP = 0 # ** < layer - resolution - component - precinct order
    OPJ_RLCP = 1 # ** < resolution - layer - component - precinct order
    OPJ_RPCL = 2 # ** < resolution - precinct - component - layer order *
    OPJ_PCRL = 3 # ** < precinct - component - resolution - layer order *
    OPJ_CPRL = 4  #** < component - precinct - resolution - layer order


class CodecFormat(enum.Enum):
    OPJ_CODEC_J2K  = 0     #< JPEG-2000 codestream : read/write
    OPJ_CODEC_JPT  = 1     #< JPT-stream (JPEG 2000, JPIP) : read only
    OPJ_CODEC_JP2  = 2     #< JP2 file format : read/write
    OPJ_CODEC_JPP  = 3     #< JPP-stream (JPEG 2000, JPIP) : to be coded
    OPJ_CODEC_JPX  = 4      #< JPX file format (JPEG 2000 Part-2) : to be coded

    @staticmethod
    def get_codec_format(buf:bytearray):
        if buf[:len(JP2_RFC3745_MAGIC)] == JP2_RFC3745_MAGIC:
            return CodecFormat.OPJ_CODEC_JP2
        if buf[:len(JP2_MAGIC)] == JP2_MAGIC:
            return CodecFormat.OPJ_CODEC_JP2
        if buf[:len(J2K_CODESTREAM_MAGIC)] == J2K_CODESTREAM_MAGIC:
            return CodecFormat.OPJ_CODEC_J2K
        raise ValueError("Invalid JPEG2000 header")


class ColorSpace(enum.Enum):
    OPJ_CLRSPC_UNSPECIFIED = 0 # not specified in the codestream
    OPJ_CLRSPC_SRGB = 1        # sRGB
    OPJ_CLRSPC_GRAY = 2        # grayscale
    OPJ_CLRSPC_SYCC = 3        # YUV
    OPJ_CLRSPC_EYCC = 4        # YCC
    OPJ_CLRSPC_CMYK = 5         # CMYK

class JPEG2000CParameters:
    """
    This follows the structure, opj_cparameters, from openjpeg.h
    """
    def __init__(self):
        self.tile_size_on = False
        self.cp_tx0 = 0
        self.cp_ty0 = 0
        self.cp_tdx = 0
        self.cp_tdy = 0
        self.cp_disto_alloc = 1
        self.cp_fixed_alloc = 0
        self.cp_fixed_quality = 0
        self.cp_comment = None
        self.csty = 0
        self.prog_order = ProgOrder.OPJ_LRCP
        self.pocs = None
        self.numpocs = 0
        self.tcp_numlayers = 1
        # Default is lossless.
        self.tcp_rates = [ 0.0 ]
        self.tcp_distoratio = [ 0.0 ]
        # OPJ_COMP_ARAM_DEFAULT_NUMRESOLUTION = 6
        # but for our codec, we would never use any but the first
        self.numresolution = 1
        # OPJ_COMP_PARAM_DEFAULT_CBLOCKW = 64
        self.cblockw_init = 64
        self.cblockh_init = 64
        self.mode = 0
        self.irreversible = 0
        self.roi_compno = -1
        self.roi_shift = 0
        self.res_spec = 0
        self.prcw_init = None
        self.prch_init = None
        self.image_offset_x0 = 0
        self.image_offset_y0 = 0
        self.subsampling_dx = 1
        self.subsampling_dy = 1
        self.decod_format = -1
        self.cod_format = -1
        self.max_comp_size = 0
        self.tp_on = 0
        self.tp_flag = 0
        self.tcp_mct = 0
        self.jpip_on = False
        self.mct_data = None
        self.max_cs_size = 0
        self.rsiz = 0


    def set_rates(self, rates:typing.Sequence[float]):
        """
        Set up to use compression rates for the layers.

        :param rates: A sequence of decreasing rates for
        subsequent layers. A rate of 0 at the end indicates
        lossless compression
        """
        self.cp_disto_alloc = 1
        self.cp_fixed_quality = 0
        self.tcp_rates = rates
        self.tcp_numlayers = len(rates)
        if rates[-1] == 0:
            self.irreversible = 0
        else:
            self.irreversible = 1
        self.tcp_distoratio = None

    def set_psnrs(self, psnrs:typing.Sequence[float]):
        """
        Set up to use signal-to-noise ratios for the layers.
        :psnrs: a sequence of increasing signal to noise ratios
        in DB. A zero at the end of the list signifies lossless
        compression.
        """
        self.cp_disto_alloc = 0
        self.cp_fixed_quality = 1
        self.tcp_distoratio = psnrs
        self.tcp_numlayers = len(psnrs)
        if psnrs[-1] == 0:
            self.irreversible = 0
        else:
            self.irreversible = 1
        self.tcp_rates = None


class CImageComptParm:
    """
    This follows opj_image_comptparm from openjpeg.h
    """
    def __init__(self, a:np.ndarray):
        """
        Initialize a component from a numpy array

        :param a: a 2D array. We get the height, width and data
        type-related parameters from this array.
        """
        assert a.ndim == 2, "Array must be 2D"
        assert a.dtype.kind in ("u", "i"), "Array must be integer type"
        self.dx = 1
        self.dy = 1
        self.x0 = 0
        self.y0 = 0
        self.h = a.shape[-2]
        self.w = a.shape[-1]
        self.sgnd = 1 if a.dtype.kind == "i" else 0
        self.prec = a.dtype.itemsize * 8
        self.bpp = self.prec

class CImage:
    """
    This follows opj_image from openjpeg.h
    """

    def __init__(self, components:typing.Sequence[CImageComptParm]):
        self.x0 = 0
        self.x1 = 0
        self.y0 = 0
        self.y1 = 0
        self.numcomps = len(components)
        self.cmptparms = components
        self.color_space = ColorSpace.OPJ_CLRSPC_GRAY


class JPEG2000(Codec):
    """
    Codec providing JPEG2000 encoding via the OpenJPEG library

    Parameters
    ----------
    snr: Signal to noise ratio in DB. Valid values are positive floating
    point numbers where lower numbers result in more compression and more
    data loss.
    rate: Compression rate in N-fold (e.g. rate=10 is a 10-fold compression
    resulting in an image size that is 1/10 of the original data. Setting
    the rate will use lossy compression.

    If snr and rate is zero or not specified, lossless compression will be
    used.
    """

    codec_id = "jpeg2000"

    def __init__(self, snr=0, rate=0):
        if snr > 0 and rate > 0:
            raise ValueError('snr or rate can be specified but not both')
        if snr < 0:
            raise ValueError('snr must be positive')
        if rate < 0:
            raise ValueError('rate must be positive')
        self.snr = snr
        self.rate = rate

    def encode(self, buf):
        buf = ensure_ndarray(buf)
        if not buf.flags.c_contiguous:
            raise TypeError('an array with contiguous memory is required')

        if buf.dtype.kind not in "iu":
            raise TypeError(
                'JPEG2000 only supports integer arrays')
        if buf.itemsize > 4:
            raise TypeError(
                'JPEG2000 does not support 64-bit integers'
            )
        params = JPEG2000CParameters()
        if self.snr > 0:
            params.set_psnrs([self.snr])
        elif self.rate > 0:
            params.set_rates([self.rate])
        if buf.ndim == 2:
            image = CImage(
                [CImageComptParm(buf)]
            )
            image.x1 = params.cp_tdx = buf.shape[1]
            image.y1 = params.cp_tdy = buf.shape[0]
        elif buf.ndim == 3 and buf.shape[2] in (3, 4):
            # Color image - encode as 3 or 4 components
            # TODO: avoid memory copy implicit in np.ascontiguousarray
            buf = np.ascontiguousarray(buf.transpose(2, 0, 1))
            image = CImage(
                [CImageComptParm(b)
                 for i, b in enumerate(buf)]
            )
            image.x1 = params.cp_tdx = buf.shape[2]
            image.y1 = params.cp_tdy = buf.shape[1]
            image.color_space = ColorSpace.OPJ_CLRSPC_SRGB
        else:
            # For 3+ dimensions, create tiles for all but last 2 dimensions
            #
            # Note that there's no handling of color images here
            #
            params.cp_tdx = buf.shape[-1]
            params.cp_tdy = buf.shape[-2]
            buf = self.reshape_buf(buf)
            params.tile_size_on = True
            image = CImage([CImageComptParm(buf)])
            image.x1 = buf.shape[1]
            image.y1 = buf.shape[0]
        return jpeg2k_encode(np.frombuffer(buf.data, np.uint8), params, image,
                             CodecFormat.OPJ_CODEC_J2K)

    def reshape_buf(self, buf):
        if buf.ndim == 1:
            raise ValueError(
                'JPEG2000 only supports arrays of 2 or more dimensions.')
        elif buf.ndim > 2:
            # Ravel all indices prior to last
            buf = buf.reshape(-1, buf.shape[-1])
        return buf

    def decode(self, buf, out=None):
        # TODO: take advantage of the output buffer if possible
        codec_format = CodecFormat.get_codec_format(buf)
        result = jpeg2k_decode(buf, codec_format)
        if out is not None:
            out.flatten()[:] = result.flatten()[:]
        return result.flatten()


    def get_config(self):
        return dict(
            id=JPEG2000.codec_id,
            snr=self.snr,
            rate=self.rate
        )

    @classmethod
    def from_config(cls, config):
        return JPEG2000(snr=config["snr"], rate=config["rate"])



