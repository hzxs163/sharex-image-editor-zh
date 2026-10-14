"""Localization pipeline entry point (used by GitHub Actions and by the local client).

  python tools/pipeline.py --dll path/to/ShareX.ImageEditor.dll \
         [--out patched.dll] [--dict dictionary/zh_all.json] \
         [--allow-saved dictionary/allow_texts.json] [--extras dictionary/extra_allow.json] \
         [--report report.json] [--untranslated untranslated.txt]

What it does:
  1. re-derives the "display text only" allow list from *this exact* binary (IL context analysis)
  2. unions in a small hand-vetted extras list
  3. applies the English -> Chinese dictionary, size preserving, inside the #US heap only
  4. writes a machine readable report: hashes, counts, and every eligible string that has no
     translation yet (that list is what the release notes show)

If the analyzer cannot run (missing dnfile/dncil) it falls back to the saved allow list.
"""
import argparse, hashlib, io, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

DLL_NAME = 'ShareX.ImageEditor.dll'


DEBUGISH = (
    'effectId=', 'ReferenceEqual', 'SafeCopyBitmap', 'CommitEffect', 'PreviewEffect',
    'StartEffectPreview', 'UpdatePreview', 'ApplyClicked', 'AttachedToVisualTree',
    'ParameterState', 'Slider[', 'ToggleSwitch[', 'AfterSet', 'DataContext', 'snapshot=',
    'refEqSource', 'inParameterStates', 'controlValue', 'controlIsChecked', 'modelValue',
    'prop=', 'key=', 'category=', 'paramCount', 'status=', 'ApplyEffect', 'CreateSourceImage',
    'MoveNext', 'g__', 'd__', '=', '::', 'Avalonia', 'Skia', '--', '%s', '%d', 'command -v',
)


PROPER_NOUNS = {'arial', 'png', 'jpg', 'jpeg', 'webp', 'crt', 'emoji', 'bmp', 'gif', 'tiff',
                'rgb332', 'vhs', 'sobel', 'perlin', 'hsv', 'rgb', 'linux', 'macos', 'windows 11',
                'shift', 'ctrl', 'alt', 'enter', 'esc', 'tab', 'null', '(null)', 'none'}


def worth_reporting(text):
    """True when an untranslated string looks like something a user would actually see."""
    import re
    s = text.strip()
    if len(s) < 3 or not re.search(r'[A-Za-z]{3}', s):
        return False
    if any(d in text for d in DEBUGISH):
        return False
    if re.fullmatch(r'#[0-9a-fA-F]{3,8}', s):
        return False
    if re.fullmatch(r'[\W\d_]+', s):
        return False
    if re.fullmatch(r'[a-z][A-Za-z0-9_]*', s):        # camelCase / snake_case identifiers
        return False
    if ' ' not in s and not re.search(r'[.:;,!?]', s):
        return False                                   # one bare token: type/member/asset name
    if re.fullmatch(r'[A-Za-z]+(\.[A-Za-z0-9]+)+', s):
        return False                                   # dotted resource keys
    if s.lower().strip('()') in PROPER_NOUNS:
        return False
    if re.match(r'^(Bayer|Floyd|Warhol|Kuwahara|Voronoi|Risograph)', s):
        return False
    if s.startswith('http') or '://' in s or s.endswith(('.dll', '.png', '.json', '.onnx', '.webp')):
        return False
    return True


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def analyze(dll, workdir):
    """Return (allow_texts, tainted_count, note)."""
    import inventory
    import allow2
    inv = os.path.join(workdir, 'inventory.txt')
    inventory.main(dll, inv)
    texts, eligible, tainted = allow2.build(inv, None)
    return texts, len(tainted), 'analyzer: %d IL references scanned' % len(texts)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--dll', required=True)
    ap.add_argument('--out')
    ap.add_argument('--dict', default=os.path.join(ROOT, 'dictionary', 'zh_all.json'))
    ap.add_argument('--allow-saved', default=os.path.join(ROOT, 'dictionary', 'allow_texts.json'))
    ap.add_argument('--extras', default=os.path.join(ROOT, 'dictionary', 'extra_allow.json'))
    ap.add_argument('--report')
    ap.add_argument('--untranslated')
    ap.add_argument('--report-raw', dest='report_raw')
    args = ap.parse_args(argv)

    dll = os.path.abspath(args.dll)
    out = os.path.abspath(args.out or (dll + '.zh'))
    dictionary = json.load(io.open(args.dict, encoding='utf-8'))
    report = {'dll': os.path.basename(dll), 'size_bytes': os.path.getsize(dll),
              'sha256_before': sha256(dll), 'dictionary_entries': len(dictionary)}

    with tempfile.TemporaryDirectory() as td:
        try:
            allow, tainted, note = analyze(dll, td)
            report['allow_source'] = 'analyzer'
        except Exception as ex:
            allow = json.load(io.open(args.allow_saved, encoding='utf-8'))
            tainted, note = 0, 'analyzer unavailable (%s): used saved allow list' % ex
            report['allow_source'] = 'saved-fallback'
        report['analyzer_note'] = note
        report['eligible_display_texts'] = len(allow)
        report['skipped_identifier_tainted'] = tainted

        allow_set = set(allow)
        if os.path.isfile(args.extras):
            allow_set |= set(json.load(io.open(args.extras, encoding='utf-8')))
        allow_file = os.path.join(td, 'allow.json')
        json.dump(sorted(allow_set), io.open(allow_file, 'w', encoding='utf-8'), ensure_ascii=False)

        import patch_us
        rc = patch_us.run(dll, args.dict, allow_file, apply=False, out=out)
        report['return_code'] = rc
        if rc != 0:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return rc

    patched = open(out, 'rb').read()
    original = open(dll, 'rb').read()
    report['sha256_after'] = sha256(out)
    report['size_after_bytes'] = len(patched)
    report['bytes_changed'] = sum(1 for a, b in zip(original, patched) if a != b)
    report['size_preserved'] = len(original) == len(patched)

    missing = sorted(t for t in allow_set if t not in dictionary)
    report['translated'] = len(allow_set) - len(missing)
    report['untranslated_count'] = len(missing)
    # the raw list is full of log/debug fragments; only surface what a human would notice
    worth = [t for t in missing if worth_reporting(t)]
    report['untranslated_reportable_count'] = len(worth)
    if args.untranslated:
        io.open(args.untranslated, 'w', encoding='utf-8').write('\n'.join(worth))
    if args.report_raw and missing:
        io.open(args.report_raw, 'w', encoding='utf-8').write('\n'.join(missing))
    if args.report:
        json.dump(report, io.open(args.report, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print(json.dumps({k: v for k, v in report.items()}, ensure_ascii=False, indent=2))
    if not report['size_preserved']:
        print('FATAL: file size changed', file=sys.stderr)
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
