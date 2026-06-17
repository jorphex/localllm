#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "social" / "x"

W, H = 1600, 900
S = 2

BG = (3, 4, 5)
PANEL = (8, 10, 10)
GRID = (45, 32, 20)
GRID_SOFT = (26, 22, 18)
TEXT = (245, 232, 210)
MUTED = (145, 122, 92)
ORANGE = (255, 112, 24)
ORANGE_2 = (255, 166, 54)
ORANGE_3 = (255, 204, 112)
ORANGE_DIM = (130, 54, 18)
RED_ORANGE = (225, 71, 20)

MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size * S)


F = {
    "title": font(MONO_BOLD, 48),
    "sub": font(MONO, 25),
    "axis": font(MONO, 25),
    "label": font(MONO_BOLD, 31),
    "small": font(MONO, 18),
    "value": font(MONO_BOLD, 35),
    "big": font(MONO_BOLD, 40),
    "huge": font(MONO_BOLD, 42),
}


def p(v: int) -> int:
    return v * S


def xy(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    return tuple(p(v) for v in box)


def text(
    d: ImageDraw.ImageDraw,
    pos: tuple[int, int],
    s: str,
    fnt: ImageFont.FreeTypeFont,
    fill=TEXT,
    anchor: str | None = None,
) -> None:
    d.text((p(pos[0]), p(pos[1])), s, font=fnt, fill=fill, anchor=anchor)


def line(d: ImageDraw.ImageDraw, a: tuple[int, int], b: tuple[int, int], fill=GRID, width=1) -> None:
    d.line([(p(a[0]), p(a[1])), (p(b[0]), p(b[1]))], fill=fill, width=p(width))


def rect(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], outline=GRID, fill=None, width=1) -> None:
    d.rectangle(xy(box), outline=outline, fill=fill, width=p(width))


def fill_rect(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill) -> None:
    d.rectangle(xy(box), fill=fill)


def terminal(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W * S, H * S), BG)
    d = ImageDraw.Draw(img)
    rect(d, (48, 46, 1552, 854), outline=GRID, fill=PANEL, width=2)
    line(d, (48, 102), (1552, 102), GRID, 1)
    text(d, (82, 65), "● ● ●", F["axis"], ORANGE_DIM)
    text(d, (226, 64), title.upper(), F["title"], TEXT)
    text(d, (82, 124), subtitle, F["sub"], MUTED)
    for x in range(80, 1530, 80):
        line(d, (x, 170), (x, 824), GRID_SOFT, 1)
    for y in range(190, 820, 60):
        line(d, (80, y), (1520, y), GRID_SOFT, 1)
    return img, d


def save(img: Image.Image, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    img.resize((W, H), Image.Resampling.LANCZOS).save(path, optimize=True)
    print(path)


def bar_chart(
    d: ImageDraw.ImageDraw,
    labels: list[str],
    values: list[float],
    displays: list[str],
    colors: list[tuple[int, int, int]],
    *,
    box=(160, 245, 1450, 730),
    ymax: float,
    yunit: str,
) -> None:
    x1, y1, x2, y2 = box
    rect(d, box, outline=GRID, fill=None, width=1)
    for tick in range(0, int(ymax) + 1, max(1, int(ymax // 5))):
        y = y2 - int((tick / ymax) * (y2 - y1))
        line(d, (x1, y), (x2, y), GRID, 1)
        text(d, (x1 - 54, y - 13), str(tick), F["axis"], MUTED)
    text(d, (x1 - 80, y1 - 34), yunit, F["axis"], MUTED)
    n = len(labels)
    gap = 82
    bar_w = (x2 - x1 - gap * (n + 1)) // n
    for i, (label, val, display, color) in enumerate(zip(labels, values, displays, colors, strict=True)):
        bx = x1 + gap + i * (bar_w + gap)
        bh = int((val / ymax) * (y2 - y1))
        fill_rect(d, (bx, y2 - bh, bx + bar_w, y2), color)
        rect(d, (bx, y2 - bh, bx + bar_w, y2), outline=ORANGE_3, width=1)
        text(d, (bx + bar_w // 2, y2 - bh - 42), display, F["value"], color, "mm")
        text(d, (bx + bar_w // 2, y2 + 28), label, F["label"], TEXT, "ma")


def grouped_bars(
    d: ImageDraw.ImageDraw,
    labels: list[str],
    series: list[tuple[str, list[float], list[str], tuple[int, int, int]]],
    *,
    box=(405, 250, 1348, 740),
    xmax: float | list[float],
    label_x: int = 92,
    value_x_pad: int = 34,
) -> None:
    x1, y1, x2, y2 = box
    row_h = (y2 - y1) // len(labels)
    for tick in [0, 0.25, 0.5, 0.75, 1.0]:
        x = x1 + int((x2 - x1) * tick)
        line(d, (x, y1), (x, y2), GRID, 1)
    for idx, label in enumerate(labels):
        cy = y1 + idx * row_h + row_h // 2
        text(d, (label_x, cy - 24), label, F["label"], TEXT)
        row_max = xmax[idx] if isinstance(xmax, list) else xmax
        for sidx, (_, vals, displays, color) in enumerate(series):
            by = cy - 30 + sidx * 42
            bw = int((vals[idx] / row_max) * (x2 - x1))
            fill_rect(d, (x1, by, x1 + bw, by + 28), color)
            rect(d, (x1, by, x2, by + 28), outline=GRID, width=1)
            text(d, (x2 + value_x_pad, by - 7), displays[idx], F["value"], color)
    lx = label_x
    for name, _, _, color in series:
        fill_rect(d, (lx, 184, lx + 30, 214), color)
        text(d, (lx + 46, 179), name, F["label"], MUTED)
        lx += 330


def render_2_shapes() -> None:
    img, d = terminal("qwen 3.6 shape map", "x=context tokens :: y=decode tok/s")
    x1, y1, x2, y2 = 220, 255, 1390, 710
    rect(d, (x1, y1, x2, y2), outline=GRID, fill=None, width=1)
    for ctx in [100, 120, 140, 160, 180]:
        x = x1 + int(((ctx - 100) / 80) * (x2 - x1))
        line(d, (x, y1), (x, y2), GRID, 1)
        text(d, (x, y2 + 32), f"{ctx}k", F["axis"], MUTED, "ma")
    for spd in [20, 40, 60, 80, 100]:
        y = y2 - int(((spd - 20) / 80) * (y2 - y1))
        line(d, (x1, y), (x2, y), GRID, 1)
        text(d, (x1 - 70, y - 14), str(spd), F["axis"], MUTED)
    text(d, (x1 - 100, y1 - 42), "tok/s", F["axis"], MUTED)
    points = [
        ("27B MTP", 128, 47.5, ORANGE_3),
        ("35B A3B", 160, 89, ORANGE),
    ]
    for label, ctx, spd, color in points:
        x = x1 + int(((ctx - 100) / 80) * (x2 - x1))
        y = y2 - int(((spd - 20) / 80) * (y2 - y1))
        d.ellipse(xy((x - 18, y - 18, x + 18, y + 18)), fill=color, outline=TEXT, width=p(2))
        text(d, (x + 34, y - 50), label, F["label"], color)
        text(d, (x + 34, y - 10), f"{ctx}k / {int(spd) if spd == 89 else '45-50'}", F["axis"], TEXT)
    save(img, "1-qwen-shapes-context.png")


def render_2_metrics() -> None:
    img, d = terminal("best local shapes", "27b mtp q6 vs 35b a3b q6")
    grouped_bars(
        d,
        ["PP", "TG", "CTX", "VRAM"],
        [
            ("27B MTP", [637, 47.5, 128, 29.56], ["637", "45-50", "128k", "29.56"], ORANGE_3),
            ("35B A3B", [2570, 89, 160, 33.03], ["2570", "89", "160k", "33.03"], ORANGE),
        ],
        xmax=[2700, 100, 180, 34.21],
        label_x=92,
    )
    save(img, "1-qwen-shapes-metrics.png")


def render_3() -> None:
    img, d = terminal("huihui vs unsloth mtp", "qwen 3.6 27b mtp q6 :: 128k q8 kv")
    grouped_bars(
        d,
        ["PP", "short TG", "long TG", "draft n"],
        [
            ("Huihui", [637, 45.2, 49.8, 3], ["637", "45", "50", "3"], ORANGE),
            ("Unsloth", [638, 43.4, 40.5, 2], ["638", "43", "40", "2"], ORANGE_3),
        ],
        xmax=[650, 55, 55, 5],
    )
    save(img, "2-mtp-builds.png")


def render_5() -> None:
    img, d = terminal("newer llama.cpp was not faster", "same qwen 3.6 35b stack :: old pinned vs newer test")
    grouped_bars(
        d,
        ["PP", "warmed TG"],
        [
            ("old", [1269, 118], ["1269", "118"], ORANGE_3),
            ("new", [1263, 86], ["1263", "86"], ORANGE),
        ],
        xmax=[1300, 125],
        box=(405, 310, 1315, 640),
    )
    save(img, "3-runtime-llamacpp.png")


def render_6() -> None:
    img, d = terminal("context cliff heatmap", "context x kv precision x decode speed")
    headers = ["shape", "kv", "tg", "read"]
    xs = [112, 500, 710, 940]
    for x, h in zip(xs, headers, strict=True):
        text(d, (x, 230), h.upper(), F["label"], MUTED)
    rows = [
        ("27B 128k", "q8", "45-50", "BEST", ORANGE),
        ("27B 256k", "q8", "22-25", "SLOW", ORANGE_DIM),
        ("27B 256k", "q4", "41-44", "TRADE", ORANGE_3),
        ("35B 160k", "q8", "89", "FAST", ORANGE),
        ("35B 256k", "q4", "95*", "TRADE", ORANGE_3),
    ]
    y = 294
    for name, kv, tg, read, color in rows:
        rect(d, (96, y - 12, 1430, y + 56), outline=GRID, fill=None, width=1)
        text(d, (xs[0], y), name, F["label"], TEXT)
        text(d, (xs[1], y - 2), kv, F["value"], color)
        text(d, (xs[2], y - 2), tg, F["value"], color)
        fill_rect(d, (xs[3], y - 6, xs[3] + 260, y + 38), color)
        text(d, (xs[3] + 284, y), read, F["label"], color)
        y += 86
    save(img, "1-qwen-shapes-context-cliff.png")


def render_7() -> None:
    img, d = terminal("vram residency budget", "current qwen 27b stack sidecar placement")
    total = 34.21
    rows = [
        ("main + cpu sidecars", 29.57, ORANGE_3),
        ("main + gpu embed", 32.46, ORANGE_2),
        ("main + gpu rerank", 32.71, ORANGE),
    ]
    y = 292
    x0, width = 505, 700
    for label, used, color in rows:
        text(d, (100, y + 8), label, F["label"], TEXT)
        fill_rect(d, (x0, y, x0 + width, y + 54), GRID)
        fill_rect(d, (x0, y, x0 + int(width * used / total), y + 54), color)
        text(d, (1248, y - 2), f"{used:.2f} GB", F["huge"], color)
        text(d, (1248, y + 52), f"{total - used:.2f} free", F["axis"], MUTED)
        y += 124
    save(img, "4-stack-vram-budget.png")


def render_8() -> None:
    img, d = terminal("vulkan vs hip/rocm", "amd ai pro r9700 32gb")
    labels = ["exact OK", "direct probe"]
    series = [
        ("Vulkan", [31.14, 30.78], ["31.1", "30.8"], ORANGE_3),
        ("HIP", [25.88, 25.75], ["25.9", "25.8"], ORANGE),
    ]
    x1, y1, x2, y2 = 390, 312, 1328, 650
    row_h = (y2 - y1) // len(labels)
    for tick in [0, 0.25, 0.5, 0.75, 1.0]:
        x = x1 + int((x2 - x1) * tick)
        line(d, (x, y1), (x, y2), GRID, 1)
    for idx, label in enumerate(labels):
        cy = y1 + idx * row_h + row_h // 2
        text(d, (92, cy - 24), label, F["value"], TEXT)
        for sidx, (_, vals, displays, color) in enumerate(series):
            by = cy - 30 + sidx * 42
            bw = int((vals[idx] / 34) * (x2 - x1))
            fill_rect(d, (x1, by, x1 + bw, by + 28), color)
            rect(d, (x1, by, x2, by + 28), outline=GRID, width=1)
            text(d, (x2 + 34, by - 7), displays[idx], F["value"], color)
    lx = 92
    for name, _, _, color in series:
        fill_rect(d, (lx, 184, lx + 30, 214), color)
        text(d, (lx + 46, 179), name, F["label"], MUTED)
        lx += 280
    save(img, "3-runtime-backend.png")


def render_9() -> None:
    img, d = terminal("current stack residency", "main + embed + rerank + tts + cache/flush")
    cols = ["main", "embed", "rerank", "tts", "cache", "flush"]
    rows = ["GPU", "CPU", "state", "timer"]
    matrix = [
        [1.0, 0.0, 1.0, 0.0, 0.6, 0.0],
        [0.2, 1.0, 0.2, 1.0, 0.3, 0.2],
        [0.4, 0.0, 0.0, 0.0, 1.0, 0.6],
        [0.0, 0.0, 0.0, 0.0, 0.2, 1.0],
    ]
    x0, y0, cell_w, cell_h = 390, 280, 158, 98
    for i, col in enumerate(cols):
        text(d, (x0 + i * cell_w + 8, y0 - 50), col, F["axis"], MUTED)
    for r, row in enumerate(rows):
        text(d, (112, y0 + r * cell_h + 28), row, F["label"], TEXT)
        for c, val in enumerate(matrix[r]):
            intensity = int(35 + val * 220)
            color = (intensity, max(36, int(intensity * 0.43)), 12)
            fill_rect(d, (x0 + c * cell_w, y0 + r * cell_h, x0 + (c + 1) * cell_w - 10, y0 + (r + 1) * cell_h - 10), color if val else (16, 16, 14))
            rect(d, (x0 + c * cell_w, y0 + r * cell_h, x0 + (c + 1) * cell_w - 10, y0 + (r + 1) * cell_h - 10), outline=GRID)
    save(img, "4-stack-residency-map.png")


def main() -> None:
    render_2_shapes()
    render_2_metrics()
    render_3()
    render_5()
    render_6()
    render_7()
    render_8()
    render_9()


if __name__ == "__main__":
    main()
