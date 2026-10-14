"""Text-based display-string allow list for ShareX Image Editor localization.

Unlike the first version (which keyed on #US byte offsets and therefore only worked on
one exact build), this one emits a list of English *texts*. That list, plus the
translation dictionary, can be replayed against any future ShareX build.

Safety model:
  * an entry is eligible only when EVERY place that loads it looks like user-facing text
  * any single use in an identifier context (x:Name, style selectors, resource keys,
    property-changed names, string comparisons, binding paths, parsers, ...) disqualifies
    the whole entry, because identical literals are stored once in the #US heap
  * eligibility is only a gate: a string is still replaced only if the dictionary has it
"""
import io, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from classify import load          # reads the tab-separated inventory report

# ---- contexts that prove the string is shown to the user -----------------------------
DISPLAY_USE = re.compile(
    r'\.set_Text$|\.set_Content$|\.set_Header$|\.set_Watermark$|\.set_ToolTip|\.set_Tooltip'
    r'|SetTip|\.set_Label$|\.set_Description$|\.set_Title$|\.set_Message$|\.set_Summary$'
    r'|\.set_Hint$|\.set_Placeholder|\.set_DisplayName$|\.set_TargetNullValue$'
    r'|ShowNotification|CreateToolDefinition|Notification$|Toast$|\.set_Header$'
    r'|AppendLiteral|StringBuilder\.Append$|String\.Concat|AppendFormatted', re.I)

# ---- methods whose whole purpose is producing visible text ---------------------------
DISPLAY_METHOD = re.compile(
    r'^(get_|set_|)(.*?)(Tooltip|ToolTip|Label|Title|Message|Description|Text|Summary|Hint'
    r'|Watermark|DisplayName|Placeholder|Header|Name|Caption|Subtitle|ButtonText|Prompts?)$',
    re.I)
VIEW_TYPE = re.compile(r'(ViewModel|View|Window|Dialog|Panel|Control|Toolbar|Form|Page|Editor)$')

# ---- one use in any of these contexts disqualifies the entire entry ------------------
IDENTIFIER_USE = re.compile(
    r'set_Name$|INameScope\.Register|\.Classes\.Add|Selectors\.|ElementName'
    r'|DynamicResourceExtension|StaticResourceExtension|ThemeVariant'
    r'|Property(Changing|ChangedEventArgs)|OnPropertyChanged'
    r'|op_Equality|String\.Equals|\.Contains\(|StartsWith|EndsWith|\.Replace\(|IndexOf'
    r'|\bParse$|\.Parse|Enum\.|GetTypeFrom|GetType\(|nameof'
    r'|CommandParameter|ConverterParameter|StringFormat|BindingPath|ReflectionBinding'
    r'|CompiledBinding(?!.*set_TargetNullValue)|BindClass|AddHandler|RemoveHandler'
    r'|FindName|RegisterName|SetValue|GetValue|TryGetValue|Dictionary'
    r'|FontFamily|Brushes\.|KeyGesture|CultureInfo|Serialization|ToJson|FromJson'
    r'|set_Mode$|Resources\.|CreateNamespaceInfo|\.Add$', re.I)
IDENTIFIER_METHOD = re.compile(r'^(get_IconKey|get_Key$|get_Id$|get_JsonKey|get_SchemaKey'
                               r'|get_TypeName|get_AssemblyName|GetHashCode|ToString|get_ResourceKey)', re.I)
PARAM_LABEL = re.compile(r'^[A-Z]|[ ]')


def classify_use(n, m, t, text):
    """-> 'ID' (identifier, disqualifies), 'DISP' (visible text), '' (neutral)."""
    if IDENTIFIER_USE.search(n) or IDENTIFIER_METHOD.search(m):
        return 'ID'
    if m == 'get_Parameters':
        # effect parameters come in (snake_case key, Capitalized label, format) triples:
        # only the key half is an identifier, the label half is what the dialog shows
        return 'DISP' if PARAM_LABEL.search(text.strip() or ' ') else 'ID'
    if DISPLAY_USE.search(n) or DISPLAY_METHOD.search(m) or VIEW_TYPE.search(t):
        return 'DISP'
    return ''


def build(inventory_path, out_path=None):
    rows = load(inventory_path)
    by_idx = {}
    for r in rows:
        by_idx.setdefault(r['idx'], []).append(r)

    eligible, tainted = {}, {}
    for idx, uses in by_idx.items():
        text = uses[0]['text']
        good = bad = 0
        bad_ctx = []
        for u in uses:
            tag = classify_use(u['nxt'], u['mname'], u['tname'], u['text'])
            if tag == 'ID':
                bad += 1
                bad_ctx.append('%s::%s -> %s' % (u['tname'], u['mname'], u['nxt']))
            elif tag == 'DISP':
                good += 1
        if bad:
            tainted[idx] = (text, bad_ctx[:3])
            continue
        if good == 0:
            continue
        stripped = text.strip()
        if len(stripped) < 2 or not re.search(r'[A-Za-z]{2}', stripped):
            continue
        if re.fullmatch(r'[\W\d_]+', stripped):
            continue
        if stripped.startswith('http') or '://' in stripped:
            continue
        eligible[idx] = text

    texts = sorted(set(eligible.values()))
    if out_path:
        out_path = os.path.abspath(out_path)
        with io.open(out_path, 'w', encoding='utf-8') as f:
            json.dump(texts, f, ensure_ascii=False, indent=1)
    return texts, eligible, tainted


def main():
    inv = sys.argv[1] if len(sys.argv) > 1 else '_inv_editor.txt'
    texts, eligible, tainted = build(inv, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                       '_allow_texts.json'))
    dict_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'zh_all.json')
    have = set(json.load(io.open(dict_path, encoding='utf-8'))) if os.path.isfile(dict_path) else set()
    missing = [t for t in texts if t not in have]
    print('eligible texts %d (entries %d), already in dict %d, newly eligible %d, tainted-and-skipped %d'
          % (len(texts), len(eligible), len(texts) - len(missing), len(missing), len(tainted)))
    with io.open('_missing.txt', 'w', encoding='utf-8') as f:
        for t in missing:
            f.write(t.replace('\n', '\\n') + '\n')
    with io.open('_tainted.txt', 'w', encoding='utf-8') as f:
        for idx, (t, ctx) in sorted(tainted.items(), key=lambda kv: kv[1][0]):
            f.write('%s\t%s\n' % (t.replace('\n', '\\n'), ' ;; '.join(ctx)))
    print('wrote _allow_texts.json, _missing.txt, _tainted.txt')


if __name__ == '__main__':
    main()
