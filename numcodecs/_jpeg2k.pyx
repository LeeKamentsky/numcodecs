#distutils: language = c++

import logging
import numpy as np

cimport numpy as np
from openjpeg cimport *
from libc.string cimport memcpy
from libcpp.string cimport string
from libcpp.vector cimport vector
from cpython.bytes cimport PyBytes_FromStringAndSize

log = logging.getLogger(__name__)

ctypedef vector[char] memory_t
ctypedef vector[opj_image_cmptparm_t] cmptparms_t

cdef struct memstream_t:
    memory_t memory
    unsigned int ptr

cdef OPJ_SIZE_T stream_read(void *p_buffer,
                            OPJ_SIZE_T n_bytes,
                            void *obj) nogil:
    cdef:
        memstream_t *memory = <memstream_t *>obj
    if memory.ptr + n_bytes > memory.memory.size():
        if memory.ptr > memory.memory.size():
            with gil:
                log.warning("Buffer overflow: avail %d, asked %d" %
                            (memory.memory.size(), memory.ptr))
            return -1
        n_bytes = memory.memory.size() - memory.ptr
    memcpy(p_buffer, <const void *>(&memory.memory[memory.ptr]), n_bytes)
    memory.ptr = memory.ptr + n_bytes
    return n_bytes

cdef OPJ_SIZE_T stream_write(void *p_buffer,
                             OPJ_SIZE_T n_bytes,
                             void *obj) nogil:
    cdef:
        memstream_t *memory = <memstream_t *>obj
    if memory.ptr + n_bytes > memory.memory.size():
        memory.memory.resize(memory.ptr + n_bytes)
    memcpy(<void *>&memory.memory[memory.ptr], p_buffer, n_bytes)
    memory.ptr = memory.ptr + n_bytes
    return n_bytes

cdef OPJ_OFF_T stream_skip(OPJ_OFF_T n_bytes, void *obj) nogil:
    cdef:
        memstream_t *memory = <memstream_t *>obj
    memory.ptr = memory.ptr + n_bytes
    return n_bytes

cdef OPJ_OFF_T stream_seek(OPJ_OFF_T n_bytes, void *obj) nogil:
    cdef:
        memstream_t *memory = <memstream_t *>obj
    if n_bytes > memory.memory.size() or n_bytes < 0:
        with gil:
            log.debug("Seek past end of file: avail %d, asked %d" %
                      (memory.memory.size(), n_bytes))
        return OPJ_FALSE
    memory.ptr = n_bytes
    return OPJ_TRUE

cdef void stream_free(void *data) nogil:
    pass

cdef void error_callback(char* msg, void* client_data) with gil:
    log.error(msg)


cdef void warning_callback(char* msg, void* client_data) with gil:
    log.warning(msg)


cdef void info_callback(char* msg, void* client_data) with gil:
    message:bytes = msg
    log.debug("info callback: " + message.decode("utf8"))

cdef OPJ_BOOL write_tiled_image(
    opj_cparameters_t *parameters,
    opj_codec_t *codec,
    opj_image_t *image,
    opj_stream_t *stream,
    const unsigned char *data) nogil:
    cdef:
        uint32_t image_width = image.x1 - image.x0
        uint32_t image_height = image.y1 - image.y0
        uint32_t tile_width = parameters.cp_tdx
        uint32_t tile_height = parameters.cp_tdy
        uint32_t i, j, x0, y0, x1, y1, tileno, x, y
        uint32_t n_tiles_width = (image_width + tile_width - 1) / tile_width
        uint32_t n_tiles_height = (image_height + tile_height - 1) / tile_height
        uint32_t itemsize = (image.comps[0].prec + 7) // 8
        uint32_t tile_size
        const unsigned char *ptr
        vector[unsigned char] buffer
        unsigned char *bptr

    with gil:
        log.debug("Image width: %d" % image_width)
        log.debug("Image height: %d" % image_height)
        log.debug("Tile width: %d" % tile_width)
        log.debug("Tile height: %d" % tile_height)
        log.debug("Tile count: %d" % (n_tiles_width * n_tiles_height))
        log.debug("image.comps[0].prec = %d" % (image.comps[0].prec))
    buffer.resize(tile_width * tile_height * itemsize)
    tileno = 0
    for i in range(n_tiles_height):
        y0 = i * parameters.cp_tdy
        y1 = y0 + parameters.cp_tdy
        if y1 > image.y1  - image.y0:
            y1 = image.y1 - image.y0
        tile_height = y1 - y0
        for j in range(n_tiles_width):
            x0 = j * parameters.cp_tdx
            x1 = x0 + parameters.cp_tdx
            if x1 > image.x1  - image.x0:
                x1 = image.x1 - image.x0
            tile_width = x1 - x0
            tile_size = tile_width * tile_height * itemsize
            ptr = data + itemsize * (y0 * image_width + x0)
            #
            # Copy from image to buffer to get contiguous memory
            #
            bptr = &buffer[0]
            for y in range(tile_height):
                memcpy(bptr, ptr, tile_width * itemsize)
                ptr += image_width * itemsize
                bptr += tile_width * itemsize
            if not opj_write_tile(codec, tileno,
                                  <OPJ_BYTE *>&buffer[0], tile_size, stream):
                return OPJ_FALSE
            tileno += 1
    return OPJ_TRUE

def jpeg2k_encode(const unsigned char[::1] data,
                  cparameters,
                  cimage,
                  codec_format):
    """
    Encode an image using OpenJPEG.

    :param data: The image as a byte array
    :param cparameters: a CParameters object containing the compression
    parameters
    :param cimage: a CImage object containing the image and component
    parameters for the image
    :param codec_format: The codec to use from CodecFormat
    """
    cdef:
        opj_cparameters_t parameters
        string cp_comment
        const unsigned char[:] byte_string
        const unsigned char *data_ptr = <const unsigned char *>&data[0]
        memstream_t streambuffer
        OPJ_CODEC_FORMAT opj_codec_format
        OPJ_COLOR_SPACE opj_color_space
        opj_stream_t *stream = NULL
        opj_codec_t *codec = NULL
        opj_image_t *image = NULL
        cmptparms_t cmptparms
        OPJ_UINT32 data_size = <OPJ_UINT32>len(data)
        OPJ_BOOL result
    streambuffer.ptr = 0
    log.debug("Entering jpeg2k_encode")
    opj_set_default_encoder_parameters(&parameters)
    log.debug("Default encoder parameters set")
    parameters.tile_size_on = <OPJ_BOOL>(cparameters.tile_size_on)
    parameters.cp_tx0 = <int>(cparameters.cp_tx0)
    parameters.cp_ty0 = <int>(cparameters.cp_ty0)
    parameters.cp_tdx = <int>(cparameters.cp_tdx)
    parameters.cp_tdy = <int>(cparameters.cp_tdy)
    parameters.cp_disto_alloc = <int>(cparameters.cp_disto_alloc)
    parameters.cp_fixed_alloc = <int>(cparameters.cp_fixed_alloc)
    parameters.cp_fixed_quality = <int>(cparameters.cp_fixed_quality)
    if isinstance(cparameters.cp_comment, str):
        cp_comment = str(cparameters.cp_comment)
        log.debug("Comment is: %s" % cp_comment)
        parameters.cp_comment = <char *>cp_comment.c_str()
    else:
        log.debug("No comment")
        parameters.cp_comment = <char *>0
    parameters.csty = <int>cparameters.csty
    parameters.prog_order = <OPJ_PROG_ORDER>cparameters.prog_order.value
    if cparameters.pocs is None:
        log.debug("No pocs")
        #parameters.numpocs = <OPJ_UINT32>0
    else:
        parameters.numpocs = <OPJ_UINT32>len(cparameters.pocs)
        log.debug("%d pocs" % parameters.numpocs)
        for i, poc in enumerate(cparameters.pocs):
            parameters.POC[i].resno0 = <OPJ_UINT32>(poc.resno0)
            parameters.POC[i].compno0 = <OPJ_UINT32>(poc.compno0)
            parameters.POC[i].layno1 = <OPJ_UINT32>(poc.layno1)
            parameters.POC[i].resno1 = <OPJ_UINT32> (poc.resno1)
            parameters.POC[i].compno1 = <OPJ_UINT32> (poc.compno1)
            parameters.POC[i].layno0 = <OPJ_UINT32> (poc.layno0)
            parameters.POC[i].precno0 = <OPJ_UINT32>(poc.precno0)
            parameters.POC[i].precno1 = <OPJ_UINT32>(poc.precno1)
            parameters.POC[i].prg1 = <OPJ_PROG_ORDER>(poc.prg1.value)
            parameters.POC[i].prg = <OPJ_PROG_ORDER>(poc.prg.value)
            byte_string = poc.progorder
            for j in range(min(5, len(poc.progorder))):
                parameters.POC[i].progorder[j] = byte_string[j]
            parameters.POC[i].tile = <OPJ_UINT32>(poc.tile)
            parameters.POC[i].tx0 = <OPJ_UINT32>(poc.tx0)
            parameters.POC[i].tx1 = <OPJ_UINT32> (poc.tx1)
            parameters.POC[i].ty0 = <OPJ_UINT32> (poc.ty0)
            parameters.POC[i].ty1 = <OPJ_UINT32> (poc.ty1)
            parameters.POC[i].layS = <OPJ_UINT32>(poc.layS)
            parameters.POC[i].resS = <OPJ_UINT32>(poc.resS)
            parameters.POC[i].compS = <OPJ_UINT32>(poc.compS)
            parameters.POC[i].prcS = <OPJ_UINT32>(poc.prcS)
            parameters.POC[i].layE = <OPJ_UINT32> (poc.layE)
            parameters.POC[i].resE = <OPJ_UINT32> (poc.resE)
            parameters.POC[i].compE = <OPJ_UINT32> (poc.compE)
            parameters.POC[i].prcE = <OPJ_UINT32> (poc.prcE)
            parameters.POC[i].txS = <OPJ_UINT32> (poc.txS)
            parameters.POC[i].txE = <OPJ_UINT32> (poc.txE)
            parameters.POC[i].tyS = <OPJ_UINT32> (poc.tyS)
            parameters.POC[i].tyE = <OPJ_UINT32> (poc.tyE)
            parameters.POC[i].dx = <OPJ_UINT32>(poc.dx)
            parameters.POC[i].dy = <OPJ_UINT32> (poc.dy)
            parameters.POC[i].lay_t = <OPJ_UINT32> (poc.lay_t)
            parameters.POC[i].res_t = <OPJ_UINT32> (poc.res_t)
            parameters.POC[i].comp_t = <OPJ_UINT32> (poc.comp_t)
            parameters.POC[i].prc_t = <OPJ_UINT32> (poc.prc_t)
            parameters.POC[i].tx0_t = <OPJ_UINT32> (poc.tx0_t)
            parameters.POC[i].ty0_t = <OPJ_UINT32> (poc.ty0_t)
    parameters.tcp_numlayers = <int>(cparameters.tcp_numlayers)
    log.debug("tcp_numlayers = %d" % parameters.tcp_numlayers)
    if cparameters.tcp_rates is not None:
        for i, rate in enumerate(cparameters.tcp_rates):
            parameters.tcp_rates[i] = <int>rate
        log.debug("Setting rates to %s" %
                  str([parameters.tcp_rates[i] for i in
                       range(parameters.tcp_numlayers)]))
    if cparameters.tcp_distoratio is not None:
        for i, distoratio in enumerate(cparameters.tcp_distoratio):
            parameters.tcp_distoratio[i] = distoratio
        log.debug("Setting ratios to %s" %
                  str([parameters.tcp_distoratio[i] for i in
                   range(parameters.tcp_numlayers)]))
    parameters.numresolution = <int>(cparameters.numresolution)
    parameters.cblockw_init = <int>(cparameters.cblockw_init)
    parameters.cblockh_init = <int>(cparameters.cblockh_init)
    parameters.mode = <int>(cparameters.mode)
    parameters.irreversible = <int>(cparameters.irreversible)
    parameters.roi_compno = <int>(cparameters.roi_compno)
    parameters.roi_shift = <int>(cparameters.roi_shift)
    parameters.res_spec = <int>(cparameters.res_spec)
    if cparameters.prcw_init is not None:
        for i, prcw_init in enumerate(cparameters.prcw_init):
            parameters.prcw_init[i] = <int>prcw_init
    if cparameters.prch_init is not None:
        for i, prch_init in enumerate(cparameters.prch_init):
            parameters.prch_init[i] = prch_init
    # cp_cinema and cp_rsize deprecated
    parameters.max_comp_size = <int>(cparameters.max_comp_size)
    parameters.tp_on = <char>(cparameters.tp_on) # 0 or 1
    parameters.tp_flag = <char>(cparameters.tp_flag)
    # MCT == 2 not implemented
    parameters.tcp_mct = <char>(cparameters.tcp_mct)
    log.debug("tcp_mct = %d" % int(parameters.tcp_mct))
    parameters.jpip_on = <OPJ_BOOL>(cparameters.jpip_on)
    if parameters.jpip_on:
        log.debug("jpip_on = True")
    else:
        log.debug("jpip_on = False")
    # mct_data not implemented
    #parameters.mct_data = <void *>0
    parameters.max_cs_size = <int>(cparameters.max_cs_size)
    parameters.rsiz = <OPJ_UINT16>(cparameters.rsiz)
    log.debug("Caller parameters set")
    #
    # JPWL not supported
    #
    #parameters.jpwl_epc_on = <OPJ_BOOL>(cparameters.jpwl_epc_on)
    #parameters.jpwl_hprot_MH = <int>(cparameters.jpwl_hprot_MH)
    #parameters.jpwl_hprot_TPH_tileno = <int>(cparameters.jpwl_hprot_TPH_tileno)
    #parameters.jpwl_hprot_TPH = <int>(cparameters.jpwl_hprot_TPH)
    #parameters.jpwl_pprot_tileno = <int>(cparameters.jpwl_pprot_tileno)
    #parameters.jpwl_pprot_packno = <int>(cparameters.jpwl_pprot_packno)
    #parameters.jpwl_pprot = <int>(cparameters.jpwl_pprot)
    #parameters.jpwl_sens_size = <int>(cparameters.jpwl_sens_size)
    #parameters.jpwl_sens_addr = <int>(cparameters.jpwl_sens_addr)
    #parameters.jpwl_sens_range = <int>(cparameters.jpwl_sens_range)
    #parameters.jpwl_sens_MH = <int>(cparameters.jpwl_sens_MH)
    #parameters.jpwl_sens_TPH_tileno = <int>(cparameters.jpwl_sens_TPH_tileno)
    #parameters.jpwl_sens_TPH = <int>(cparameters.jpwl_sens_TPH)
    try:
        #
        # Hook the streambuffer to an OpenJPEG stream
        #
        stream = opj_stream_default_create(OPJ_FALSE)
        if stream == NULL:
            raise MemoryError("opj_stream_default_create failed")
        log.debug("Stream created")
        opj_stream_set_write_function(stream, <opj_stream_write_fn>stream_write)
        opj_stream_set_seek_function(stream, <opj_stream_seek_fn>stream_seek)
        opj_stream_set_skip_function(stream, <opj_stream_skip_fn>stream_skip)
        opj_stream_set_user_data(stream, <void *>&streambuffer,
                                 <opj_stream_free_user_data_fn> stream_free)
        log.debug("Stream hooks installed")
        #
        # Create the codec
        #
        opj_codec_format=<OPJ_CODEC_FORMAT>(codec_format.value)
        codec = opj_create_compress(opj_codec_format)
        if codec == NULL:
            raise MemoryError("opj_create_compress failed")
        log.debug("Codec created")
        opj_set_error_handler(codec, <opj_msg_callback>error_callback, NULL)
        opj_set_warning_handler(codec, <opj_msg_callback>warning_callback, NULL)
        if log.getEffectiveLevel() <= logging.DEBUG:
            opj_set_info_handler(codec, <opj_msg_callback>info_callback, NULL)
        log.debug("Codec logging hooks installed")
        #
        # Color space
        #
        opj_color_space = <OPJ_COLOR_SPACE>cimage.color_space.value
        #
        # Create the image
        #
        log.debug("%d image components" % len(cimage.cmptparms))
        cmptparms.resize(len(cimage.cmptparms))
        for i, cmptparm in enumerate(cimage.cmptparms):
            cmptparms[i].dx = <OPJ_UINT32> cmptparm.dx
            cmptparms[i].dy = <OPJ_UINT32> cmptparm.dy
            cmptparms[i].w = <OPJ_UINT32> cmptparm.w
            cmptparms[i].h = <OPJ_UINT32> cmptparm.h
            cmptparms[i].x0 = <OPJ_UINT32> cmptparm.x0
            cmptparms[i].y0 = <OPJ_UINT32> cmptparm.y0
            cmptparms[i].prec = <OPJ_UINT32> cmptparm.prec
            cmptparms[i].bpp = <OPJ_UINT32> cmptparm.bpp
            cmptparms[i].sgnd = <OPJ_UINT32> cmptparm.sgnd
        log.debug("Image components copied")
        if parameters.tile_size_on:
            log.debug("Creating tiled image")
            image = opj_image_tile_create(cmptparms.size(),
                                          <opj_image_cmptparm_t *>&cmptparms[0],
                                          opj_color_space)
        else:
            log.debug("Creating untiled image")
            image = opj_image_create(cmptparms.size(),
                                     <opj_image_cmptparm_t *>&cmptparms[0],
                                     opj_color_space)
        if image == NULL:
            raise MemoryError("Failed to create image")
        log.debug("opj_image_create succeeeded")
        image.x0 = <OPJ_UINT32>cimage.x0
        image.y0 = <OPJ_UINT32>cimage.y0
        image.x1 = <OPJ_UINT32>cimage.x1
        image.y1 = <OPJ_UINT32>cimage.y1
        log.debug("Image extents: x=%d:%d, y=%d:%d" % (
            image.x0, image.x1, image.y0, image.y1))
        image.color_space = opj_color_space
        image.numcomps = cmptparms.size()
        log.debug("Image parameters set")
        if not opj_setup_encoder(codec, &parameters, image):
            raise RuntimeError("Failed to setup encoder")
        log.debug("opj_setup_encoder completed successfully")
        if not opj_start_compress(codec, image, stream):
            raise RuntimeError("Failed to start compression")
        log.debug("Starting compression")
        with nogil:
            if parameters.tile_size_on:
                result = write_tiled_image(
                    &parameters,
                    codec,
                    image,
                    stream,
                    data_ptr)
            else:
                result = opj_write_tile(codec, 0, <OPJ_BYTE *>data_ptr,
                                        data_size, stream)
        if not result:
            raise RuntimeError("Failed to encode image")
        log.debug("Image written")
        result = opj_end_compress(codec, stream)
        if not result:
            raise RuntimeError("Failed to end compression")
        log.debug("Compression completed successfully")
        log.debug("Final size: %d" % (streambuffer.memory.size()))
        output = PyBytes_FromStringAndSize(
            &streambuffer.memory[0],
            streambuffer.memory.size())
        log.debug("Packaged Python object")
        return output

    finally:
        if stream != NULL:
            opj_stream_destroy(stream)
        log.debug("Stream destroyed")
        if codec != NULL:
            opj_destroy_codec(codec)
        log.debug("Codec destroyed")
        if image != NULL:
            opj_image_destroy(image)
        log.debug("Image destroyed")

def jpeg2k_decode(const unsigned char[::1] buffer, codec_format,
                  reduce=0,
                  layer=0,
                  components=None):
    """
    Decode a JPEG2000 image

    :param buffer: the compressed image
    :param codec_format: one of the CodecFormat enums, OPJ_CODEC_J2K or
    OPJ_CODEC_JP2.
    :param reduce: picks out the pyramid level, default is the lowest
    :param layer: picks out the quality layer, default is the best
    :param components: a sequence of integer indexes of the components
    to return. Defaults to all of them.
    """
    cdef:
        opj_dparameters_t parameters
        const unsigned char *data_ptr = <const unsigned char *>&buffer[0]
        memstream_t streambuffer
        OPJ_CODEC_FORMAT opj_codec_format
        opj_stream_t * stream = NULL
        opj_codec_t * codec = NULL
        opj_image_t * image = NULL
        OPJ_BOOL result
        vector[OPJ_UINT32] vcomponents
        char *output_ptr
        np.ndarray a
        uint8_t *ptr_bytes
        uint16_t *ptr_shorts
        uint32_t *ptr_ints
        int i, j
        int width, height
        int n_components

    log.debug("Entering jpeg2k_decode")
    try:
        #TODO - create a new kind of streambuffer that uses the data
        #       passed rather than copying to the vector.
        #
        streambuffer.ptr = 0
        streambuffer.memory.resize(<int>(len(buffer)))
        memcpy(&streambuffer.memory[0],
               data_ptr, len(buffer))
        log.debug("Stream buffer initialized. Size=%d" %
                  streambuffer.memory.size())
        stream = opj_stream_default_create(OPJ_TRUE)
        if stream == NULL:
            raise MemoryError("opj_stream_default_create failed")
        log.debug("Stream created")
        opj_stream_set_read_function(stream, <opj_stream_read_fn>stream_read)
        opj_stream_set_seek_function(stream, <opj_stream_seek_fn>stream_seek)
        opj_stream_set_skip_function(stream, <opj_stream_skip_fn>stream_skip)
        opj_stream_set_user_data(stream, <void *>&streambuffer,
                                 <opj_stream_free_user_data_fn> stream_free)
        opj_stream_set_user_data_length(stream, streambuffer.memory.size())
        log.debug("Stream hooks installed")

        opj_set_default_decoder_parameters(&parameters);
        parameters.cp_reduce = <OPJ_UINT32>reduce
        parameters.cp_layer = <OPJ_UINT32>layer
        log.debug("Decoder parameters set")

        opj_codec_format = <OPJ_CODEC_FORMAT>codec_format.value
        codec = opj_create_decompress(opj_codec_format)
        if codec == NULL:
            raise MemoryError("opj_create_decompress failed")
        log.debug("Codec created")
        opj_set_error_handler(codec, <opj_msg_callback>error_callback, NULL)
        opj_set_warning_handler(codec, <opj_msg_callback>warning_callback, NULL)
        if log.getEffectiveLevel() <= logging.DEBUG:
            opj_set_info_handler(codec, <opj_msg_callback>info_callback, NULL)
        log.debug("Codec logging hooks installed")

        result = opj_setup_decoder(codec, &parameters)
        if not result:
            raise RuntimeError("opj_setup_decoder failed")
        log.debug("Codec parameters set")

        result = opj_read_header(stream, codec, &image)
        if not result:
            raise RuntimeError("opj_read_header failed")
        log.debug("Header read")
        if components is not None:
            for component in components:
                vcomponents.push_back(<OPJ_UINT32>component)
            result = opj_set_decoded_components(
                codec,
                vcomponents.size(),
                &vcomponents[0],
                OPJ_FALSE)
            log.debug("Components chosen")
        result = opj_decode(codec, stream, image)
        if not result:
            raise RuntimeError("opj_decode failed")
        log.debug("Decode completed")
        result = opj_end_decompress(codec, stream)
        if not result:
            raise RuntimeError("opj_end_decompress failed")
        log.debug("Decompression completed")

        n_components = image.numcomps
        log.debug("# of components: %d" % n_components)
        signed = image.comps[0].sgnd
        kind = "i" if signed else "u"
        log.debug("Dtype kind: %s" % kind)
        prec = image.comps[0].prec
        log.debug("Precision: %d" % prec)
        height = image.comps[0].h
        log.debug("Height: %d" % height)
        width = image.comps[0].w
        log.debug("Width: %d" % width)
        if prec <= 8:
            itemsize = 1
        elif prec <= 16:
            itemsize = 2
        elif prec <= 32:
            itemsize = 4
        else:
            raise ValueError("Unsupported precision: %d" % prec)
        #
        # Check remaining components for consistency
        #
        for i in range(1, n_components):
            if image.comps[i].sgnd != signed or \
                image.comps[i].prec != prec or \
                image.comps[i].h != height or \
                image.comps[i].w != width:
                raise ValueError("Image components must be identical")
        dtype = "%s%d" % (kind, itemsize)
        if n_components == 1:
            a = np.empty((height, width), dtype)
            log.debug("Allocated %d x %d array" % (width, height))
            output_ptr = a.data
            with nogil:
                if itemsize == 1:
                    ptr_bytes = <uint8_t *> output_ptr
                    for i in range(width * height):
                        ptr_bytes[i] = <uint8_t>(image.comps[0].data[i])
                elif itemsize == 2:
                    ptr_shorts = <uint16_t *> a.data
                    for i in range(width * height):
                        ptr_shorts[i] = <uint16_t>(image.comps[0].data[i])
                else:
                    ptr_ints = <uint32_t *> a.data
                    for i in range(width * height):
                        ptr_ints[i] = <uint32_t>(image.comps[0].data[i])
            log.debug("Copied single channel array")
        else:
            a = np.zeros((height, width, n_components), dtype)
            log.debug("Allocated %d x %d x %d array" %
                      (width, height, n_components))
            with nogil:
                if itemsize == 1:
                    for j in range(n_components):
                        ptr_bytes = (<uint8_t *> a.data) + j
                        for i in range(width * height):
                            ptr_bytes[0] = <uint8_t>(image.comps[j].data[i])
                            ptr_bytes += n_components
                elif itemsize == 2:
                    for j in range(n_components):
                        ptr_shorts = (<uint16_t *> a.data) + j
                        for i in range(width * height):
                            ptr_shorts[0] = <uint16_t>(image.comps[j].data[i])
                            ptr_shorts += n_components
                else:
                    for j in range(n_components):
                        ptr_ints = (<uint32_t *> a.data) + j
                        for i in range(width * height):
                            ptr_ints[0] = <uint32_t>(image.comps[j].data[i])
                            ptr_ints += n_components
            log.debug("Copied multichannel array")
        return a
    finally:
        if stream != NULL:
            opj_stream_destroy(stream)
        log.debug("Stream destroyed")
        if codec != NULL:
            opj_destroy_codec(codec)
        log.debug("Codec destroyed")
        if image != NULL:
            opj_image_destroy(image)
        log.debug("Image destroyed")

