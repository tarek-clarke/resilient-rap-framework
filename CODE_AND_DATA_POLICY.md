# Code and Data Policy

This `ngise` branch is the code and evidence artifact for the NGISE paper
*Engineering Resilient Reproducible Analytical Pipelines (RAP):
Semantic-Based Self-Healing for High-Velocity Heterogeneous Data Streams*.
The public branch is available at:

<https://github.com/tarek-clarke/resilient-rap-framework/tree/ngise>

## Included

- the triple-header benchmark runner and its runtime dependencies;
- the BERT, Levenshtein, and Regex ablation implementation;
- the 27 selected per-run JSON summaries supporting Tables 4 and 5;
- the 100-case ablation report and the manifest for the 24 cases used in Table 1;
- the manifest mapping artifact files to the reported tables.

## Data availability and limits

The telemetry is synthetic. No personal, confidential, or proprietary dataset
is used. The repository does not include the original raw 3.6-million-packet
streams, generated SQLite state, per-run configuration manifests, a committed
random seed or chaos-profile JSON, or a locked software environment. The
committed JSON files are summary evidence for the reported values, not raw
packet data. A new run is therefore not expected to reproduce them bit-for-bit.

The nominal protocol specifies 5% chaos, but the three committed GH200 reports
record approximately 12%. The `rtxb6000` reports identify RTX PRO 6000
Blackwell Workstation and Max-Q variants with approximately 96 GB of VRAM;
they are not reports from the separate 48 GB RTX 6000 Ada Generation product.

For double-blind review, use an anonymized repository URL or archive link in
the manuscript. The existing Git history retains its original metadata even
though identifying text was removed from the current working tree.
