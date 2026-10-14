"""Size-preserving in-place patcher for .NET #US (user string) heap entries.

Entry layout: [compressed length L][UTF-16LE payload (L-1 bytes)][flag byte].
Total entry size = prefix_bytes + L. We only shrink/pad, never grow, so every other
entry keeps its byte offset and all ldstr tokens remain valid.

Usage: python patch_us.py <dll> <dict.json> [--apply] [--allow allow.json]
  dict.json : {"English source": "中文翻译"}
"""
import json, sys, os, shutil, struct, argparse
try:  # the Windows console defaults to GBK; force UTF-8 so printing Chinese cannot abort the run
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from pe_us import PE


def enc_compact(n):
    if n < 0x80:
        return bytes([n])
    if n < 0x4000:
        return bytes([(n >> 8) | 0x80, n & 0xff])
    return struct.pack('<I', n | 0xC0000000)


def us_flag(chars):
    for ch in chars:
        o = ord(ch)
        if (o >> 8) & 0xff:
            return 1
        lo = o & 0xff
        if 0x01 <= lo <= 0x08 or 0x0E <= lo <= 0x1F or lo in (0x27, 0x2D, 0x7F):
            return 1
    return 0


def parse_us(data, us_off, us_size):
    end = us_off + us_size
    entries = {}
    i = us_off
    while i < end:
        b = data[i]
        if b == 0:
            i += 1
            continue
        if b < 0x80:
            L, pl = b, 1
        elif b < 0xc0:
            L = ((b & 0x3f) << 8) | data[i + 1]
            pl = 2
        else:
            L = struct.unpack_from('<I', data, i)[0] & 0x0fffffff
            pl = 4
        if L < 1 or i + pl + L > end or (L - 1) % 2 != 0:
            break
        payload = data[i + pl:i + pl + L - 1]
        entries[i - us_off] = dict(off=i, pl=pl, L=L, size=pl + L, text=payload.decode('utf-16-le'))
        i += pl + L
    return entries


def build_patch(entry, new_text):
    payload = new_text.encode('utf-16-le')
    flag = bytes([us_flag(new_text)])
    L = len(payload) + 1
    prefix = enc_compact(L)
    total = len(prefix) + L
    if total > entry['size']:
        raise ValueError('no room: %r(%d bytes) -> %r needs %d, have %d' % (
            entry['text'], entry['size'], new_text, total, entry['size']))
    blob = (prefix + payload + flag).ljust(entry['size'], b'\x00')
    assert len(blob) == entry['size']
    return blob


def run(dll, dict_path, allow_path=None, apply=False, dry=False, out=None):
    data = bytearray(open(dll, 'rb').read())
    orig = bytes(data)
    pex = PE(dll)
    us_off, us_size = pex.streams['#US']
    entries = parse_us(bytes(data), us_off, us_size)

    mapping = json.load(open(dict_path, encoding='utf-8'))
    allow = {}
    allow_texts = None
    if allow_path:
        allow_doc = json.load(open(allow_path, encoding='utf-8'))
        if allow_doc and isinstance(allow_doc[0], str):
            # text-based allow list: portable across ShareX builds (offsets shift, texts do not)
            allow_texts = set(allow_doc)
            extra = os.path.join(os.path.dirname(os.path.abspath(allow_path)), 'extra_allow.json')
            if os.path.isfile(extra):
                allow_texts |= set(json.load(open(extra, encoding='utf-8')))
        else:
            allow = {item['idx']: item['text'] for item in allow_doc}

    patches, problems, applied_keys, toolong = [], [], set(), []
    for idx, e in sorted(entries.items()):
        if allow_texts is not None:
            if e['text'] not in allow_texts:
                continue
        elif allow and idx not in allow:
            continue
        new = mapping.get(e['text'])
        if new is None:
            continue
        try:
            blob = build_patch(e, new)
        except ValueError as ex:
            toolong.append(str(ex))
            continue
        patches.append((e['off'], blob, e, new))
        applied_keys.add(e['text'])

    unused = [k for k in mapping if k not in applied_keys]
    patches.sort(key=lambda x: x[0])
    for a, b in zip(patches, patches[1:]):
        if a[0] + len(a[1]) > b[0]:
            problems.append('overlap at 0x%x' % a[0])

    untranslated = []
    if allow_texts is not None:
        untranslated = [t for t in allow_texts if t not in mapping]
    elif allow_path:
        allow_doc2 = json.load(open(allow_path, encoding='utf-8'))
        untranslated = [item['text'] for item in allow_doc2 if item['text'] not in mapping]

    print('entries %d, patches %d, dict keys %d, unused dict keys %d, allow texts missing from dict %d' % (
        len(entries), len(patches), len(mapping), len(unused), len(untranslated)))
    for p in problems:
        print('  PROBLEM ' + p)
    if toolong:
        print('  SKIP-TOO-LONG (%d):' % len(toolong))
        for t in toolong[:20]:
            print('    ' + t)
    if unused:
        print('  UNUSED  ' + ' | '.join(sorted(unused)[:25]))
    if untranslated:
        print('  NOT-YET-TRANSLATED ' + ' | '.join(sorted(set(untranslated))[:25]))
    if problems:
        return 1
    if dry:
        return 0

    for off, blob, e, new in patches:
        data[off:off + len(blob)] = blob

    assert len(data) == len(orig)
    changed = [i for i in range(len(data)) if data[i] != orig[i]]
    outside = [i for i in changed if not (us_off <= i < us_off + us_size)]
    if outside:
        print('ABORT: %d byte changes outside #US' % len(outside))
        return 1
    patched = bytes(data)
    entries2 = parse_us(patched, us_off, us_size)
    if len(entries2) != len(entries):
        print('ABORT: heap entry count changed %d -> %d' % (len(entries), len(entries2)))
        return 1
    for off, blob, e, new in patches:
        if entries2[e['off'] - us_off]['text'] != new:
            print('ABORT: readback mismatch %r' % new)
            return 1
    print('bytes changed %d, heap entries intact' % len(changed))

    target = dll if apply else (out or dll + '.patched')
    if apply:
        with open(target, 'r+b') as f:
            f.write(patched)
            f.flush()
            os.fsync(f.fileno())
    else:
        with open(target, 'wb') as f:
            f.write(patched)
    print('wrote', target)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dll')
    ap.add_argument('dict')
    ap.add_argument('--allow', default=None)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--out')
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()
    rc = run(args.dll, args.dict, args.allow, args.apply, args.dry, args.out)
    sys.exit(rc)


if __name__ == '__main__':
    main()
