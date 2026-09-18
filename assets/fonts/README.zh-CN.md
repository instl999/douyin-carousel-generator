# 字体


*[English](README.md)*

标题用的中文粗黑体。程序会按下面的顺序自动找：

1. **本目录**里的字体文件（优先级最高，把 .ttf / .otf 直接丢进来即可）
2. 系统字体：Windows 微软雅黑 Bold / macOS PingFang / Linux Noto Sans CJK

推荐放这几个（都可免费商用，自行下载）：

| 字体 | 文件名 | 特点 |
|---|---|---|
| 思源黑体 Heavy | `SourceHanSansSC-Heavy.otf` | 最接近参考样例的厚重感 |
| 阿里巴巴普惠体 Black | `AlibabaPuHuiTi-3-115-Black.ttf` | 商用免费，字重足 |
| Noto Sans SC Black | `NotoSansSC-Black.ttf` | 跨平台一致 |

放好后 `python -m dig doctor` 会显示实际选中的是哪一个。
也可以在 config.yaml 里写死：

```yaml
text:
  font: assets/fonts/SourceHanSansSC-Heavy.otf
  font_index: 0      # .ttc 字体集才需要改
```

Linux / Docker / Codex 容器里没有中文字体时：

```bash
apt-get update && apt-get install -y fonts-noto-cjk
```

没有中文字体会怎样？标题会渲染成方块或问号——`dig doctor` 会明确警告。
