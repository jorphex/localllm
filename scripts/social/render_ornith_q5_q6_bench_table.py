#!/usr/bin/env python3
"""Render Ornith Q5 vs Q6 benchmark-score table."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "benchmarks" / "results" / "ornith-q5-q6-bench-table.png"

W, H = 1800, 1100
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
GREEN = (122, 220, 122)

MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

ROWS = [
    ("VRAM footprint", "lower", "27.9 GB", "31.4 GB"),
    ("short prompt PP", "higher", "3070", "3043"),
    ("short prompt TG", "higher", "113.6", "107.8"),
    ("long prompt PP", "higher", "2548", "2450"),
    ("long prompt TG", "higher", "107.3", "98.5"),
    ("transcript fixtures", "higher", "2/5", "1/5"),
    ("transcript turns", "higher", "25/35", "24/35"),
    ("transcript partial", "higher", "0.9048", "0.8857"),
    ("coding sim pass", "higher", "7/8", "7/8"),
    ("coding sim scope", "higher", "7/8", "6/8"),
    ("tool-error-free", "higher", "8/8", "7/8"),
    ("agent score", "higher", "0.9000", "0.8438"),
    ("opencode diag", "higher", "0.86", "0.66"),
    ("coding smoke", "higher", "0.50", "0.25"),
    ("agentic barrage", "higher", "1.00", "0.85"),
]


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size * S)


F = {
    "title": font(MONO_BOLD, 54),
    "sub": font(MONO, 25),
    "head": font(MONO_BOLD, 30),
    "cell": font(MONO, 28),
    "cell_bold": font(MONO_BOLD, 30),
    "small": font(MONO, 21),
}


def p(v: int) -> int:
    return v * S


def xy(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    return tuple(p(v) for v in box)


def text(
    d: ImageDraw.ImageDraw,
    pos: tuple[int, int],
    value: str,
    fnt: ImageFont.FreeTypeFont,
    fill=TEXT,
    anchor: str | None = None,
) -> None:
    d.text((p(pos[0]), p(pos[1])), value, font=fnt, fill=fill, anchor=anchor)


def line(d: ImageDraw.ImageDraw, a: tuple[int, int], b: tuple[int, int], fill=GRID, width=1) -> None:
    d.line([(p(a[0]), p(a[1])), (p(b[0]), p(b[1]))], fill=fill, width=p(width))


def rect(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], outline=GRID, fill=None, width=1) -> None:
    d.rectangle(xy(box), outline=outline, fill=fill, width=p(width))


def fill_rect(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill) -> None:
    d.rectangle(xy(box), fill=fill)


def winner(row: tuple[str, str, str, str]) -> str:
    _, direction, q5, q6 = row
    if "/" in q5:
        q5_val = float(q5.split("/", 1)[0]) / float(q5.split("/", 1)[1])
        q6_val = float(q6.split("/", 1)[0]) / float(q6.split("/", 1)[1])
    else:
        q5_val = float(q5.replace(" GB", ""))
        q6_val = float(q6.replace(" GB", ""))
    if q5_val == q6_val:
        return "tie"
    if direction == "lower":
        return "Q5" if q5_val < q6_val else "Q6"
    return "Q5" if q5_val > q6_val else "Q6"


def terminal_frame() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W * S, H * S), BG)
    d = ImageDraw.Draw(img)
    rect(d, (48, 46, W - 48, H - 46), outline=GRID, fill=PANEL, width=2)
    line(d, (48, 102), (W - 48, 102), GRID, 1)
    text(d, (82, 65), "● ● ●", F["sub"], ORANGE_DIM)
    text(d, (226, 61), "ORNITH 35B BENCH TABLE", F["title"], TEXT)
    text(d, (82, 124), "q8 kv :: full 256k context :: b4096/ub2048 :: r9700/vulkan", F["sub"], MUTED)
    for x in range(80, W - 80, 80):
        line(d, (x, 170), (x, H - 80), GRID_SOFT, 1)
    for y in range(190, H - 80, 60):
        line(d, (80, y), (W - 80, y), GRID_SOFT, 1)
    return img, d


def render() -> Path:
    img, d = terminal_frame()

    left, top = 100, 205
    col_metric = (left, left + 565)
    col_q5 = (col_metric[1], col_metric[1] + 300)
    col_q6 = (col_q5[1], col_q5[1] + 300)
    col_win = (col_q6[1], col_q6[1] + 250)
    row_h = 52
    table_w = col_win[1] - left
    table_h = row_h * (len(ROWS) + 1)

    rect(d, (left, top, left + table_w, top + table_h), outline=GRID, fill=(5, 7, 7), width=2)
    header_y = top
    fill_rect(d, (left, header_y, left + table_w, header_y + row_h), (18, 13, 9))
    text(d, (col_metric[0] + 22, header_y + 13), "metric", F["head"], MUTED)
    text(d, (col_q5[0] + 22, header_y + 13), "Q5_K_M", F["head"], ORANGE)
    text(d, (col_q6[0] + 22, header_y + 13), "Q6_K", F["head"], ORANGE_2)
    text(d, (col_win[0] + 22, header_y + 13), "edge", F["head"], MUTED)

    for x in (col_metric[1], col_q5[1], col_q6[1]):
        line(d, (x, top), (x, top + table_h), GRID, 1)

    for i, row in enumerate(ROWS):
        y = top + row_h * (i + 1)
        if i % 2 == 0:
            fill_rect(d, (left, y, left + table_w, y + row_h), (10, 11, 10))
        line(d, (left, y), (left + table_w, y), GRID, 1)

        metric, _, q5, q6 = row
        win = winner(row)
        q5_color = ORANGE_3 if win in {"Q5", "tie"} else TEXT
        q6_color = ORANGE_3 if win in {"Q6", "tie"} else TEXT
        edge = "tie" if win == "tie" else win
        edge_color = MUTED if win == "tie" else GREEN

        text(d, (col_metric[0] + 22, y + 13), metric, F["cell"], TEXT)
        text(d, (col_q5[0] + 22, y + 11), q5, F["cell_bold"], q5_color)
        text(d, (col_q6[0] + 22, y + 11), q6, F["cell_bold"], q6_color)
        text(d, (col_win[0] + 22, y + 11), edge, F["cell_bold"], edge_color)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    final = img.resize((W, H), Image.Resampling.LANCZOS)
    final.save(OUT, optimize=True)
    return OUT


def main() -> None:
    print(render())


if __name__ == "__main__":
    main()
