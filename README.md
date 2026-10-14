# ShareX 图像编辑器 · 中文汉化

给 [ShareX](https://github.com/ShareX/ShareX) 新版图像编辑器（Avalonia 版）补上中文界面。
每 2 天自动检查官方新版本，有更新就重新打补丁并发布。

## 为什么需要它

ShareX 21 起的独立图像编辑器（`ShareX.ImageEditor.dll`）**完全没有官方翻译**：
`Languages\<语言>\` 里的卫星程序集只覆盖老的 WinForms 界面，新编辑器不走那套机制——
它的界面文字被 Avalonia 的 XAML 编译器编进了程序集自己的字符串表（.NET 元数据 `#US` 堆）。

所以这里用字节级补丁：把英文字符串就地换成中文。

- **只改字符串内容**，不改代码、不改元数据结构、不改文件长度；
- 每条替换保证 UTF-16 字节数不超过原条目，剩余空间补零，因此其它字符串的偏移和所有 `ldstr` token 依然有效；
- 每次构建都会校验：文件长度不变、所有改动字节都落在 `#US` 堆区间内、替换后的文字能读回。

ShareX 21.0.0 实测：1251 条界面文字，改动 34025 字节，文件仍是 3389952 字节。

## 安装

方式一（手动）：

1. 完全退出 ShareX（托盘图标右键 → 退出）。
2. 从 [Releases](../../releases) 下载 `ShareX.ImageEditor.dll`。
3. 备份你安装目录里的同名文件，然后用下载的文件覆盖它。

方式二（脚本）：下载 Release 里的 `应用汉化.bat` 和 `apply_localization.py` 放到 ShareX 安装目录，双击 bat。
它会自动检查 ShareX 是否运行、先备份、再打补丁，并打印本次替换了多少条。

还原：`恢复英文原版.bat`（用补丁时生成的 `.orig-*` 备份还原）。

## 哪些文字仍是英文（故意的）

| 文字 | 原因 |
| --- | --- |
| 侧栏 `Background`、比例 `Auto`、背景类型 `Transparent`、`Rotate`、`Image` | 同一段字符串既显示给人看、又被程序当内部标识符（样式选择器名、命令比较、句柄名）。翻译会让功能失效。 |
| 边框样式 `Solid`、效果分组标题 `Manipulations / Adjustments / Filters / Drawings` | 来自枚举 `ToString()`，不是字符串字面量，字节补丁碰不到。 |
| `CRT`、`macOS`、`Windows 11`、`Emoji`、`Bayer 4x4`、`Floyd-Steinberg` 等 | 专有名词，保留原文。 |

**注意一个副作用**：效果下拉框里的选项值（如实线/虚线、左上/右下）在程序里"显示文字"和"持久化值"是同一个字符串。
汉化后，**汉化之前保存的效果预设**或别人给的 `.sxie` 效果包里那些英文选项值会匹配不上——表现为该参数退回默认值，不会崩溃。

## 自动同步流程

`.github/workflows/localize.yml`，每 2 天（`04:00 UTC`）跑一次，也可手动触发或改词典后自动触发：

1. 查 `ShareX/ShareX` 的 latest release；
2. 与本仓库已有的 `v<版本>-zh` 比较，没有新版本就什么都不做；
3. 下载官方 portable zip，按 GitHub 公布的 `sha256 digest` 校验；
4. 从 zip 里取出 `ShareX.ImageEditor.dll`；
5. 对这一版二进制**重新做界面文字识别**（IL 上下文分析：某字符串若出现在 `set_Name`、样式选择器、资源键、
   `PropertyChangedEventArgs`、字符串比较、`Parse` 等位置，整条放弃翻译），
   再套用 `dictionary/zh_all.json`；
6. 发布 `v<版本>-zh`，附带汉化后的 DLL、应用脚本、词典、`untranslated.txt` 和 `report.json`，
   发布说明里列出哈希、改动字节数、以及"仍未翻译且可能被看到"的文字清单。

想补充词典：编辑 `dictionary/zh_all.json` 提 PR 或直接提交，流水线会自动重跑并发布。
识别逻辑在 `tools/allow2.py`，补丁写入在 `tools/patch_us.py`，入口是 `tools/pipeline.py`。

本地跑一遍（不需要 GitHub）：

```bash
pip install dnfile dncil
python tools/pipeline.py --dll <你的 ShareX.ImageEditor.dll> --out 汉化版.dll \
       --report report.json --untranslated untranslated.txt
```

## 许可与来源

- ShareX 版权归 [ShareX Team](https://github.com/ShareX/ShareX) 所有，本体以 **GPL-3.0** 发布；本仓库不替代、不重新授权官方程序。
- 本仓库自有内容（词典、识别与打补丁脚本、工作流）同样以 GPL-3.0 提供，见 `LICENSE`。
- Release 里的 DLL 是**官方二进制的修改版**，只替换界面文字；哈希与生成过程全部公开可复现。
- 这些 DLL 没有代码签名，Windows SmartScreen 可能告警——请自行按 `report.json` 里的 sha256 核对。
- 与 ShareX 官方无任何关联，官方也不为这份汉化背书。
