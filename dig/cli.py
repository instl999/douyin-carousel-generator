"""命令行入口。

最常用的一条：
    python -m dig run --theme "楼盘名字里的暗号" --style retro_comic --handle your_douyin_id
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from . import __version__
from .config import Config, load_config
from .util import DigError, log, set_verbose, warn


# --------------------------------------------------------------------------- #
# 公共参数
# --------------------------------------------------------------------------- #
def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", default="", help="配置文件路径（默认找 config.yaml）")
    p.add_argument("--offline", action="store_true", help="全部用 mock 引擎，不联网不花钱")
    p.add_argument("--verbose", "-v", action="store_true", help="打印请求细节")
    p.add_argument("--out", default="", help="输出目录（默认 output/时间戳_主题）")


def add_style_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--style", default="", help="画风预设 id，见 dig style list")
    p.add_argument("--style-prompt", default="", help="临时画风描述，覆盖预设的 prompt")


def build_config(args) -> Config:
    cfg = load_config(getattr(args, "config", "") or None)
    if getattr(args, "verbose", False):
        set_verbose(True)
    if getattr(args, "offline", False):
        cfg.use_mock()
        log("· 离线模式：使用 mock 引擎")
    return cfg


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #
def cmd_run(args) -> int:
    from . import pipeline

    cfg = build_config(args)
    if args.size:
        try:
            w, h = args.size.lower().split("x")
            cfg.set("page.width", int(w))
            cfg.set("page.height", int(h))
        except Exception:
            raise DigError("--size 格式应为 宽x高，例如 1440x1920")
    if args.workers:
        cfg.set("run.workers", args.workers)
    if args.seed is not None:
        cfg.set("run.seed", args.seed)
    if args.no_cache:
        cfg.set("run.cache", False)

    result = pipeline.run(
        cfg,
        theme=args.theme,
        style_id=args.style,
        style_prompt=args.style_prompt,
        character_id=args.character,
        pages=args.pages,
        panels=args.panels,
        handle=args.handle,
        angle=args.angle,
        audience=args.audience,
        out_dir=args.out,
        zip_it=args.zip,
        allow_in_image_text=args.allow_text_in_image,
        strict=args.strict,
        skip_validation=args.no_validate,
    )
    _print_result(result)
    return 0


def _print_result(result) -> None:
    log("")
    log("成图目录：" + result["out_dir"])
    for f in result.get("files", []):
        log("  " + os.path.basename(f))
    if result.get("caption"):
        log("文案：" + result["caption"])
    if result.get("zip"):
        log("打包：" + result["zip"])
    deck = result.get("deck")
    if deck is not None:
        errs = [b for b in deck.all_beats if b.error]
        if errs:
            warn("有 %d 格生图失败（已用占位图兜底），详见 manifest.json" % len(errs))


# --------------------------------------------------------------------------- #
# script / render
# --------------------------------------------------------------------------- #
def cmd_script(args) -> int:
    from . import pipeline

    cfg = build_config(args)
    result = pipeline.run(
        cfg,
        theme=args.theme,
        style_id=args.style,
        style_prompt=args.style_prompt,
        character_id=args.character,
        pages=args.pages,
        panels=args.panels,
        handle=args.handle,
        angle=args.angle,
        audience=args.audience,
        out_dir=args.out,
        script_only=True,
    )
    log("")
    log("脚本：" + result["script"])
    log("改完文案后用这条出图：")
    log("  python -m dig render --script \"%s\"" % result["script"])
    return 0


def cmd_render(args) -> int:
    from . import pipeline

    cfg = build_config(args)
    if args.no_cache:
        cfg.set("run.cache", False)
    result = pipeline.run(
        cfg,
        script_path=args.script,
        style_id=args.style,
        style_prompt=args.style_prompt,
        character_id=args.character,
        handle=args.handle,
        out_dir=args.out or os.path.dirname(os.path.abspath(args.script)),
        render_only=args.skip_images,
        zip_it=args.zip,
        strict=args.strict,
        skip_validation=args.no_validate,
    )
    _print_result(result)
    return 0


# --------------------------------------------------------------------------- #
# batch
# --------------------------------------------------------------------------- #
def cmd_validate(args) -> int:
    """只体检，不生成。Agent 应该在花钱之前先跑这个。"""
    from . import pipeline, validate
    from .character import load_character
    from .models import Deck

    cfg = build_config(args)
    deck = Deck.from_dict(pipeline.read_script(args.script))
    character = deck.character
    if not character and deck.character_id:
        try:
            character = load_character(cfg, deck.character_id)
        except DigError:
            character = None
    style = pipeline.resolve_style(cfg, args.style or deck.style_id)

    issues = validate.validate_deck(deck, style, character, strict=args.strict)
    log(validate.format_issues(issues))
    if validate.has_errors(issues):
        log("")
        log("有错误，生成会被拦下。改完再跑一次这条命令。")
        return 2
    log("")
    log("可以生成了：python -m dig render --script \"%s\"" % args.script)
    return 0


def cmd_batch(args) -> int:
    from . import pipeline
    from .util import load_json

    cfg = build_config(args)
    if args.out:
        # 批量时 --out 是"放所有作品的父目录"，不是单个作品目录
        cfg.set("output_dir", args.out)
    data = load_json(args.file)
    if isinstance(data, dict):
        data = data.get("topics") or data.get("items") or []
    if not isinstance(data, list) or not data:
        raise DigError("选题文件应该是一个数组，或者 {\"topics\": [...]}")
    if args.limit:
        data = data[: args.limit]

    results = pipeline.run_batch(
        cfg,
        data,
        style_id=args.style,
        style_prompt=args.style_prompt,
        character_id=args.character,
        pages=args.pages,
        handle=args.handle,
        zip_it=args.zip,
    )
    ok = [r for r in results if not r.get("error")]
    log("\n批量完成：成功 %d / %d" % (len(ok), len(results)))
    for r in results:
        if r.get("error"):
            log("  ✗ %s：%s" % (r.get("theme"), r["error"]))
        else:
            log("  ✓ " + r["out_dir"])
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# style
# --------------------------------------------------------------------------- #
def cmd_style(args) -> int:
    from . import style as style_mod
    from .providers import make_text_engine

    cfg = build_config(args)

    if args.style_cmd == "list":
        names = style_mod.list_styles(cfg)
        if not names:
            log("styles/ 目录是空的")
            return 0
        log("可用画风预设：")
        for n in names:
            preset = style_mod.load_style(cfg, n)
            log("  %-16s %s" % (n, preset.name))
            if preset.description:
                log("  %-16s   %s" % ("", preset.description))
        return 0

    if args.style_cmd == "show":
        preset = style_mod.load_style(cfg, args.id)
        log("id:      " + preset.id)
        log("name:    " + preset.name)
        log("prompt:  " + preset.prompt)
        log("negative:" + preset.negative)
        log("palette: " + ", ".join(preset.palette))
        return 0

    if args.style_cmd == "add":
        if not args.from_image:
            raise DigError("请给一张参考图：--from-image ref.jpg")
        vision = make_text_engine(cfg.provider("vision"), cfg.root)
        log("正在分析参考图的画风…")
        preset = style_mod.style_from_image(
            cfg, vision, args.from_image, name=args.name, style_id=args.id
        )
        path = style_mod.save_style(cfg, preset)
        log("已保存画风预设：" + path)
        log("  id:     " + preset.id)
        log("  prompt: " + preset.prompt[:120])
        log("用法：python -m dig run --theme \"...\" --style " + preset.id)
        return 0

    raise DigError("未知的 style 子命令")


# --------------------------------------------------------------------------- #
# character
# --------------------------------------------------------------------------- #
def cmd_character(args) -> int:
    from . import character as char_mod
    from . import style as style_mod
    from .providers import make_image_engine, make_text_engine

    cfg = build_config(args)

    if args.char_cmd == "list":
        names = char_mod.list_characters(cfg)
        if not names:
            log("还没有注册主角。用：")
            log("  python -m dig character add --name 小圆 --photo 照片.jpg --stylize")
            return 0
        log("已注册主角：")
        for n in names:
            c = char_mod.load_character(cfg, n)
            if c:
                log("  %-14s %s" % (n, c.name))
                log("  %-14s   特征：%s" % ("", (c.sheet or "")[:60]))
                log("  %-14s   定妆图：%s" % ("", c.style_ref or "（无，建议跑 stylize）"))
        return 0

    if args.char_cmd == "add":
        vision = make_text_engine(cfg.provider("vision"), cfg.root)
        char = char_mod.register_character(
            cfg, vision, name=args.name, photo=args.photo,
            char_id=args.id, persona=args.persona,
        )
        log("主角已登记：" + char.id)
        log("  特征：" + char.sheet)
        log("  标志：" + char.signature)
        if args.stylize:
            preset = style_mod.load_style(cfg, args.style or str(cfg.get("style")))
            image_engine = make_image_engine(cfg.provider("image"), cfg.root)
            char_mod.stylize_character(cfg, image_engine, char, preset)
        else:
            log("建议再跑一次定妆图，跨图一致性会明显变好：")
            log("  python -m dig character stylize --id %s --style %s"
                % (char.id, args.style or cfg.get("style")))
        log("出图时带上：--character " + char.id)
        return 0

    if args.char_cmd == "stylize":
        char = char_mod.load_character(cfg, args.id)
        if not char:
            raise DigError("找不到主角：" + str(args.id))
        preset = style_mod.load_style(cfg, args.style or str(cfg.get("style")))
        image_engine = make_image_engine(cfg.provider("image"), cfg.root)
        char_mod.stylize_character(cfg, image_engine, char, preset)
        return 0

    raise DigError("未知的 character 子命令")


# --------------------------------------------------------------------------- #
# doctor / ui
# --------------------------------------------------------------------------- #
def cmd_doctor(args) -> int:
    from . import fonts
    from .style import list_styles
    from .character import list_characters

    cfg = build_config(args)
    log("douyin-image-gen v" + __version__)
    log("Python " + sys.version.split()[0] + "  平台 " + sys.platform)
    log("")
    try:
        import PIL

        log("Pillow: " + getattr(PIL, "__version__", "?"))
    except Exception as exc:  # noqa: BLE001
        log("✗ Pillow 没装：pip install pillow  （%s）" % exc)
    try:
        import yaml  # noqa: F401

        log("PyYAML: ok")
    except Exception:
        log("△ PyYAML 没装，YAML 配置和风格预设不可用：pip install pyyaml")
    log("")
    log(fonts.report())
    log("")
    log("配置文件: " + (cfg.path or "（没找到，用内置默认值）"))
    log("输出目录: " + cfg.output_dir)
    log("成图尺寸: %sx%s" % (cfg.get("page.width"), cfg.get("page.height")))
    log("默认画风: " + str(cfg.get("style")))
    log("画风预设: " + (", ".join(list_styles(cfg)) or "（空）"))
    log("已注册主角: " + (", ".join(list_characters(cfg)) or "（空）"))
    log("")
    for kind in ("text", "vision", "image"):
        pc = cfg.provider(kind)
        state = "✓ 有 key" if pc.api_key else ("—" if pc.provider == "mock" else "✗ 缺 key（" + pc.api_key_env + "）")
        log("%-6s %-8s %-34s %s" % (kind, pc.provider, pc.model, state))
    log("")
    log("先跑通流程（不花钱）：python -m dig run --theme \"测试主题\" --offline")
    return 0


def cmd_ui(args) -> int:
    from .webui import serve

    cfg = build_config(args)
    serve(cfg, host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


# --------------------------------------------------------------------------- #
# 解析器
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dig",
        description="抖音图文轮播（双格科普漫画）一键生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  python -m dig doctor
  python -m dig run --theme "楼盘名字里的暗号" --offline
  python -m dig run --theme "楼盘名字里的暗号" --style retro_comic --handle your_douyin_id
  python -m dig character add --name 小圆 --photo me.jpg --stylize
  python -m dig run --theme "第一次租房避坑" --character 小圆
  python -m dig style add --from-image ref.jpg --name 复古港漫 --id hk_retro
  python -m dig batch --file topics.json
  python -m dig ui
""",
    )
    p.add_argument("--version", action="version", version="douyin-image-gen " + __version__)
    sub = p.add_subparsers(dest="cmd")

    # run
    r = sub.add_parser("run", help="一键出一整套图")
    add_common(r)
    add_style_args(r)
    r.add_argument("--theme", "-t", required=True, help="主题/选题，一句话")
    r.add_argument("--character", "-c", default="", help="主角 id（个人 IP）")
    r.add_argument("--pages", type=int, default=None, help="出几张图，5~7 推荐")
    r.add_argument("--panels", type=int, default=None, help="每张几格，默认 2")
    r.add_argument("--handle", default="", help="抖音号，写进页脚水印")
    r.add_argument("--angle", default="", help="切入角度，比如 '从新手视角'")
    r.add_argument("--audience", default="", help="目标观众，比如 '刚毕业的年轻人'")
    r.add_argument("--size", default="", help="成图尺寸，如 1440x1920")
    r.add_argument("--workers", type=int, default=0, help="并发生图数")
    r.add_argument("--seed", type=int, default=None, help="固定随机种子，便于复现")
    r.add_argument("--no-cache", action="store_true", help="不使用本地缓存")
    r.add_argument("--zip", action="store_true", help="额外打包成 zip")
    r.add_argument("--allow-text-in-image", action="store_true",
                   help="允许模型在画面里写字（默认禁止，文字由排版渲染）")
    r.add_argument("--strict", action="store_true", help="把体检警告也当成错误")
    r.add_argument("--no-validate", action="store_true", help="跳过脚本体检（不建议）")
    r.set_defaults(func=cmd_run)

    # script
    s = sub.add_parser("script", help="只生成脚本 JSON，不出图")
    add_common(s)
    add_style_args(s)
    s.add_argument("--theme", "-t", required=True)
    s.add_argument("--character", "-c", default="")
    s.add_argument("--pages", type=int, default=None)
    s.add_argument("--panels", type=int, default=None)
    s.add_argument("--handle", default="")
    s.add_argument("--angle", default="")
    s.add_argument("--audience", default="")
    s.set_defaults(func=cmd_script)

    # render
    d = sub.add_parser("render", help="用改好的脚本出图")
    add_common(d)
    add_style_args(d)
    d.add_argument("--script", required=True, help="script.json 路径")
    d.add_argument("--character", "-c", default="")
    d.add_argument("--handle", default="")
    d.add_argument("--skip-images", action="store_true", help="不重新生图，只重排文字")
    d.add_argument("--no-cache", action="store_true")
    d.add_argument("--zip", action="store_true")
    d.add_argument("--strict", action="store_true", help="把体检警告也当成错误")
    d.add_argument("--no-validate", action="store_true", help="跳过脚本体检（不建议）")
    d.set_defaults(func=cmd_render)

    # validate
    v = sub.add_parser("validate", help="只体检脚本，不生成（生图前先跑这个）")
    add_common(v)
    v.add_argument("--script", required=True, help="script.json 路径")
    v.add_argument("--style", default="", help="按指定画风体检")
    v.add_argument("--strict", action="store_true", help="把警告也当成错误")
    v.set_defaults(func=cmd_validate)

    # batch
    b = sub.add_parser("batch", help="批量跑一批选题")
    add_common(b)
    add_style_args(b)
    b.add_argument("--file", required=True, help="选题 JSON 文件")
    b.add_argument("--character", "-c", default="")
    b.add_argument("--pages", type=int, default=None)
    b.add_argument("--handle", default="")
    b.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    b.add_argument("--zip", action="store_true")
    b.set_defaults(func=cmd_batch)

    # style
    st = sub.add_parser("style", help="画风预设管理")
    st_sub = st.add_subparsers(dest="style_cmd")
    sl = st_sub.add_parser("list", help="列出所有预设")
    add_common(sl)
    ss = st_sub.add_parser("show", help="查看某个预设")
    add_common(ss)
    ss.add_argument("id")
    sa = st_sub.add_parser("add", help="从参考图反推画风，存成新预设")
    add_common(sa)
    sa.add_argument("--from-image", dest="from_image", required=True, help="参考图路径")
    sa.add_argument("--name", default="", help="中文名字")
    sa.add_argument("--id", default="", help="预设 id（英文，用于 --style）")
    for _p in (sl, ss, sa):
        _p.set_defaults(func=cmd_style)

    # character
    ch = sub.add_parser("character", help="主角（个人 IP）管理")
    ch_sub = ch.add_subparsers(dest="char_cmd")
    cl = ch_sub.add_parser("list", help="列出已注册主角")
    add_common(cl)
    ca = ch_sub.add_parser("add", help="上传照片登记主角")
    add_common(ca)
    ca.add_argument("--name", required=True, help="主角名字，如 小圆")
    ca.add_argument("--photo", required=True, help="人物照片路径")
    ca.add_argument("--id", default="", help="主角 id，默认由名字生成")
    ca.add_argument("--persona", default="", help="人设口吻，可留空由模型推断")
    ca.add_argument("--style", default="", help="定妆图使用的画风")
    ca.add_argument("--stylize", action="store_true", help="顺便生成风格化定妆图（推荐）")
    cs = ch_sub.add_parser("stylize", help="为已有主角生成定妆图")
    add_common(cs)
    cs.add_argument("--id", required=True)
    cs.add_argument("--style", default="")
    for _p in (cl, ca, cs):
        _p.set_defaults(func=cmd_character)

    # doctor
    doc = sub.add_parser("doctor", help="体检：依赖、字体、Key、预设")
    add_common(doc)
    doc.set_defaults(func=cmd_doctor)

    # ui
    ui = sub.add_parser("ui", help="打开本地网页版（可拖照片）")
    add_common(ui)
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-browser", action="store_true")
    ui.set_defaults(func=cmd_ui)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 1
    func = getattr(args, "func", None)
    if func is None:
        # 子命令没选具体动作，比如 `dig style`
        parser.parse_args([args.cmd, "--help"])
        return 1
    try:
        return func(args)
    except DigError as exc:
        print("\n✗ " + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
