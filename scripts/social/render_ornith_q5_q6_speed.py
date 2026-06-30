#!/usr/bin/env python3
"""Render Ornith Q5 vs Q6 speed/VRAM chart."""
from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "benchmarks" / "results" / "ornith-q5-q6-speed.png"

W, H = 1600, 900
SCALE = 2

BG = "#030405"
PANEL = "#080a0a"
GRID = "#2d2014"
GRID_SOFT = "#1a1612"
TEXT = "#f5e8d2"
MUTED = "#917a5c"
ORANGE = "#ff7018"
ORANGE_2 = "#ffa636"
ORANGE_3 = "#ffcc70"
ORANGE_DIM = "#823612"

MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

DATA = {
    "Q5_K_M": {
        "vram": 27.9,
        "short_pp": 3070,
        "short_tg": 113.6,
        "long_pp": 2548,
        "long_tg": 107.3,
    },
    "Q6_K": {
        "vram": 31.4,
        "short_pp": 3043,
        "short_tg": 107.8,
        "long_pp": 2450,
        "long_tg": 98.5,
    },
}


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size * SCALE)


FONTS = {
    "title": font(MONO_BOLD, 48),
    "subtitle": font(MONO, 24),
    "section": font(MONO_BOLD, 27),
    "label": font(MONO_BOLD, 25),
    "small": font(MONO, 19),
}


def px(value: int) -> int:
    return value * SCALE


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    fnt: ImageFont.FreeTypeFont,
    fill: str = TEXT,
    anchor: str | None = None,
) -> None:
    draw.text((px(xy[0]), px(xy[1])), value, font=fnt, fill=fill, anchor=anchor)


def draw_line(
    draw: ImageDraw.ImageDraw,
    a: tuple[int, int],
    b: tuple[int, int],
    fill: str = GRID,
    width: int = 1,
) -> None:
    draw.line([(px(a[0]), px(a[1])), (px(b[0]), px(b[1]))], fill=fill, width=px(width))


def draw_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    outline: str = GRID,
    fill: str | None = None,
    width: int = 1,
) -> None:
    draw.rectangle(tuple(px(v) for v in box), outline=outline, fill=fill, width=px(width))


def terminal_frame() -> Image.Image:
    img = Image.new("RGB", (W * SCALE, H * SCALE), BG)
    draw = ImageDraw.Draw(img)
    draw_rect(draw, (48, 46, 1552, 854), outline=GRID, fill=PANEL, width=2)
    draw_line(draw, (48, 102), (1552, 102), GRID, 1)
    draw_text(draw, (82, 65), "● ● ●", FONTS["subtitle"], ORANGE_DIM)
    draw_text(draw, (226, 64), "ORNITH 35B: Q5 VS Q6", FONTS["title"], TEXT)
    draw_text(
        draw,
        (82, 124),
        "full 256k context :: q8 kv :: b4096/ub2048 :: vulkan/r9700",
        FONTS["subtitle"],
        MUTED,
    )
    for x in range(80, 1530, 80):
        draw_line(draw, (x, 170), (x, 824), GRID_SOFT, 1)
    for y in range(190, 820, 60):
        draw_line(draw, (80, y), (1520, y), GRID_SOFT, 1)
    return img


def make_axis(fig: mpl.figure.Figure, rect: tuple[float, float, float, float], title: str):
    ax = fig.add_axes(rect)
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=MUTED, labelsize=13, length=0)
    for spine in ax.spines.values():
        spine.set_color(GRID)
        spine.set_linewidth(1.4)
    ax.grid(axis="x", color=GRID, linewidth=1.0)
    ax.set_axisbelow(True)
    ax.text(
        0.0,
        1.08,
        title,
        transform=ax.transAxes,
        color=MUTED,
        fontsize=17,
        fontweight="bold",
        fontfamily="DejaVu Sans Mono",
    )
    return ax


def add_labels(ax, bars, labels: list[str], color: str, pad: float) -> None:
    for bar, label in zip(bars, labels, strict=True):
        ax.text(
            bar.get_width() + pad,
            bar.get_y() + bar.get_height() / 2,
            label,
            va="center",
            ha="left",
            color=color,
            fontsize=17,
            fontweight="bold",
            fontfamily="DejaVu Sans Mono",
        )


def render_matplotlib_layer() -> Image.Image:
    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans Mono",
            "figure.facecolor": (0, 0, 0, 0),
            "savefig.facecolor": (0, 0, 0, 0),
            "axes.edgecolor": GRID,
            "xtick.color": MUTED,
            "ytick.color": TEXT,
            "text.color": TEXT,
        }
    )
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)

    names = list(DATA)
    y = np.arange(len(names))

    ax_vram = make_axis(fig, (0.095, 0.565, 0.37, 0.225), "VRAM FOOTPRINT (GB)")
    vram = [DATA[name]["vram"] for name in names]
    bars = ax_vram.barh(y, vram, height=0.42, color=[ORANGE, ORANGE_2])
    ax_vram.set_xlim(0, 34.2)
    ax_vram.set_yticks(y, names)
    ax_vram.set_xticks([0, 8, 16, 24, 32])
    ax_vram.invert_yaxis()
    add_labels(ax_vram, bars, [f"{value:.1f} GB" for value in vram], ORANGE_3, 0.55)

    ax_pp = make_axis(fig, (0.56, 0.565, 0.355, 0.225), "PROMPT PROCESSING (PP TOK/S)")
    short_pp = [DATA[name]["short_pp"] for name in names]
    long_pp = [DATA[name]["long_pp"] for name in names]
    h = 0.22
    bars_short = ax_pp.barh(y - h / 1.5, short_pp, height=h, color=ORANGE)
    bars_long = ax_pp.barh(y + h / 1.5, long_pp, height=h, color=ORANGE_3)
    ax_pp.set_xlim(0, 3300)
    ax_pp.set_yticks(y, names)
    ax_pp.set_xticks([0, 1000, 2000, 3000])
    ax_pp.invert_yaxis()
    add_labels(ax_pp, bars_short, [f"{value:.0f} short" for value in short_pp], ORANGE, 45)
    add_labels(ax_pp, bars_long, [f"{value:.0f} long" for value in long_pp], ORANGE_3, 45)

    ax_tg = make_axis(fig, (0.145, 0.205, 0.77, 0.22), "TOKEN GENERATION (TG TOK/S)")
    y2 = np.array([0, 1])
    q5_tg = [DATA["Q5_K_M"]["short_tg"], DATA["Q5_K_M"]["long_tg"]]
    q6_tg = [DATA["Q6_K"]["short_tg"], DATA["Q6_K"]["long_tg"]]
    bars_q5 = ax_tg.barh(y2 - h / 1.5, q5_tg, height=h, color=ORANGE)
    bars_q6 = ax_tg.barh(y2 + h / 1.5, q6_tg, height=h, color=ORANGE_2)
    ax_tg.set_xlim(0, 125)
    ax_tg.set_yticks(y2, ["short prompt", "long prompt"])
    ax_tg.set_xticks([0, 25, 50, 75, 100, 125])
    ax_tg.invert_yaxis()
    add_labels(ax_tg, bars_q5, [f"Q5 {value:.1f}" for value in q5_tg], ORANGE, 2.0)
    add_labels(ax_tg, bars_q6, [f"Q6 {value:.1f}" for value in q6_tg], ORANGE_2, 2.0)

    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())
    layer = Image.fromarray(buf.copy(), "RGBA")
    plt.close(fig)
    return layer.resize((W * SCALE, H * SCALE), Image.Resampling.LANCZOS)


def render() -> Path:
    img = terminal_frame().convert("RGBA")
    chart = render_matplotlib_layer()
    img.alpha_composite(chart)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    final = img.convert("RGB").resize((W, H), Image.Resampling.LANCZOS)
    final.save(OUT, optimize=True)
    return OUT


def main() -> None:
    print(render())


if __name__ == "__main__":
    main()
