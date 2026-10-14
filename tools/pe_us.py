import struct, sys, io, os

class PE:
    def __init__(self, path):
        self.data = open(path, 'rb').read()
        d = self.data
        assert d[:2] == b'MZ'
        pe_off = struct.unpack_from('<I', d, 0x3c)[0]
        assert d[pe_off:pe_off+4] == b'PE\x00\x00'
        coff = pe_off + 4
        self.nsections = struct.unpack_from('<H', d, coff + 2)[0]
        self.sizeof_optional = struct.unpack_from('<H', d, coff + 16)[0]
        opt_off = coff + 20
        magic = struct.unpack_from('<H', d, opt_off)[0]
        self.pe32plus = (magic == 0x20b)
        # data directories
        dd_off = opt_off + (112 if self.pe32plus else 96)
        cli_rva, cli_size = struct.unpack_from('<II', d, dd_off + 14*8)
        self.sections = []
        st_off = opt_off + self.sizeof_optional
        for i in range(self.nsections):
            o = st_off + i*40
            name = d[o:o+8].rstrip(b'\x00').decode('ascii', 'replace')
            vsize, va, rawsize, raw = struct.unpack_from('<IIII', d, o+8)
            self.sections.append((name, va, vsize, raw, rawsize))
        def rva2off(rva):
            for name, va, vsize, raw, rawsize in self.sections:
                if va <= rva < va + max(vsize, rawsize):
                    return raw + (rva - va)
            raise Exception('bad rva %x' % rva)
        self.rva2off = rva2off
        cli_off = rva2off(cli_rva)
        self.meta_rva, self.meta_size = struct.unpack_from('<II', d, cli_off + 8)
        self.meta_off = rva2off(self.meta_rva)
        md = d[self.meta_off:]
        assert md[:4] == b'BSJB', md[:4]
        version_len = struct.unpack_from('<I', md, 12)[0]
        self.version = md[16:16+version_len].rstrip(b'\x00').decode('utf-8', 'replace')
        p = 16 + ((version_len + 3) // 4) * 4
        flags, streams = struct.unpack_from('<HH', md, p)
        p += 4
        self.streams = {}
        for i in range(streams):
            off, size = struct.unpack_from('<II', md, p)
            p += 8
            e = md.index(b'\x00', p)
            name = md[p:e].decode('utf-8', 'replace')
            p = e + 1
            while p % 4 != 0 and md[p] == 0:
                p += 1
            self.streams[name] = (self.meta_off + off, size)
        self.meta_end = self.meta_off + self.meta_size

def read_compressed_u(d, i):
    b = d[i]
    if b < 0x80:
        return b, 1
    if b < 0xc0:
        return ((b & 0x3f) << 8) | d[i+1], 2
    return struct.unpack_from('<I', d, i)[0] & 0x0fffffff, 4

def dump_us(path, out):
    pe = PE(path)
    if '#US' not in pe.streams:
        print('streams:', pe.streams)
        print('sections:', pe.sections)
        print('meta_off', pe.meta_off, 'meta_size', pe.meta_size)
        print('head', pe.data[pe.meta_off:pe.meta_off+64])
        raise SystemExit('no #US')
    off, size = pe.streams['#US']
    d = pe.data
    i = off
    entries = []
    end = off + size
    while i < end:
        if d[i] == 0:
            i += 1
            continue
        try:
            ln, pl = read_compressed_u(d, i)
        except IndexError:
            break
        if ln == 0 or ln % 2 != 0 or i + pl + ln + 1 > end:
            entries.append((i, None, 'INVALID len=%d' % ln))
            break
        raw = d[i+pl:i+pl+ln]
        term = d[i+pl+ln]
        try:
            s = raw.decode('utf-16-le')
        except Exception as e:
            s = repr(raw)
        entries.append((i - off, (s, ln, pl, term, raw)))
        i += pl + ln + 1
    with io.open(out, 'w', encoding='utf-8') as f:
        f.write('file %s size %d\n#US off %d size %d\n' % (os.path.basename(path), len(d), off, size))
        f.write('entries %d\n' % len(entries))
        for e in entries:
            idx = e[0]
            if e[1] is None:
                f.write('%d\t%s\n' % (idx, e[2]))
                continue
            s, ln, pl, term, raw = e
            f.write('%d\t%d\t%d\t%d\t%s\n' % (idx, ln, pl, term, s.replace('\n', '\\n').replace('\t', '\\t')))
    return pe, entries

if __name__ == '__main__':
    p = sys.argv[1]
    o = sys.argv[2]
    pe, entries = dump_us(p, o)
    print('streams:', {k: v[1] for k, v in pe.streams.items()})
    print('meta off/size', pe.meta_off, pe.meta_size, 'file size', len(pe.data))
    print('us entries', len(entries))
