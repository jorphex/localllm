# Local Agent Stack Residency

Images:

1. `social/x/4-stack-vram-budget.png`
2. `social/x/4-stack-residency-map.png`

Alt text:

Image 1: Terminal-style black and saturated orange horizontal bar chart titled "VRAM Residency Budget." It shows current Qwen 27B stack GPU memory use with different sidecar placements. Main plus CPU sidecars uses about 29.57 GB. Main plus GPU embedding uses about 32.46 GB. Main plus GPU reranker uses about 32.71 GB.

Image 2: Terminal-style black and saturated orange residency matrix titled "Current Stack Residency." Rows show GPU, CPU, state, and timer. Columns show main, embedding, reranker, TTS, cache, and flush. Filled cells indicate the current placement: main and reranker on GPU, embedding and TTS on CPU, cache/state handling separately, and an idle flush timer.

## Tweet 1

The current Qwen 27B stack leaves enough VRAM for one 4B sidecar, but not much more.

Measured total VRAM use:

main + CPU sidecars: 29.57 GB
main + GPU embedding: 32.46 GB
main + GPU reranker: 32.71 GB

This is total stack residency, not model-file size.

[image 1]

## Tweet 2

I tested both sidecar placements.

Embedding fit in VRAM, but moving the reranker to GPU felt faster in the agent path.

Current placement:
main model: GPU
reranker: GPU
embedding: CPU
TTS: CPU
prompt reuse: on
RAM prompt-cache store: off
idle slot flush: on

[image 2]

## Notes

- One tweet per image.
- Collapses the old `7-vram-stack-budget` and `9-local-agent-stack-map` threads.
- Current placement reflects the latest flip: embedding CPU/RAM, reranker GPU/VRAM.
- Do not include local paths, ports, hostnames, or API keys in posted screenshots.
