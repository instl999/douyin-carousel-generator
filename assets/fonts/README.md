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

After adding one, `python -m dig doctor` reports which file was actually selected. You can
also pin it in `config.yaml`:

```yaml
text:
  font: assets/fonts/SourceHanSansSC-Heavy.otf
  font_index: 0      # only relevant for .ttc collections
```

On Linux / Docker / CI containers without CJK fonts:

```bash
apt-get update && apt-get install -y fonts-noto-cjk
```

What happens without a CJK font? Captions render as boxes or question marks — `dig doctor`
warns about this explicitly.
