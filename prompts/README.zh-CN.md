# 提示词目录


*[English](README.md)*

| 文件 | 用途 | 在哪里被用到 |
|---|---|---|
| `topic_ideation_zh.md` | **选题生成**，复制进 ChatGPT 用 | 人工，产出 `topics.json` |
| — | 分镜脚本系统提示词 | 代码内置：`dig/script_gen.py` 的 `SYSTEM` |
| — | 画风反推提示词 | 代码内置：`dig/style.py` 的 `STYLE_SYSTEM` |
| — | 角色设定卡提示词 | 代码内置：`dig/character.py` 的 `CHAR_SYSTEM` |
| — | 单格画面提示词拼装 | 代码内置：`dig/prompt_builder.py` |

内置的那几条写在代码里是故意的：它们和 JSON 解析、字数清洗逻辑是配套的，
改提示词而不改解析容易出错。要调就直接改对应的 `.py`，都在文件顶部。
