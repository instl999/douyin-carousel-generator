# Fonts

*[中文版](README.zh-CN.md)*

Captions need a heavy CJK sans. The program searches in this order:

1. **This directory** (highest priority — just drop a `.ttf` / `.otf` in)
2. System fonts: Microsoft YaHei Bold on Windows, PingFang on macOS, Noto Sans CJK on Linux

Recommended (all free for commercial use, download them yourself):

| Font | Filename | Why |
|---|---|---|
| Source Han Sans Heavy | `SourceHanSansSC-Heavy.otf` | Closest to the weight in the reference posts |
| Alibaba PuHuiTi Black | `AlibabaPuHuiTi-3-115-Black.ttf` | Free commercially, sufficiently heavy |
| Noto Sans SC Black | `NotoSansSC-Black.ttf` | Consistent across platforms |

After adding one, `python -m dig doctor` reports which file was actually selected, with the
face name (e.g. `Noto Sans CJK SC Black`).

**Font collections (`.ttc`) pick the Simplified Chinese face automatically.** One `.ttc`
often bundles Japanese, Korean, Simplified and Traditional variants whose glyphs differ:
Noto Sans CJK's face 0 is **Japanese**, which draws 房、没、次、退 in Japanese forms. The
tool picks the face whose name says SC/CN/GB, and `doctor` warns if the chosen one isn't. You can
also pin it in `config.yaml`:

```yaml
text:
  font: assets/fonts/SourceHanSansSC-Heavy.otf
  font_index: 0      # only used when you pin a .ttc yourself (auto-detection picks the SC face)
```

On Linux / Docker / CI containers without CJK fonts:

```bash
apt-get update && apt-get install -y fonts-noto-cjk
```

What happens without a CJK font? Captions render as boxes or question marks — `dig doctor`
warns about this explicitly.
