"""Bounded UNI PAniDataFile reader. No guessed tag skipping or script execution.

Tag layouts cross-checked with the local Gonptechan parts reader; rendering
and stage-script projection are deliberately separate from binary decoding.
"""
import struct


class FormatError(ValueError):
    pass


class Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def take(self, count):
        if count < 0 or self.offset + count > len(self.data):
            raise FormatError(f'truncated PAT at byte {self.offset:#x}, need {count}')
        result = self.data[self.offset:self.offset+count]
        self.offset += count
        return result

    def unpack(self, fmt):
        return struct.unpack('<'+fmt, self.take(struct.calcsize('<'+fmt)))

    def tag(self):
        return self.take(4).decode('ascii', errors='strict')

    def name(self):
        return self.take(self.unpack('B')[0]).decode('cp932')

    def properties(self, end, layouts):
        result = {}
        while True:
            tag = self.tag()
            if tag == end:
                return result
            if tag in {'PANA','PPNA'}:
                result[tag] = self.name()
            elif tag in layouts:
                result[tag] = self.unpack(layouts[tag])
            else:
                raise FormatError(f'unsupported PAT tag {tag!r} at {self.offset-4:#x}')


PART = {'PRXY':'2i','PRAL':'B','PRRV':'B','PRFL':'B','PRZM':'2f',
        'PRSP':'4B','PRAN':'f','PRA3':'4f','PRPR':'i','PRID':'i','PRCL':'4B'}
CUT = {'PPXY':'2i','PPCC':'2i','PPUV':'4i','PPWH':'2i','PPSS':'2i',
       'PPTE':'2h','PPCL':'i','PPPA':'i','PPGR':'i','PPTP':'i','PPVT':'i',
       'PPPP':'i','PPTX':'i','PPJP':'2i'}


def decompress(data, size):
    if not 0 <= size <= 256*1024*1024:
        raise FormatError('PAT texture exceeds decode limit')
    output = bytearray()
    r = Reader(data)
    while r.offset < len(data):
        value = r.unpack('B')[0]
        if value:
            output.append(value)
        else:
            value, count = r.unpack('2B')
            output.extend(bytes([value])*count)
        if len(output) > size:
            raise FormatError('PAT texture expansion exceeds declared size')
    if len(output) != size:
        raise FormatError('PAT texture expansion size mismatch')
    return bytes(output)


def texture(r):
    result = {}
    while True:
        tag = r.tag()
        if tag == 'PGED':
            return result
        if tag == 'PGNM':
            result['name'] = r.take(32).split(b'\0')[0].decode('cp932')
        elif tag in {'PGTP','PGTE'}:
            result[tag] = r.take(4)
        elif tag == 'PGT2':
            size, width, height = r.unpack('3I')
            kind = r.take(4)
            result.update(width=width,height=height,kind=kind)
            if not (0 < width <= 16384 and 0 < height <= 16384):
                raise FormatError('invalid PAT texture dimensions')
            expected = {b'DXT1':width*height//2+128,
                        b'DXT5':width*height+128,
                        struct.pack('<I',21):width*height*4+128}.get(kind)
            if expected is None:
                raise FormatError(f'unsupported texture encoding {kind!r}')
            if size == expected:
                r.take(8)
                dds = r.take(size)
            else:
                metadata = r.unpack('6I')
                packed_size, raw_size = metadata[4:]
                dds = decompress(r.take(packed_size),raw_size)
            if dds[:4] != b'DDS ' or len(dds) != expected:
                raise FormatError('invalid embedded DDS payload')
            result['dds'] = dds
        else:
            raise FormatError(f'unsupported texture tag {tag!r}')


def parse(path):
    data = path.read_bytes()
    if len(data) > 512*1024*1024:
        raise FormatError('PAT exceeds file decode limit')
    r = Reader(data)
    if r.take(32)[:12] != b'PAniDataFile' or r.tag() != '_STR':
        raise FormatError('not a UNI PAniDataFile')
    result = dict(parts={},cutouts={},textures={},shapes=[])
    while True:
        tag = r.tag()
        if tag == '_END':
            if r.offset != len(data):
                raise FormatError('trailing PAT data')
            return result
        if tag in {'P_ST','PPST','PGST'}:
            index = r.unpack('I')[0]
            if tag == 'P_ST':
                part = dict(name='',groups={})
                while True:
                    sub = r.tag()
                    if sub == 'P_ED':
                        break
                    if sub == 'PANA':
                        part['name'] = r.name()
                    elif sub == 'PRST':
                        group = r.unpack('I')[0]
                        part['groups'][group] = r.properties('PRED',PART)
                    else:
                        raise FormatError(f'unsupported part tag {sub!r}')
                result['parts'][index] = part
            elif tag == 'PPST':
                result['cutouts'][index] = r.properties('PPED',CUT)
            else:
                result['textures'][index] = texture(r)
        elif tag == 'VEST':
            count, stride = r.unpack('2I')
            if count > 65536 or not 1 <= stride <= 256:
                raise FormatError('invalid PAT shape table')
            result['shapes'] = [r.unpack(str(stride)+'I') for _ in range(count)]
            if r.tag() != 'VNST':
                raise FormatError('missing PAT shape names')
            result['shape_names'] = [r.take(32).split(b'\0')[0].decode('cp932') for _ in range(count)]
            if r.tag() != 'VEED':
                raise FormatError('missing PAT shape terminator')
        else:
            raise FormatError(f'unsupported top-level tag {tag!r} at {r.offset-4:#x}')
