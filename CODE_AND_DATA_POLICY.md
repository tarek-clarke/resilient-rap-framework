# Code and Data Policy

This `ngise` branch is the code and evidence artifact for the NGISE paper
*Engineering Resilient Reproducible Analytical Pipelines (RAP):
Semantic-Based Self-Healing for High-Velocity Heterogeneous Data Streams*.
The public branch is available at:

<https://github.com/tarek-clarke/resilient-rap-framework/tree/ngise>

## Included

- the triple-header benchmark runner and its runtime dependencies;
- the semantic, string-similarity, and Regex ablation implementation;
- the 27 selected per-run JSON summaries supporting Tables 4 and 5;
- the three-run GH200 rerun's per-session summaries, event timing samples,
  timing summaries, and logs;
- the 100-case ablation report and the manifest for the 24 cases used in Table 1;
- the manifest mapping artifact files to the reported tables.

## Data availability and limits

The telemetry is synthetic. No personal, confidential, or proprietary dataset
is used. The repository does not include the original raw 3.6-million-packet
streams, generated SQLite state, per-run configuration manifests, a committed
random seed or chaos-profile JSON, or a locked software environment. The
committed JSON files are summary evidence for the reported values, not raw
packet data. A new run is therefore not expected to reproduce them bit-for-bit.

The three GH200 reports from 2026-10-07 record observed chaos rates of
4.9944%, 4.9992%, and 5.0047%. They replace the earlier approximately 12%
GH200 reports in the paper's table mapping. The rerun has no recorded RNG
seed, so its results are auditable summaries rather than bit-for-bit
reproducible outputs. The `rtxb6000` reports identify RTX PRO 6000 Blackwell
Workstation and Max-Q variants with approximately 96 GB of VRAM; they are not
reports from the separate 48 GB RTX 6000 Ada Generation product.
