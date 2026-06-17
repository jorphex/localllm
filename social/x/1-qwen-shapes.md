# Qwen 3.6 Shapes: Dense, Sparse, Context

Images:

1. `social/x/1-qwen-shapes-context.png`
2. `social/x/1-qwen-shapes-metrics.png`
3. `social/x/1-qwen-shapes-context-cliff.png`

Alt text:

Image 1: Terminal-style black and saturated orange scatter plot titled "Qwen 3.6 Shape Map." It plots context tokens against decode tokens per second. The 27B MTP point is at 128k context and about 45-50 tokens per second. The 35B A3B point is at 160k context and about 89 tokens per second.

Image 2: Terminal-style black and saturated orange grouped bar chart titled "Best Local Shapes." It compares 27B MTP Q6 and 35B A3B Q6 across prompt processing, decode, context, and stack VRAM. The 27B shape shows about 637 prompt-processing tokens per second, 45-50 decode tokens per second, 128k context, and 29.56 GB stack VRAM. The 35B shape shows about 2570 prompt-processing tokens per second, 89 decode tokens per second, 160k context, and 33.03 GB stack VRAM.

Image 3: Terminal-style black and saturated orange heatmap titled "Context Cliff Heatmap." It compares local Qwen 3.6 shapes by model, context, KV precision, decode speed, and qualitative read.

## Tweet 1

I compared tuned Qwen 3.6 local-agent shapes on my AMD/Vulkan stack.

The best 27B MTP Q6 shape I found was 128k q8 KV at ~45-50 tok/s decode.

The best 35B A3B Q6 speed shape I found was 160k q8 KV at ~89 tok/s decode.

This is local-stack data, not a universal model ranking.

[image 1]

## Tweet 2

The tuned shapes were not close on prompt processing:

27B MTP Q6:
128k ctx / q8 KV / b2048 / ub1024 / draft-MTP n=3
~637 pp/s, ~45-50 tok/s, 29.56 GB stack VRAM

35B A3B Q6:
160k ctx / q8 KV / b4096 / ub2048 / spec-default
~2570 pp/s, ~89 tok/s, 33.03 GB stack VRAM

[image 2]

## Tweet 3

Context size changed the result a lot.

On 27B MTP Q6, 256k q8 KV loaded but decode fell to ~22-25 tok/s.

256k q4 KV recovered speed to ~41-44 tok/s, but with the KV-precision tradeoff.

For daily agent work, I kept the faster q8 KV shape instead of maxing context.

[image 3]

## Notes

- One tweet per image.
- Collapses the old `2-27b-vs-35b`, `4-dense-hype-sparse-reality`, and `6-context-cliff-heatmap` threads.
- Keep this framed as local-stack evidence, not a universal dense-vs-sparse claim.
- The 35B row uses the faster `fast-160k` managed-service probe.
