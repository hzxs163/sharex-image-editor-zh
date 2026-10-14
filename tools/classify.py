import sys, io, re, json

DISPLAY_PATTERNS = [
    r'\.set_Text$', r'set_Content$', r'set_Header$', r'set_Watermark$', r'set_ToolTip',
    r'SetTip', r'set_Label$', r'set_Description$', r'set_Title$', r'set_Message$',
    r'ShowNotification', r'CreateToolDefinition',
    r'set_ToolbarTitle$', r'set_Tooltip$', r'set_PlaceholderText', r'set_AccessText',
    r'Toast', r'set_Subtitle', r'set_Caption', r'set_Hint$', r'\.set_Text\b'
]
NONDISPLAY_PATTERNS = [
    r'set_Name$', r'INameScope\.Register', r'Classes\.Add', r'Selectors\.', r'ElementName',
    r'DynamicResourceExtension', r'StaticResourceExtension', r'PropertyChangingEventArgs',
    r'PropertyChangedEventArgs', r'op_Equality', r'String\.Equals', r'String\.Contains',
    r'String\.StartsWith', r'String\.EndsWith', r'String\.Replace', r'String\.Concat',
    r'BindClass', r'ReflectionBindingExtension', r'CompiledBindingExtension', r'CreateNamespaceInfo',
    r'\.Add$', r'set_Item$', r'ArgumentNullException', r'ArgumentException',
    r'InvalidOperationException', r'KeyGesture\.Parse', r'Color\.(Parse|FromUInt32)', r'Rect\.Parse',
    r'BoxShadows\.Parse', r'ContainsDesktopToken', r'CultureInfo', r'on_Equality',
    r'ArgumentNullException\.ThrowIfNull', r'CreateHandle', r'TransformConverter', r'onPropertyChanged',
    r'set_StringFormat', r'set_ConverterParameter', r'CommandParameter', r'FontFamily',
    r'Brushes\.', r'TryReadGSettingsValue', r'SafeCopyBitmap', r'Remove$'
]
DISPLAY_RE = re.compile('|'.join(DISPLAY_PATTERNS))
NONDISPLAY_RE = re.compile('|'.join(NONDISPLAY_PATTERNS))
DISPLAY_METHOD_RE = re.compile(
    r'^(get_(Name|Description|DisplayName|Label|Tooltip|ToolTip|Title|Message|Text|Summary|Hint|'
    r'Watermark|SectionHeader|CategoryName|ParameterName|FriendlyName|UnitLabel|Placeholder|'
    r'ResultsSummary))$'
    r'|^(Build.*(Title|Message|Summary|Notification)|.*Notification|Show.*(Message|Notification|Toast))$',
    re.I)


def load(path):
    rows = []
    with io.open(path, encoding='utf-8') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            if line.startswith(' '):
                continue
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 9:
                continue
            idx, foff, bytes_, maxchars, tname, mname, s, prv, nxt = parts[:9]
            if idx == '-1':
                continue
            nxt = nxt.replace('NEXT[', '').rstrip(']')
            s = s.replace('\\n', '\n').replace('\\t', '\t')
            rows.append(dict(idx=int(idx), foff=foff, size=int(bytes_.split('=')[1]),
                             budget=int(maxchars.split('=')[1]), tname=tname, mname=mname,
                             text=s, prv=prv.replace('PREV[', '').rstrip(']'), nxt=nxt))
    return rows


def main(inv_path, out_path):
    rows = load(inv_path)
    by_idx = {}
    for r in rows:
        by_idx.setdefault(r['idx'], []).append(r)
    disp, conflict, nondisp, unknown = [], [], [], []
    for idx, uses in sorted(by_idx.items()):
        text = uses[0]['text']
        tags = []
        for u in uses:
            n = u['nxt']
            m = u['mname']
            d = bool(DISPLAY_RE.search(n)) or bool(DISPLAY_METHOD_RE.match(m)) or ('set_TargetNullValue' in n)
            nd = bool(NONDISPLAY_RE.search(n)) or (m == 'get_IconKey')
            if d and not nd:
                tags.append('D')
            elif nd:
                tags.append('X')
            else:
                tags.append('?')
        has_d = 'D' in tags
        has_x = 'X' in tags
        in_xaml = any(('XamlIlPopulate' in u['mname']) or u['mname'].startswith('Populate:') for u in uses)
        rec = dict(idx=idx, text=text, size=uses[0]['size'], budget=uses[0]['budget'],
                   uses=[(u['tname'], u['mname'][:44], u['nxt'][:64]) for u in uses], tags=tags, xaml=in_xaml)
        if has_d and has_x:
            conflict.append(rec)
        elif has_d:
            disp.append(rec)
        elif has_x and in_xaml:
            conflict.append(rec)
        elif in_xaml:
            unknown.append(rec)
        else:
            nondisp.append(rec)
    with io.open(out_path, 'w', encoding='utf-8') as f:
        f.write('=== DISPLAY-ONLY (%d) ===\n' % len(disp))
        for r in sorted(disp, key=lambda x: x['text']):
            f.write('idx=%d size=%d budget=%d | %s | %s\n' % (r['idx'], r['size'], r['budget'], r['text'],
                                                               ' ; '.join('%s::%s->%s' % u for u in r['uses'][:2])))
        f.write('\n=== XAML/UNKNOWN (%d) ===\n' % len(unknown))
        for r in sorted(unknown, key=lambda x: x['text']):
            f.write('idx=%d size=%d budget=%d tags=%s | %s | %s\n' % (r['idx'], r['size'], r['budget'],
                        ''.join(r['tags']), r['text'], ' ; '.join('%s::%s->%s' % u for u in r['uses'][:3])))
        f.write('\n=== CONFLICT (%d) ===\n' % len(conflict))
        for r in sorted(conflict, key=lambda x: x['text']):
            f.write('idx=%d size=%d budget=%d tags=%s | %s | %s\n' % (r['idx'], r['size'], r['budget'],
                        ''.join(r['tags']), r['text'], ' ; '.join('%s::%s->%s' % u for u in r['uses'][:6])))
        f.write('\n=== NON-DISPLAY (%d) ===\n' % len(nondisp))
        for r in sorted(nondisp, key=lambda x: x['text'])[:400]:
            f.write('idx=%d | %s | %s\n' % (r['idx'], r['text'], ' ; '.join('%s->%s' % (u[1], u[2]) for u in r['uses'][:1])))
    print('display', len(disp), 'xaml-unknown', len(unknown), 'conflict', len(conflict), 'nondisplay', len(nondisp), 'total', len(by_idx))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
