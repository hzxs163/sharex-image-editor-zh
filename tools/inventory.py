import sys, io, struct, time
import dnfile
from dncil.cil.body import CilMethodBody
from dncil.cil.body.reader import CilMethodBodyReaderBase
from pe_us import PE


class R(CilMethodBodyReaderBase):
    def __init__(self, pe, rva):
        self.pe = pe
        self.rva = rva

    def read(self, n):
        # pefile's get_data() takes an RVA, not a file offset
        try:
            d = self.pe.get_data(self.rva, n)
        except Exception:
            return b''
        if not d:
            raise IOError('eof at rva 0x%x' % self.rva)
        self.rva += len(d)
        return d

    def tell(self):
        return self.rva

    def seek(self, rva):
        self.rva = rva
        return rva


def parse_us(path):
    pex = PE(path)
    d = open(path, 'rb').read()
    off, size = pex.streams['#US']
    end = off + size
    entries = {}
    i = off
    while i < end:
        b = d[i]
        if b == 0:
            i += 1
            continue
        if b < 0x80:
            L, pl = b, 1
        elif b < 0xc0:
            L = ((b & 0x3f) << 8) | d[i + 1]
            pl = 2
        else:
            L = struct.unpack_from('<I', d, i)[0] & 0x0fffffff
            pl = 4
        if L < 1 or i + pl + L > end or (L - 1) % 2 != 0:
            break
        content = d[i + pl:i + pl + L - 1]
        try:
            s = content.decode('utf-16-le')
        except Exception:
            s = None
        entries[i - off] = (s, i, pl, L, content)
        i += pl + L
    return entries


def tok_name(md, token):
    try:
        t = getattr(token, 'table', None)
        idx = getattr(token, 'rid', None)
        if t is None:
            t = int(token) >> 24
            idx = int(token) & 0xFFFFFF
    except Exception:
        return None
    try:
        if t == 0x06 and idx - 1 < len(md.MethodDef.rows):
            r = md.MethodDef.rows[idx - 1]
            return 'M:' + (r.Name.value if hasattr(r.Name, 'value') else str(r.Name))
        if t == 0x0A and idx - 1 < len(md.MemberRef.rows):
            r = md.MemberRef.rows[idx - 1]
            nm = r.Name.value if hasattr(r.Name, 'value') else str(r.Name)
            cls = ''
            try:
                row = getattr(r.Class, 'row', None)
                if row is not None:
                    for attr in ('TypeName', 'Name'):
                        v = getattr(row, attr, None)
                        if v is not None:
                            cls = v.value if hasattr(v, 'value') else str(v)
                            break
            except Exception:
                pass
            return 'R:' + (cls + '.' if cls else '') + nm
        return 'T%02X:%d' % (t, idx)
    except Exception:
        return None


def main(path, report):
    t0 = time.time()
    pe = dnfile.dnPE(path)
    md = pe.net.mdtables
    us = parse_us(path)
    owners = {}
    for t in md.TypeDef.rows:
        tn = t.TypeName.value if hasattr(t.TypeName, 'value') else str(t.TypeName)
        for mi in (t.MethodList or []):
            try:
                owners[mi.row_index] = tn
            except Exception:
                pass
    rows = []
    n_ok = n_err = n_skip = 0
    errs = []
    raw = open(path, 'rb').read()
    for i, row in enumerate(md.MethodDef.rows):
        rva = row.Rva
        if i % 1500 == 0:
            print('progress', i, 'ok', n_ok, 'err', n_err, 'skip', n_skip, flush=True)
        if not rva:
            continue
        mname = row.Name.value if hasattr(row.Name, 'value') else str(row.Name)
        tname = owners.get(i, '?')
        try:
            o = pe.get_offset_from_rva(rva)
            h = raw[o]
            fmt = h & 7
            if fmt in (2, 6):
                csize = h >> 2
                hdr = 1
            elif fmt == 3:
                csize = struct.unpack_from('<I', raw, o + 4)[0]
                hdr = (struct.unpack_from('<H', raw, o)[0] >> 12) * 4
            else:
                n_skip += 1
                if len(errs) < 12:
                    errs.append('SKIPHDR %s %s rva=%x off=%x %s' % (tname, mname, rva, o, raw[o:o + 8].hex()))
                continue
            if csize <= 0 or csize > 2_000_000 or o + hdr + csize > len(raw):
                n_skip += 1
                if len(errs) < 12:
                    errs.append('SKIPSIZE %s %s rva=%x csize=%d' % (tname, mname, rva, csize))
                continue
        except Exception as ex:
            n_skip += 1
            continue
        try:
            body = CilMethodBody(R(pe, rva))
            n_ok += 1
        except Exception as e:
            n_err += 1
            if len(errs) < 12:
                errs.append('%s %s rva=%x %s' % (tname, mname, rva, e))
            continue
        ins = body.instructions
        for j, x in enumerate(ins):
            if x.opcode.name != 'ldstr':
                continue
            try:
                idx = x.operand.rid
            except Exception:
                try:
                    idx = int(x.operand) & 0xFFFFFF
                except Exception:
                    idx = -1
            e = us.get(idx)
            s = e[0] if e else None
            nxt = ''
            for k in range(j + 1, min(j + 6, len(ins))):
                o2 = ins[k].opcode.name
                if o2 in ('call', 'callvirt', 'newobj', 'ldtoken', 'calli'):
                    nxt = o2 + ' ' + (tok_name(md, ins[k].operand) or '')
                    break
            prv = ''
            for k in range(j - 1, max(j - 4, -1), -1):
                o2 = ins[k].opcode.name
                if o2 in ('call', 'callvirt', 'newobj', 'ldc.i4.1', 'nop'):
                    prv = o2 + ' ' + (tok_name(md, ins[k].operand) or '')
                    break
            rows.append((idx, s if s is not None else '<undecodable>', e[1] if e else 0, e[3] if e else 0, tname, mname, prv, nxt))
    with io.open(report, 'w', encoding='utf-8') as f:
        f.write('# %s\n# ok=%d err=%d us=%d ldstr=%d  (%.1fs)\n' % (path, n_ok, n_err, len(us), len(rows), time.time() - t0))
        for e in errs:
            f.write('# ERR ' + e + '\n')
        for idx, s, foff, L, tname, mname, prv, nxt in sorted(rows, key=lambda r: (r[4], r[5])):
            f.write('%d\t0x%x\tbytes=%d\tmaxchars=%d\t%s\t%s\t%s\tPREV[%s]\tNEXT[%s]\n' % (
                idx, foff, L, (L - 1) // 2, (tname or '')[:46], (mname or '')[:52],
                (s or '').replace('\n', '\\n'), prv, nxt))
    print('ok', n_ok, 'err', n_err, 'us', len(us), 'ldstr refs', len(rows), 'time', round(time.time() - t0, 1))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
