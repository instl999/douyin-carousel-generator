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

放好后 `python -m dig doctor` 会显示实际选中的是哪一个，连同字体名（比如 `Noto Sans CJK SC Black`）。

**.ttc 字体集合会自动挑简体中文。** 一个 .ttc 里常常同时装着日、韩、简、繁几个版本，
同一个汉字写法不一样：Noto Sans CJK 的第 0 个是**日文**，直接用会把「房、没、次、退」画成日本字形。
程序按字体名挑 SC/CN/GB 那一个；`doctor` 发现选中的不是简体会提醒你。
也可以在 config.yaml 里写死：

```yaml
text:
  font: assets/fonts/SourceHanSansSC-Heavy.otf
  font_index: 0      # 只有手动指定 .ttc 字体集时才生效（自动查找会按名字挑简体）
```

Linux / Docker / Codex 容器里没有中文字体时：

```bash
apt-get update && apt-get install -y fonts-noto-cjk
```

没有中文字体会怎样？标题会渲染成方块或问号——`dig doctor` 会明确警告。
