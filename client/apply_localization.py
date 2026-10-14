"""ShareX 图像编辑器汉化 - 本机应用/回滚工具

用法：
    python apply_localization.py "D:\\ShareX-21.0.0-portable-x64"        # 应用汉化
    python apply_localization.py "D:\\ShareX-21.0.0-portable-x64" --revert  # 还原英文原版
    python apply_localization.py --detect                                # 只找安装目录

不需要联网：词典随仓库一起分发，界面文本的识别在本地按你这一版二进制重新做。
"""
import argparse, glob, io, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
DLL_NAME = 'ShareX.ImageEditor.dll'
try:  # the Windows console defaults to GBK; force UTF-8 so printing Chinese cannot abort the run
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

PRISTINE_DIR = os.path.join(ROOT, 'original')


def detect_installs():
    """Look for a ShareX install folder near this script, then on common roots."""
    hits = []
    bases = [os.path.abspath(os.path.join(ROOT, '..')),
             os.path.abspath(os.path.join(ROOT, '..', '..')),
             os.path.abspath(os.path.join(HERE, '..', '..', '..'))]
    for b in set(bases):
        if not os.path.isdir(b):
            continue
        hits += glob.glob(os.path.join(b, '*', 'ShareX.exe'))
        hits += glob.glob(os.path.join(b, '*', '*', 'ShareX.exe'))
    dirs = sorted({os.path.dirname(h) for h in hits})
    return dirs


def running():
    out = []
    for name in ('ShareX.exe', 'ShareX.ImageEditor.App.exe'):
        try:
            r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq %s' % name, '/FO', 'CSV', '/NH'],
                               capture_output=True, text=True, timeout=30)
            for line in (r.stdout or '').splitlines():
                low = line.lower()
                if ('"%s"' % name.lower()) in low and 'no tasks' not in low:
                    out.append(line.strip())
        except Exception:
            pass
    return out


def find_tools():
    """Locate the pipeline tools folder (repo layout, or shipped alongside this script)."""
    for cand in (os.path.join(ROOT, 'tools'),
                 os.path.join(HERE, 'tools'),
                 os.path.abspath(os.path.join(HERE, '..', 'tools'))):
        if os.path.isfile(os.path.join(cand, 'pipeline.py')):
            return cand
    return None


def do_revert(install):
    dll = os.path.join(install, DLL_NAME)
    backups = sorted(glob.glob(os.path.join(install, DLL_NAME + '.orig-*')))
    pristine = os.path.join(PRISTINE_DIR, DLL_NAME)
    src = None
    if os.path.isfile(pristine):
        src = pristine
    elif backups:
        src = backups[0]
    if not src:
        print('X 找不到未汉化的原件（original/%s 或 %s.orig-*）' % (DLL_NAME, DLL_NAME))
        return 2
    shutil.copy2(src, dll)
    print('OK 已还原为官方原版：%s\n   来源：%s' % (dll, src))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('install', nargs='?', help='ShareX 安装目录（含 %s）' % DLL_NAME)
    ap.add_argument('--revert', action='store_true')
    ap.add_argument('--detect', action='store_true')
    args = ap.parse_args()

    if args.detect or not args.install:
        dirs = detect_installs()
        if not dirs:
            print('X 没能自动找到 ShareX 安装目录，请把目录作为参数传进来。')
            return 2
        print('找到的 ShareX 安装目录：')
        for d in dirs:
            print('   ', d)
        install = args.install or dirs[0]
    else:
        install = os.path.abspath(args.install)

    dll = os.path.join(install, DLL_NAME)
    if not os.path.isfile(dll):
        print('X 目录里没有 %s：%s' % (DLL_NAME, install))
        return 2
    b = running()
    if b:
        print('X ShareX 正在运行，请先退出（托盘图标 -> 退出）：')
        for x in b:
            print('   ', x)
        return 1
    if args.revert:
        return do_revert(install)

    stamp = time.strftime('%Y%m%d-%H%M%S')
    bak = os.path.join(install, '%s.orig-%s' % (DLL_NAME, stamp))
    shutil.copy2(dll, bak)
    print('已备份当前文件 ->', bak)
    if not os.path.isdir(PRISTINE_DIR):
        os.makedirs(PRISTINE_DIR)
    keep = os.path.join(PRISTINE_DIR, DLL_NAME)
    if not os.path.isfile(keep):
        shutil.copy2(bak, keep)
        print('同时在本仓库 original/ 存了一份未汉化原件（回滚用）')

    rep_path = os.path.join(install, '汉化报告.json')
    untr_path = os.path.join(install, '未翻译清单.txt')
    tools = find_tools()
    if not tools:
        print('X 找不到 tools/pipeline.py。')
        print('   如果你的 ShareX 版本与 Release 标注的一致，直接覆盖 DLL 即可（见 README 安装步骤）。')
        print('   本脚本用于版本不一致时重新识别并打补丁，需要仓库里的 tools 目录（连同本脚本一起下载即可）。')
        return 2
    # run the pipeline in a child process: pefile memory-maps the dll while analysing it,
    # and Windows refuses to overwrite a mapped image from the very process that mapped it
    cmd = [sys.executable, os.path.join(tools, 'pipeline.py'),
           '--dll', dll, '--out', dll + '.tmp-zh',
           '--report', rep_path, '--untranslated', untr_path]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    sys.stdout.write(''.join(l + '\n' for l in (r.stdout or '').splitlines()
                             if not l.startswith('progress')))
    rc = r.returncode
    if rc == 0:
        os.replace(dll + '.tmp-zh', dll)
        rep = json.load(io.open(rep_path, encoding='utf-8'))
        print('\n汉化完成：本次替换 %d 条界面文字，改动 %d 字节，文件长度保持不变。' %
              (rep['translated'], rep['bytes_changed']))
        if rep.get('untranslated_reportable_count'):
            print('  另有 %d 条可能被看到的英文未收录，清单：%s' %
                  (rep['untranslated_reportable_count'], untr_path))
        print('  还原：python apply_localization.py "%s" --revert' % install)
    else:
        print('X 打补丁失败：')
        print((r.stdout or '')[-1500:])
        print((r.stderr or '')[-1500:])
    return rc


if __name__ == '__main__':
    sys.exit(main())
