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

# 退出码：Agent 靠它判断要不要去读 manifest.json
EXIT_OK = 0          # 全部成功
EXIT_PARTIAL = 1     # 跑完了，但有格子是占位图（或批量里有选题失败）—— 看 manifest.json 的 errors
EXIT_ERROR = 2       # 参数 / 配置 / 体检错误、Key 被拒：什么都没生成


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
    return _print_result(result)


def _print_result(result) -> int:
    """打印结果并返回退出码。有占位图就返回 1 —— 以前 0/12 全失败也返回 0。"""
    log("")
    log("成图目录：" + result["out_dir"])
    for f in result.get("files", []):
        log("  " + os.path.basename(f))
    if result.get("caption"):
        log("文案：" + result["caption"])
    if result.get("zip"):
        log("打包：" + result["zip"])
    if result.get("preview"):
        log("预览：" + result["preview"] + "（整套 + 手机里的样子，发布前看这一张）")
    billing = (result.get("stats") or {}).get("billing") or {}
    if billing.get("billed"):
        log("计费：本次实际发出 %d 次生图请求，详见 manifest.json 的 billing" % billing.get("requests", 0))
    deck = result.get("deck")
    if deck is not None:
        errs = [i + 1 for i, b in enumerate(deck.all_beats) if b.error]
        if errs:
            warn("第 %s 格生图失败（已用占位图兜底），详见 manifest.json；只重画这几格：\n"
                 "  python -m dig reroll --script \"%s\" --panel %s"
                 % ("、".join(map(str, errs)), os.path.join(result["out_dir"], "script.json"),
                    ",".join(map(str, errs))))
    return EXIT_OK if result.get("ok", True) else EXIT_PARTIAL


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


def render_out_dir(cfg: Config, script: str, explicit: str = "") -> str:
    """render 的输出目录。

    脚本就在某个作品目录里（output/ 下，或者目录里有上一轮的 manifest.json，
    比如 run --out ./out/task123 出来的）：原地更新，改完文案重排就是这么用的。
    其它地方的脚本（比如按 AGENTS.md 写在仓库根目录的 my-script.json）：新建
    output/<时间>_<主题>/ —— 以前直接写进脚本所在目录，pages/、panels/、
    manifest.json 散了一仓库根目录。
    """
    if explicit:
        return explicit
    sdir = os.path.dirname(os.path.abspath(script))
    out = os.path.abspath(cfg.output_dir)
    if sdir.startswith(out + os.sep) or os.path.isfile(os.path.join(sdir, "manifest.json")):
        return sdir
    return ""


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
        out_dir=render_out_dir(cfg, args.script, args.out),
        render_only=args.skip_images,
        zip_it=args.zip,
        strict=args.strict,
        skip_validation=args.no_validate,
    )
    return _print_result(result)


def _panel_list(values) -> list:
    out = []
    for v in values or []:
        for part in str(v).replace("，", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.append(int(part))
            except ValueError:
                raise DigError("--panel 要写数字，比如 --panel 3 或 --panel 3,7（收到：%s）" % part)
    return out


def cmd_reroll(args) -> int:
    """只重画指定的格，其余格原样沿用。"""
    from . import pipeline

    cfg = build_config(args)
    result = pipeline.reroll(
        cfg,
        script_path=args.script,
        panels=_panel_list(args.panel),
        scene=args.scene,
        caption=args.caption,
        style_id=args.style,
        character_id=args.character,
        strict=args.strict,
    )
    return _print_result(result)


def cmd_sheet(args) -> int:
    """先只画角色定妆图（1 次计费），看过满意再出整套。"""
    from . import charsheet, pipeline
    from .ledger import Ledger
    from .prompt_builder import panel_negative
    from .providers import make_image_engine
    from .util import ensure_dir, slugify

    cfg = build_config(args)
    deck = pipeline.load_deck(args.script) if args.script else None
    if deck is None and not args.character:
        raise DigError("给一个脚本（--script）或一个已登记的主角（--character）")
    character = pipeline.resolve_character(cfg, deck, args.character)
    if character is None:
        raise DigError("脚本里没有主角（character / character_id），没有定妆图可画")
    style = pipeline.resolve_style(cfg, args.style or (deck.style_id if deck else ""))

    user_ref = character.style_ref_for(style.id)
    if user_ref:
        log("%s 在 %s 画风下用的是 character stylize 生成的定妆图：%s" % (
            character.name or character.id, style.id, user_ref))
        log("要换这张图，重跑：python -m dig character stylize --id %s --style %s" % (character.id, style.id))
        return EXIT_OK

    if args.out:
        out_dir = args.out
    elif args.script and render_out_dir(cfg, args.script):
        out_dir = render_out_dir(cfg, args.script)
    else:
        out_dir = os.path.join(cfg.output_dir, "sheets",
                               "%s_%s" % (slugify(character.name or character.id or "主角", 16), style.id))
    ensure_dir(out_dir)
    pc = cfg.provider("image")
    if pc.provider != "mock":
        pc.require_key()            # 缺 Key 在花钱之前就说清楚
    engine = make_image_engine(pc, cfg.root)
    ledger = Ledger.for_engine(engine)
    path = charsheet.ensure_character_sheet(
        character, style, engine, cfg.cache_dir, out_dir,
        negative=panel_negative(style), use_cache=bool(cfg.get("run.cache", True)),
        redraw=args.redraw, ledger=ledger,
    )
    if not path:
        raise DigError("定妆图没画成，见上面的报错")
    log("")
    log("定妆图：" + path)
    log(ledger.render())
    log("打开看一眼：脸、发型、服装、标志性元素对不对。")
    log("  满意：直接出整套，这张会被缓存复用，不再计费")
    log("  不满意：改 character.sheet 的描述，或者重画一张：python -m dig sheet %s --redraw"
        % (("--script \"%s\"" % args.script) if args.script else ("--character " + args.character)))
    return EXIT_OK


# --------------------------------------------------------------------------- #
# batch
# --------------------------------------------------------------------------- #
def cmd_validate(args) -> int:
    """只体检，不生成。Agent 应该在花钱之前先跑这个。"""
    from . import pipeline, validate
    from .models import Deck

    cfg = build_config(args)
    deck = Deck.from_dict(pipeline.read_script(args.script))
    style = pipeline.resolve_style(cfg, args.style or deck.style_id)
    missing = None
    try:
        # 和 render 同一个口径：体检说有主角，出图就一定有主角
        character = pipeline.resolve_character(cfg, deck, args.character)
    except DigError as exc:
        character, missing = None, exc

    page_size = (int(cfg.get("page.width", 1792)), int(cfg.get("page.height", 2400)))
    issues = validate.validate_deck(deck, style, character, strict=args.strict,
                                    page_size=page_size, cfg=cfg)
    if missing is not None:
        issues = [i for i in issues if i.code != "no-character"]
        issues.insert(0, validate.Issue(
            "error", "脚本", "character-missing", str(missing).splitlines()[0],
            "用 dig character list 看已登记的主角，或者改用内联 character 块",
        ))
    log(validate.format_issues(issues))
    if validate.has_errors(issues):
        log("")
        log("有错误，生成会被拦下。改完再跑一次这条命令。")
        return EXIT_ERROR
    log("")
    log("可以生成了：python -m dig render --script \"%s\"" % args.script)
    return EXIT_OK


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
    ok = [r for r in results if not r.get("error") and r.get("ok", True)]
    log("\n批量完成：完整成功 %d / %d" % (len(ok), len(results)))
    for r in results:
        if r.get("error"):
            log("  ✗ %s：%s" % (r.get("theme"), r["error"]))
        elif not r.get("ok", True):
            log("  △ %s（有占位图，见 manifest.json）" % r["out_dir"])
        else:
            log("  ✓ " + r["out_dir"])
    return EXIT_OK if results and len(ok) == len(results) else EXIT_PARTIAL


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
                refs = "、".join("%s" % k for k in sorted(c.style_refs)) or "（无，出图时会按画风自动生成）"
                log("  %-14s   定妆图：%s" % ("", refs))
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
            log("出图时会按画风自动用照片画一张定妆图（每个画风一张，缓存复用）。")
            log("想先看一眼：python -m dig sheet --character %s --style %s"
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
    log("douyin-carousel-generator v" + __version__)
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
  python -m dig validate --script my-script.json
  python -m dig sheet --script my-script.json
  python -m dig render --script my-script.json
  python -m dig reroll --script output/xxx/script.json --panel 7
  python -m dig style add --from-image ref.jpg --name 复古港漫 --id hk_retro
  python -m dig batch --file topics.json
  python -m dig ui
""",
    )
    p.add_argument("--version", action="version", version="douyin-carousel-generator " + __version__)
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

    # reroll
    rr = sub.add_parser("reroll", help="只重画指定的格，其余沿用（1 格 = 1 次计费）")
    add_common(rr)
    add_style_args(rr)
    rr.add_argument("--script", required=True, help="作品目录里的 script.json")
    rr.add_argument("--panel", "-p", action="append", required=True,
                    help="第几格（从 1 数），可重复或写成 3,7")
    rr.add_argument("--scene", default="", help="顺便换掉这一格的画面描述（只能配合单格）")
    rr.add_argument("--caption", default="", help="顺便换掉这一格的短标题（只能配合单格）")
    rr.add_argument("--character", "-c", default="")
    rr.add_argument("--strict", action="store_true", help="把体检警告也当成错误")
    rr.set_defaults(func=cmd_reroll)

    # sheet
    sh = sub.add_parser("sheet", help="只画角色定妆图（1 次计费），满意再出整套")
    add_common(sh)
    add_style_args(sh)
    sh.add_argument("--script", default="", help="脚本（用它的主角和画风）")
    sh.add_argument("--character", "-c", default="", help="已登记的主角 id")
    sh.add_argument("--redraw", action="store_true", help="不要缓存里那张，重画一张（再计费一次）")
    sh.set_defaults(func=cmd_sheet)

    # validate
    v = sub.add_parser("validate", help="只体检脚本，不生成（生图前先跑这个）")
    add_common(v)
    v.add_argument("--script", required=True, help="script.json 路径")
    v.add_argument("--style", default="", help="按指定画风体检")
    v.add_argument("--character", "-c", default="", help="按指定主角体检")
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
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
