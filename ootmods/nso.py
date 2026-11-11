"""Read and write Switch NSO code modules."""
import hashlib
import struct

PAGE = 0x1000


class NsoError(Exception):
    pass


def page_up(n):
    return (n + PAGE - 1) & ~(PAGE - 1)


def lz4_block(src, size):
    """Decompress one LZ4 block. Uses the lz4 package when it is installed, else plain Python."""
    try:
        import lz4.block
        return lz4.block.decompress(bytes(src), uncompressed_size=size)
    except ImportError:
        pass
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]; i += 1
        run = token >> 4
        if run == 15:
            while True:
                b = src[i]; i += 1
                run += b
                if b != 255:
                    break
        out += src[i:i + run]; i += run
        if i >= n:
            break
        back = src[i] | src[i + 1] << 8; i += 2
        run = token & 15
        if run == 15:
            while True:
                b = src[i]; i += 1
                run += b
                if b != 255:
                    break
        run += 4
        start = len(out) - back
        if back >= run:
            out += out[start:start + run]
        else:                               # overlapping copy: the pattern repeats
            piece = out[start:]
            out += (piece * (run // back + 1))[:run]
    if len(out) != size:
        raise ValueError('LZ4 data does not match its stated size')
    return bytes(out)


ZBIC_DLLS = []      # ZBIC readers already on this PC (a Hookshot Builder brings one): targets.py lists them


def zbic_open(blob, size):
    """Open ZBIC-packed bytes: with the zbic package when it is installed, else with a reader that is on the
    PC already."""
    blob = bytes(blob)
    try:
        import zbic
    except ImportError:
        zbic = None
    if zbic is not None:
        return zbic.decompress(blob)
    import ctypes
    for path in ZBIC_DLLS:
        try:
            fn = ctypes.CDLL(path).zbic_decompress
        except (OSError, AttributeError):       # not there, not for this Python, or not this library
            continue
        fn.restype = ctypes.c_longlong
        fn.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
        out = ctypes.create_string_buffer(size)
        got = fn(out, size, blob, len(blob))
        if got != size:
            raise ValueError('%d of %d bytes' % (got, size))
        return out.raw
    raise NsoError("the game's code in this dump is packed: reading it needs the zbic package "
                   "(python -m pip install zstandard zbic)")


def unpack(blob, size):
    """One packed segment of a module, opened. The dumps of Switch 2 games pack them with ZBIC, older ones
    with LZ4."""
    try:
        out = zbic_open(blob, size) if bytes(blob[:4]) == b'ZBIC' else lz4_block(blob, size)
    except NsoError:
        raise
    except Exception as e:                      # damaged data: the reader's own error, or a read past the end
        raise NsoError("a part of the game's code cannot be opened (%s)" % e)
    if len(out) != size:
        raise NsoError("a part of the game's code does not open to its stated size")
    return out


class Nso:
    """One module. seg[i] = (memory offset, bytes) for text, rodata, data."""

    def __init__(self, raw=None):
        self.seg = [None, None, None]
        self.bss = 0
        self.module_id = bytes(32)
        self.extents = bytes(0x18)          # .api_info, .dynstr, .dynsym (offset, size; rodata-relative)
        if raw is None:
            return
        if raw[:4] != b'NSO0':
            raise ValueError('not an NSO file')
        self._raw = raw
        self._flags = struct.unpack_from('<I', raw, 12)[0]
        self.bss = struct.unpack_from('<I', raw, 0x3c)[0]
        self.module_id = bytes(raw[0x40:0x60])
        self.extents = bytes(raw[0x88:0xa0])
        self._mem = [struct.unpack_from('<III', raw, 16 + i * 16) for i in range(3)]

    def _load(self, i):
        if self.seg[i] is None:
            off, mem, size = self._mem[i]
            csize = struct.unpack_from('<I', self._raw, 0x60 + i * 4)[0]
            blob = self._raw[off:off + csize]
            if self._flags >> i & 1:
                blob = unpack(blob, size)
            self.seg[i] = (mem, bytearray(blob))
        return self.seg[i]

    @property
    def text(self):
        return self._load(0)[1]

    def plain(self):
        """True when the code can be read straight from the file."""
        return not self._flags & 1

    def word(self, site):
        """The instruction at an address of the code."""
        if self.seg[0] is None and self.plain():
            off, mem, size = self._mem[0]
            return struct.unpack_from('<I', self._raw, off + site - mem)[0]
        return struct.unpack_from('<I', self.text, site)[0]

    @property
    def build_id(self):
        return self.module_id[:20].hex().upper()

    def size(self):
        """Bytes of address space the module takes once loaded."""
        if self.seg[2] is not None:
            mem, blob = self.seg[2]
            return page_up(mem + len(blob) + self.bss)
        off, mem, size = self._mem[2]
        return page_up(mem + size + self.bss)

    def image(self):
        """The module as it sits in memory (without bss)."""
        segs = [self._load(i) for i in range(3)]
        out = bytearray(segs[2][0] + len(segs[2][1]))
        for mem, blob in segs:
            out[mem:mem + len(blob)] = blob
        return out

    def build(self):
        """The module as an uncompressed NSO file."""
        segs = [self._load(i) if self.seg[i] is None else self.seg[i] for i in range(3)]
        hdr = bytearray(0x100)
        hdr[:4] = b'NSO0'
        struct.pack_into('<I', hdr, 12, 0x38)               # hashes present, nothing compressed
        body = bytearray()
        for i, (mem, blob) in enumerate(segs):
            struct.pack_into('<III', hdr, 16 + i * 16, 0x100 + len(body), mem, len(blob))
            struct.pack_into('<I', hdr, 0x60 + i * 4, len(blob))
            hdr[0xa0 + i * 32:0xc0 + i * 32] = hashlib.sha256(blob).digest()
            body += blob
        struct.pack_into('<I', hdr, 0x3c, self.bss)
        hdr[0x40:0x60] = self.module_id
        hdr[0x88:0xa0] = self.extents
        return bytes(hdr + body)


def load(path):
    with open(path, 'rb') as f:
        return Nso(f.read())


def data_file_offset(raw, mem_offset):
    """File offset of a data-segment address in an uncompressed NSO made by build() (None if not there)."""
    off, mem, size = struct.unpack_from('<III', raw, 16 + 2 * 16)
    if struct.unpack_from('<I', raw, 12)[0] & 4 or not mem <= mem_offset < mem + size:
        return None
    return off + mem_offset - mem


def rehash(raw):
    """Refresh the segment hashes of an uncompressed NSO after its bytes were edited in place."""
    raw = bytearray(raw)
    for i in range(3):
        off, mem, size = struct.unpack_from('<III', raw, 16 + i * 16)
        raw[0xa0 + i * 32:0xc0 + i * 32] = hashlib.sha256(raw[off:off + size]).digest()
    return bytes(raw)
