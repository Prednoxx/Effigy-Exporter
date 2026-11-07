"""Read KRAK DCX payloads with the Oodle 9 DLL supplied by Nightreign."""
import ctypes as c
import struct


class Oodle9:
    def __init__(self, path):
        dll = c.WinDLL(str(path))
        self.buffer_size = dll.OodleLZ_GetDecodeBufferSize
        self.buffer_size.argtypes = (c.c_int, c.c_ssize_t, c.c_int)
        self.buffer_size.restype = c.c_ssize_t
        self.decompress = dll.OodleLZ_Decompress
        self.decompress.argtypes = (
            c.c_char_p, c.c_ssize_t, c.c_void_p, c.c_ssize_t,
            c.c_int, c.c_int, c.c_int, c.c_void_p, c.c_ssize_t,
            c.c_void_p, c.c_void_p, c.c_void_p, c.c_ssize_t, c.c_int,
        )
        self.decompress.restype = c.c_ssize_t

    def unwrap(self, data):
        if data[:4] != b"DCX\0" or data[0x28:0x2C] != b"KRAK":
            return data
        if len(data) < 0x4C or data[0x18:0x1C] != b"DCS\0" or data[0x44:0x4C] != b"DCA\0\0\0\0\x08":
            raise ValueError("Invalid KRAK DCX header")
        size, compressed = struct.unpack_from(">II", data, 0x1C)
        if not 0 < compressed <= len(data) - 0x4C or not 0 < size <= 1 << 30:
            raise ValueError("Invalid KRAK payload size")

        # Oodle 9 takes a compressor selector before the output length.
        capacity = self.buffer_size(-1, size, 1)
        if capacity < size or capacity > size + (1 << 20):
            raise ValueError("Invalid Oodle output buffer size")
        output = c.create_string_buffer(capacity)
        count = self.decompress(
            data[0x4C:0x4C + compressed], compressed, output, size,
            1, 0, 0, None, 0, None, None, None, 0, 3,
        )
        if count != size:
            raise ValueError("KRAK output does not match the DCX size")
        return output[:size]
