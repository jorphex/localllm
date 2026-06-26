#!/usr/bin/env python3
"""Render Radeon AI PRO R9700 compute/bandwidth peak chart."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "social" / "x"
DATA_DIR = ROOT / "benchmarks" / "results" / "gpu-peak"

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
GREEN = (120, 220, 120)

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


def plain_terminal(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """Clean dark panel without the dense background grid."""
    img = Image.new("RGB", (W * S, H * S), BG)
    d = ImageDraw.Draw(img)
    rect(d, (48, 46, 1552, 854), outline=GRID, fill=PANEL, width=2)
    line(d, (48, 102), (1552, 102), GRID, 1)
    text(d, (82, 65), "● ● ●", F["axis"], ORANGE_DIM)
    text(d, (226, 64), title.upper(), F["title"], TEXT)
    text(d, (82, 124), subtitle, F["sub"], MUTED)
    return img, d


def save(img: Image.Image, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    img.resize((W, H), Image.Resampling.LANCZOS).save(path, optimize=True)
    print(path)


def load_llama_bench(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    # Drop any leading log lines before the JSON array.
    start = raw.find("[")
    if start < 0:
        return []
    return json.loads(raw[start:])


def find_result(results: list[dict], n_prompt: int, n_gen: int) -> dict | None:
    for r in results:
        if r.get("n_prompt") == n_prompt and r.get("n_gen") == n_gen:
            return r
    return None


def compute_metrics() -> dict:
    hip_pp_sweep = load_llama_bench(DATA_DIR / "hip-bench-pp-sweep.json")
    hip_baseline = load_llama_bench(DATA_DIR / "hip-bench-baseline.json")
    vulkan = load_llama_bench(DATA_DIR / "vulkan-bench.json")

    hip_pp = find_result(hip_pp_sweep, 1024, 0)
    vulkan_pp = find_result(vulkan, 1024, 0)
    hip_tg = find_result(hip_baseline, 0, 128)
    vulkan_tg = find_result(vulkan, 0, 128)

    params = vulkan_pp["model_n_params"]
    size_bytes = vulkan_pp["model_size"]

    def tflops(tps: float) -> float:
        return 2 * params * tps / 1e12

    def gbps(tps: float) -> float:
        return size_bytes * tps / 1e9

    return {
        "params": params,
        "size_bytes": size_bytes,
        "hip_pp_tps": hip_pp["avg_ts"],
        "hip_pp_tflops": tflops(hip_pp["avg_ts"]),
        "hip_tps": hip_tg["avg_ts"],
        "hip_gbps": gbps(hip_tg["avg_ts"]),
        "vulkan_pp_tps": vulkan_pp["avg_ts"],
        "vulkan_pp_tflops": tflops(vulkan_pp["avg_ts"]),
        "vulkan_tps": vulkan_tg["avg_ts"],
        "vulkan_gbps": gbps(vulkan_tg["avg_ts"]),
    }


def horizontal_bars(
    d: ImageDraw.ImageDraw,
    labels: list[str],
    values: list[float],
    displays: list[str],
    colors: list[tuple[int, int, int]],
    *,
    box: tuple[int, int, int, int],
    xmax: float,
    xunit: str,
    label_x: int = 92,
    value_font=None,
    value_offset: int = 34,
    show_grid: bool = True,
) -> None:
    if value_font is None:
        value_font = F["value"]
    x1, y1, x2, y2 = box
    row_h = (y2 - y1) // len(labels)
    if show_grid:
        for tick in [0, 0.25, 0.5, 0.75, 1.0]:
            x = x1 + int((x2 - x1) * tick)
            line(d, (x, y1), (x, y2), GRID, 1)
    else:
        line(d, (x1, y2), (x2, y2), GRID, 1)
        for tick in [0.0, 0.5, 1.0]:
            x = x1 + int((x2 - x1) * tick)
            line(d, (x, y2), (x, y2 + 8), GRID, 1)
    for idx, label in enumerate(labels):
        cy = y1 + idx * row_h + row_h // 2
        text(d, (label_x, cy - 24), label, F["label"], TEXT)
        bw = int((values[idx] / xmax) * (x2 - x1))
        by = cy - 28
        fill_rect(d, (x1, by, x1 + bw, by + 28), colors[idx])
        rect(d, (x1, by, x2, by + 28), outline=GRID, width=1)
        text(d, (x2 + value_offset, by - 7), displays[idx], value_font, colors[idx])
    text(d, (x2 - 10, y1 - 44), xunit, F["axis"], MUTED, "rm")


def render_original(metrics: dict) -> None:
    img, d = terminal(
        "radeon ai pro r9700 peak",
        "qwen3.6 27b q6_k :: measured vs published spec",
    )

    compute_labels = ["FP16 matrix", "FP16 vector", "FP32", "Vulkan PP", "HIP PP"]
    compute_values = [383.0, 95.7, 47.8, metrics["vulkan_pp_tflops"], metrics["hip_pp_tflops"]]
    compute_displays = ["383", "95.7", "47.8", f"{metrics['vulkan_pp_tflops']:.1f}", f"{metrics['hip_pp_tflops']:.1f}"]
    compute_colors = [ORANGE_DIM, ORANGE_DIM, ORANGE_DIM, ORANGE, ORANGE_3]
    horizontal_bars(
        d, compute_labels, compute_values, compute_displays, compute_colors,
        box=(420, 245, 1380, 520), xmax=400, xunit="TFLOPS", label_x=92,
    )
    text(d, (420, 210), "PROMPT PROCESSING (COMPUTE)", F["axis"], MUTED)

    bw_labels = ["published", "Vulkan raw TG", "HIP raw TG"]
    bw_values = [640.0, metrics["vulkan_gbps"], metrics["hip_gbps"]]
    bw_displays = ["640", f"{metrics['vulkan_gbps']:.0f}", f"{metrics['hip_gbps']:.0f}"]
    bw_colors = [ORANGE_DIM, ORANGE, ORANGE_3]
    horizontal_bars(
        d, bw_labels, bw_values, bw_displays, bw_colors,
        box=(420, 610, 1380, 790), xmax=700, xunit="GB/s", label_x=92,
    )
    text(d, (420, 575), "TOKEN GENERATION (MEMORY BANDWIDTH)", F["axis"], MUTED)

    save(img, "5-r9700-peak-vs-spec.png")


def render_utilization(metrics: dict) -> None:
    """Option B: measured as percentage of published peak."""
    img, d = plain_terminal(
        "radeon ai pro r9700",
        "measured as % of published peak",
    )

    vulkan_pp_fp32 = metrics["vulkan_pp_tflops"] / 47.8 * 100
    hip_pp_fp32 = metrics["hip_pp_tflops"] / 47.8 * 100
    vulkan_pp_f16m = metrics["vulkan_pp_tflops"] / 383.0 * 100
    hip_pp_f16m = metrics["hip_pp_tflops"] / 383.0 * 100
    vulkan_bw = metrics["vulkan_gbps"] / 640.0 * 100
    hip_bw = metrics["hip_gbps"] / 640.0 * 100

    labels = [
        "PP vs FP32",
        "PP vs FP16 matrix",
        "raw TG vs bandwidth",
    ]
    vulkan_vals = [vulkan_pp_fp32, vulkan_pp_f16m, vulkan_bw]
    hip_vals = [hip_pp_fp32, hip_pp_f16m, hip_bw]
    vulkan_displays = [f"{vulkan_pp_fp32:.0f}%", f"{vulkan_pp_f16m:.0f}%", f"{vulkan_bw:.0f}%"]
    hip_displays = [f"{hip_pp_fp32:.0f}%", f"{hip_pp_f16m:.0f}%", f"{hip_bw:.0f}%"]

    x1, y1, x2, y2 = 460, 210, 1180, 740
    row_h = (y2 - y1) // len(labels)
    # Minimal axis ticks and baseline only
    line(d, (x1, y2), (x2, y2), GRID, 1)
    for tick in [0, 50, 100, 125]:
        x = x1 + int((x2 - x1) * (tick / 125))
        line(d, (x, y2), (x, y2 + 10), GRID, 1)
        text(d, (x, y2 + 38), f"{tick}%", F["axis"], MUTED, "ma")
    for idx, label in enumerate(labels):
        cy = y1 + idx * row_h + row_h // 2
        text(d, (80, cy - 34), label, F["label"], TEXT)
        row_max = 125
        v_bw = int((vulkan_vals[idx] / row_max) * (x2 - x1))
        h_bw = int((hip_vals[idx] / row_max) * (x2 - x1))
        v_by = cy - 58
        h_by = cy - 14
        fill_rect(d, (x1, v_by, x1 + v_bw, v_by + 36), ORANGE)
        rect(d, (x1, v_by, x1 + v_bw, v_by + 36), outline=ORANGE_3, width=1)
        fill_rect(d, (x1, h_by, x1 + h_bw, h_by + 36), ORANGE_3)
        rect(d, (x1, h_by, x1 + h_bw, h_by + 36), outline=GRID, width=1)
        text(d, (x2 + 40, v_by - 12), vulkan_displays[idx], F["big"], ORANGE)
        text(d, (x2 + 40, h_by - 12), hip_displays[idx], F["big"], ORANGE_3)

    # Legend (large, bottom-left so it clears the x-axis labels)
    leg_y = 805
    sq = 26
    gap = 14
    fill_rect(d, (80, leg_y, 80 + sq, leg_y + sq), ORANGE)
    rect(d, (80, leg_y, 80 + sq, leg_y + sq), outline=GRID, width=1)
    text(d, (80 + sq + gap, leg_y + 2), "Vulkan", F["label"], TEXT)
    hip_x = 80 + sq + gap + 170
    fill_rect(d, (hip_x, leg_y, hip_x + sq, leg_y + sq), ORANGE_3)
    rect(d, (hip_x, leg_y, hip_x + sq, leg_y + sq), outline=GRID, width=1)
    text(d, (hip_x + sq + gap, leg_y + 2), "HIP", F["label"], TEXT)

    # 100% reference line
    x100 = x1 + int((x2 - x1) * (100 / 125))
    line(d, (x100, y1), (x100, y2), RED_ORANGE, 2)
    text(d, (x100, y1 - 46), "100% of spec", F["small"], RED_ORANGE, "ma")

    save(img, "5b-r9700-utilization.png")


def render() -> dict:
    metrics = compute_metrics()
    render_original(metrics)
    render_utilization(metrics)
    return metrics


if __name__ == "__main__":
    metrics = render()
    print(json.dumps(metrics, indent=2))