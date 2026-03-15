# Active
[Tuning review] managed runtime now accepts global and per-service extra `llama-server` args — enables the same tuning flags as shell/systemd launches and preserves service-specific override order.
[Benchmark result] main service runs better with `--threads-http 6 -ctk q8_0 -ctv q8_0` added to the existing profile — reduced simple chat probe from ~0.57 s to ~0.13 s and increased free VRAM from ~262 MiB to ~594 MiB without breaking health checks.
