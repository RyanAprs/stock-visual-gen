"""stockgen CLI — render original clips + Adobe Stock CSV metadata."""
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .config import Config
from . import checks as checks_mod
from . import render as render_mod
from . import metadata as meta_mod
from . import assets as assets_mod
from . import vector as vector_mod

console = Console()

ALL_SKETCHES = ["particles", "gradient", "waves", "nebula", "data"]


def cmd_doctor(args) -> int:
    cfg = Config.load(args.config)
    console.print("[bold]stockgen doctor[/]")
    t = Table()
    t.add_column("Check"); t.add_column("OK"); t.add_column("Detail")
    ok_all = True
    for name, ok, detail in checks_mod.doctor(cfg):
        t.add_row(name, "[green]✓[/]" if ok else "[red]✗[/]", detail)
        ok_all = ok_all and ok
    console.print(t)
    return 0 if ok_all else 1


def _batch_dir(cfg, name: str | None) -> Path:
    name = name or datetime.now().strftime("batch_%Y%m%d_%H%M%S")
    d = cfg.output_dir / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _do_render(cfg, sketches, count, seed_start, batch, aspect) -> list[dict]:
    manifest_path = batch / "clips.json"
    clips = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    idx = len(clips)
    reg = assets_mod.Registry.load(batch)
    for sketch in sketches:
        for k in range(count):
            seed = seed_start + k
            idx += 1
            suffix = "_v" if aspect == "9:16" else ""
            out_mp4 = batch / f"clip_{idx:03d}{suffix}.mp4"
            console.print(f"[cyan]▶ render[/] {sketch} seed={seed} [{aspect or '16:9'}] → {out_mp4.name}")
            info = render_mod.render_clip(cfg, sketch, seed, out_mp4, cfg.cache_dir, aspect=aspect)
            clips.append(info)
            manifest_path.write_text(json.dumps(clips, indent=2))
            # register as ORIGINAL IP (rendered by stockgen)
            reg.add(assets_mod.Asset(
                file=info.get("file", out_mp4.name),
                kind=assets_mod.KIND_VIDEO,
                source=assets_mod.SOURCE_ORIGINAL,
                sketch=sketch, seed=seed,
                width=info.get("width"), height=info.get("height"),
                aspect=info.get("aspect", aspect or "16:9"),
            ))
            reg.save()
            console.print(f"  [green]✓[/] {out_mp4.name} ({info['width']}x{info['height']}, {info['duration']}s)")
    return clips


def cmd_render(args) -> int:
    cfg = Config.load(args.config)
    sketches = [args.sketch] if args.sketch and args.sketch != "all" else ALL_SKETCHES
    batch = _batch_dir(cfg, args.batch)
    aspect = getattr(args, "aspect", "16:9")
    try:
        clips = _do_render(cfg, sketches, args.count, args.seed_start, batch, aspect)
    except Exception as e:
        console.print(f"  [red]✗ {e}[/]")
        return 3
    console.print(f"\n[green]✓ {len(clips)} clips[/] in {batch}")
    console.print("[dim]Next: stockgen metadata --batch " + batch.name + "[/]")
    return 0


def cmd_metadata(args) -> int:
    cfg = Config.load(args.config)
    if args.batch:
        batch = cfg.output_dir / args.batch
    else:
        # newest batch
        batches = sorted(cfg.output_dir.glob("batch_*"), key=lambda p: p.stat().st_mtime)
        if not batches:
            console.print("[red]no batches found[/]"); return 2
        batch = batches[-1]

    provider = cfg.get("metadata.provider", "ollama")

    # registry-driven path (multi-kind: video/image/vector)
    reg = assets_mod.Registry.load(batch)
    if reg.assets:
        errs = reg.validate()
        if errs:
            console.print(f"[red]✗ guardrail: {len(errs)} non-sellable asset(s) — refusing.[/]")
            for e in errs:
                console.print(f"  [red]•[/] {e}")
            return 1
        kind_filter = getattr(args, "kind", "all")
        if kind_filter and kind_filter != "all":
            sel = assets_mod.Registry(reg.path, reg.of_kind(kind_filter))
        else:
            sel = reg
        console.print(f"[bold]metadata[/] ({provider}) for {len(sel.assets)} assets in {batch.name}")
        written = meta_mod.build_per_kind_csvs(cfg, sel, batch)
        for kind, path in written.items():
            console.print(f"  [green]✓ {kind}[/] → {path.name} ({len(sel.of_kind(kind))} rows)")
        _write_upload_checklist(batch, reg)  # checklist always from FULL registry
        console.print(f"\n[green]✓ CSV(s) + upload_checklist.txt[/] in {batch}")
        return 0

    # legacy path: clips.json only (video)
    manifest = batch / "clips.json"
    if not manifest.exists():
        console.print(f"[red]no registry.json or clips.json in {batch}[/]"); return 2
    clips = json.loads(manifest.read_text())
    console.print(f"[bold]metadata[/] ({provider}) for {len(clips)} clips in {batch.name}")
    rows = []
    for c in clips:
        row = meta_mod.gen_for_clip(cfg, c)
        rows.append(row)
        console.print(f"  [green]✓[/] {row['Filename']}: {row['Title'][:60]}")
    out_csv = meta_mod.write_csv(rows, batch / "metadata.csv")
    console.print(f"\n[green]✓ CSV:[/] {out_csv}")
    console.print("[dim]Upload clips + this CSV to Adobe Stock contributor portal.[/]")
    return 0


def _write_upload_checklist(batch, reg) -> None:
    ai_assets = [a for a in reg.assets if a.is_ai]
    lines = [
        "Adobe Stock upload checklist",
        "=" * 32,
        f"batch: {batch.name}",
        f"total sellable assets: {len(reg.assets)}",
        "",
        "Per-kind CSV: upload the matching metadata_<kind>.csv with each asset group.",
        "Vector: upload the .eps + JPEG preview (keep .svg as local master).",
        "Video: min 4MP (4K = 3840x2160 is safe). Image: min 4MP, sRGB.",
        "",
    ]
    if ai_assets:
        lines += [
            "AI-GENERATED ASSETS — you MUST tick 'Created using generative AI tools'",
            "in the contributor portal for each of these (CSV has no AI column):",
        ]
        lines += [f"  • {a.file}  (source={a.source})" for a in ai_assets]
        lines += [
            "",
            "Confirm your Google Flow/Veo plan grants COMMERCIAL rights (paid plan).",
            "Free/trial output is NOT licensed for stock resale.",
        ]
    else:
        lines.append("No AI assets in this batch — no AI disclosure needed.")
    (batch / "upload_checklist.txt").write_text("\n".join(lines) + "\n")


def cmd_batch(args) -> int:
    """render + metadata in one go."""
    rc = cmd_render(args)
    if rc != 0:
        return rc
    return cmd_metadata(args)


def _ask(prompt: str, options: list[str], default: str) -> str:
    """Simple interactive picker; returns default on empty/non-tty."""
    import sys
    if not sys.stdin.isatty():
        return default
    console.print(f"\n[bold]{prompt}[/]")
    for i, o in enumerate(options, 1):
        tag = " [dim](default)[/]" if o == default else ""
        console.print(f"  {i}. {o}{tag}")
    try:
        raw = input("> ").strip()
    except EOFError:
        return default
    if not raw:
        return default
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    return raw


def cmd_generate(args) -> int:
    """Interactive: pick aspect ratio(s) + compile-vs-individual, then render (+compile) + metadata."""
    cfg = Config.load(args.config)
    sketches = [args.sketch] if args.sketch and args.sketch != "all" else ALL_SKETCHES

    # 1) aspect
    aspect_choice = args.aspect or _ask(
        "Aspect ratio?", ["16:9 (landscape / stock)", "9:16 (vertical / shorts)", "both"], "16:9 (landscape / stock)")
    aspects = []
    if aspect_choice.startswith("16:9"): aspects = ["16:9"]
    elif aspect_choice.startswith("9:16"): aspects = ["9:16"]
    elif aspect_choice == "both": aspects = ["16:9", "9:16"]
    elif aspect_choice in ("16:9", "9:16"): aspects = [aspect_choice]
    else: aspects = ["16:9"]

    # 2) mode
    mode = args.mode or _ask(
        "Output mode?", ["individual (separate loop clips + CSV)", "compile (join clips into one video + music)"],
        "individual (separate loop clips + CSV)")
    mode = "compile" if mode.startswith("compile") else "individual"

    batch = _batch_dir(cfg, args.batch)
    all_clips: list[dict] = []
    for asp in aspects:
        try:
            clips = _do_render(cfg, sketches, args.count, args.seed_start, batch, asp)
        except Exception as e:
            console.print(f"  [red]✗ render failed: {e}[/]")
            return 3
        all_clips = clips  # manifest accumulates

    if mode == "compile":
        from . import assemble as asm
        for asp in aspects:
            asp_clips = [c for c in all_clips if c.get("aspect", "16:9") == asp]
            if not asp_clips:
                continue
            tag = "vertical" if asp == "9:16" else "landscape"
            try:
                out = asm.compile_clips(cfg, asp_clips, batch, out_name=f"compiled_{tag}.mp4")
                console.print(f"[green]✓ compiled[/] {tag}: {out}")
            except Exception as e:
                console.print(f"  [red]✗ compile {tag} failed: {e}[/]")
    else:
        # individual clips -> Adobe Stock CSV
        rows = [meta_mod.gen_for_clip(cfg, c) for c in all_clips]
        out_csv = meta_mod.write_csv(rows, batch / "metadata.csv")
        console.print(f"[green]✓ CSV:[/] {out_csv}")

    console.print(f"\n[green]✓ done[/] → {batch}")
    return 0


def cmd_assets(args) -> int:
    """List/validate the IP-source registry for a batch."""
    cfg = Config.load(args.config)
    if args.batch:
        batch = cfg.output_dir / args.batch
    else:
        batches = sorted(cfg.output_dir.glob("batch_*"), key=lambda p: p.stat().st_mtime)
        if not batches:
            console.print("[red]no batches found[/]"); return 2
        batch = batches[-1]
    reg = assets_mod.Registry.load(batch)
    if not reg.assets:
        console.print(f"[yellow]no assets registered in {batch.name}[/]"); return 0
    t = Table(title=f"assets — {batch.name}")
    t.add_column("File"); t.add_column("Kind"); t.add_column("Source")
    t.add_column("AI"); t.add_column("Sellable")
    for a in reg.assets:
        t.add_row(a.file, a.kind, a.source,
                  "[yellow]yes[/]" if a.is_ai else "no",
                  "[green]✓[/]" if a.sellable else "[red]✗ BLOCKED[/]")
    console.print(t)
    errs = reg.validate()
    if errs:
        console.print(f"\n[red]✗ {len(errs)} guardrail violation(s):[/]")
        for e in errs:
            console.print(f"  [red]•[/] {e}")
        return 1
    console.print(f"\n[green]✓ all {len(reg.assets)} assets sellable[/]")
    return 0


def cmd_vector(args) -> int:
    """Generate original flat-vector assets (SVG master + EPS + JPEG preview)."""
    cfg = Config.load(args.config)
    styles = vector_mod.VECTOR_STYLES if args.style == "all" else [args.style]
    batch = _batch_dir(cfg, args.batch)
    vec_dir = batch / "vector"
    reg = assets_mod.Registry.load(batch)
    idx = len(reg.of_kind(assets_mod.KIND_VECTOR))
    made = 0
    for style in styles:
        for k in range(args.count):
            seed = args.seed_start + k
            idx += 1
            console.print(f"[cyan]▶ vector[/] {style} seed={seed} → vec_{idx:03d}")
            try:
                info = vector_mod.render_vector(style, seed, vec_dir, idx)
            except Exception as e:
                console.print(f"  [red]✗ {e}[/]"); return 3
            reg.add(assets_mod.Asset(
                file=f"vector/{info['file']}", kind=assets_mod.KIND_VECTOR,
                source=assets_mod.SOURCE_ORIGINAL, sketch=style, seed=seed,
                width=info["width"], height=info["height"],
            ))
            reg.save()
            made += 1
            console.print(f"  [green]✓[/] {info['file']} + .svg + preview.jpg")
    console.print(f"\n[green]✓ {made} vectors[/] in {vec_dir}")
    console.print(f"[dim]Next: stockgen metadata --batch {batch.name} --kind vector[/]")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="stockgen",
                                description="Generate ORIGINAL motion-graphics clips + Adobe Stock CSV")
    p.add_argument("--config", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check environment").set_defaults(func=cmd_doctor)

    for name, fn in (("render", cmd_render), ("batch", cmd_batch)):
        r = sub.add_parser(name, help=f"{name} clips")
        r.add_argument("--sketch", default="all", help="sketch name or 'all' (" + ", ".join(ALL_SKETCHES) + ")")
        r.add_argument("--count", type=int, default=3, help="clips per sketch")
        r.add_argument("--seed-start", type=int, default=100, dest="seed_start")
        r.add_argument("--batch", default=None, help="batch dir name (default: timestamp)")
        r.add_argument("--aspect", default="16:9", choices=["16:9", "9:16"], help="aspect ratio")
        r.set_defaults(func=fn)

    g = sub.add_parser("generate", help="interactive: aspect + compile/individual, then render + metadata")
    g.add_argument("--sketch", default="all", help="sketch name or 'all'")
    g.add_argument("--count", type=int, default=2, help="clips per sketch")
    g.add_argument("--seed-start", type=int, default=100, dest="seed_start")
    g.add_argument("--batch", default=None)
    g.add_argument("--aspect", default=None, help="16:9 | 9:16 | both (skips prompt)")
    g.add_argument("--mode", default=None, help="individual | compile (skips prompt)")
    g.set_defaults(func=cmd_generate)

    m = sub.add_parser("metadata", help="generate Adobe Stock CSV for a batch")
    m.add_argument("--batch", default=None, help="batch dir name (default: newest)")
    m.add_argument("--kind", default="all", choices=["all", "video", "image", "vector"],
                   help="limit CSV to one asset kind (default: all)")
    m.set_defaults(func=cmd_metadata)

    a = sub.add_parser("assets", help="list/validate the IP-source registry for a batch")
    a.add_argument("--batch", default=None, help="batch dir name (default: newest)")
    a.set_defaults(func=cmd_assets)

    vec = sub.add_parser("vector", help="generate original flat-vector assets (SVG+EPS+preview)")
    vec.add_argument("--style", default="all",
                     help="style or 'all' (" + ", ".join(vector_mod.VECTOR_STYLES) + ")")
    vec.add_argument("--count", type=int, default=3, help="vectors per style")
    vec.add_argument("--seed-start", type=int, default=100, dest="seed_start")
    vec.add_argument("--batch", default=None, help="batch dir name (default: timestamp)")
    vec.set_defaults(func=cmd_vector)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
