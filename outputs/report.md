# NimbusAI — GPU Cost Optimization Report

> **Period:** monthly · **Snapshot:** June 2026
> Re-baseline before acting — GPU prices shift monthly.

---

## Executive Summary

| Metric | Value |
|---|---|
| **Baseline spend** | $27,133 / month |
| **Optimized spend** | $14,626 / month |
| **Projected savings** | $12,507 / month (**46%**) |
| **Baseline $/1M-token** | $6.488 |
| **Optimized $/1M-token** | $1.126 |
| **Inference savings** | 82.6% |

---

## Savings Breakdown by Lever

| Lever | Monthly Savings (USD) | % of Total Savings |
|---|---|---|
| Inference (cascade/cache/batch) | $1,212 | 9.7% |
| Purchasing (spot/reserved) | $10,040 | 80.3% |
| Right-size util-lies | $655 | 5.2% |
| Kill idle GPUs | $600 | 4.8% |

---

## Analysis: Why the GPU-Util Lie Costs Real Money

> **Core insight:** `nvidia-smi` reports *clock-active fraction*, not compute
> efficiency. A GPU can show 98% GPU-Util while doing ≤20% of its peak FLOPs.

### The Mechanism

GPU-Util% counts how often the SM clocks are not in a deep-sleep state (C0
vs. deeper C-states). A kernel that stalls waiting for **HBM memory reads**
(memory-bound decode) keeps the clock ticking — so GPU-Util stays high — but
produces almost no FLOPs because compute pipelines are idle waiting for data.

This is precisely LLM decode: each forward pass loads the full KV-cache and
weight shards from HBM (~3.35 TB/s on H100-SXM), while generating just
1–2 tokens per step. The arithmetic intensity is ~1-2 FLOP/byte vs. the
H100 ridge-point of ~295 FLOP/byte — deeply memory-bound.

**Cost implication:** You pay for a full H100 GPU-hour (~$3.89/hr on-demand)
but receive the equivalent work of a much cheaper A10G or L4.

### Detected GPU-Util Lies

| GPU ID | Type | GPU-Util% | MFU | Wasted $ → Right-Size Action |
|---|---|---|---|---|
| gpu-h100-4 | H100 | 98.2% | 19.4% | Down-tier to next cheaper GPU class |
| gpu-a10g-1 | A10G | 96.9% | 26.8% | Down-tier to next cheaper GPU class |

---

## Prioritised Action Plan

Ranked by ROI (biggest savings first, lowest disruption preferred):

| Priority | Action | Lever | Est. Monthly Saving | Effort |
|---|---|---|---|---|
| 1 | Purchasing (spot/reserved) | FinOps | $10,040 | Medium – requires workload audit + commitment |
| 2 | Inference (cascade/cache/batch) | FinOps | $1,212 | Low – routing policy + API flag changes |
| 3 | Right-size util-lies | FinOps | $655 | Medium – redeploy to cheaper GPU class |
| 4 | Kill idle GPUs | FinOps | $600 | Low – auto-shutdown scripts or TTL policies |

> **Why Purchasing first in absolute $?** Reserved 3yr contracts on always-on
> training jobs deliver the largest single savings (~$10,040/mo) with
> low execution risk once utilisation is confirmed > break-even (~55%).
> **Why Inference second?** Cascade routing + prompt caching + batch API require
> only code changes — no procurement cycle — and compounds with every new request.

---

## Inference Deep-Dive (M2)

- **Requests analysed:** 7,533,027 tokens across 2,400 requests
- **Cascade routing** moves small/medium queries to the cheap model tier
  (\$0.20/\$0.40 per 1M vs \$3.00/\$15.00) — biggest per-token lever.
- **Prompt caching:** avg cache reads = **710.0×**
  vs break-even of 12.5× → cache is ✓ justified.
- **Batch API:** 50% discount for non-latency-sensitive jobs.

### [D3] Cache Economics

Break-even formula: `avg_reads ≥ write_cost / read_discount = 1.25 / 0.10 = 12.5`.
At **710.0× average reads**, caching delivers a
**90%** discount on cached input tokens — well past the threshold.

### [D4] Reasoning Budget

| Metric | Value |
|---|---|
| Reasoning traffic share | 16.5% of tokens |
| Reasoning cost share | 16.5% of optimized bill |
| Reasoning energy | 29,787.7 Wh/day (94.0% of Wh) |
| Non-reasoning energy | 1,887.6 Wh/day |

**Why reasoning is an energy bomb:** Reasoning models run extended chain-of-thought
passes — each forward step generates intermediate 'thinking' tokens that are discarded
before the final response. This is compute-bound (high FLOP/byte) unlike decode, but
the sheer volume of hidden tokens inflates energy ~80× per useful output token.

**Routing rule proposal:** Route to reasoning model only when
`task_complexity_score > threshold` (e.g. multi-step math, code debugging).
Capping reasoning at 10% traffic saves **\$0.55/day**
and **11,708.5 Wh/day** (~351.3 kWh/month).

---

## Sustainability Analysis

- **Energy per query (median 800 tokens):** 0.24 Wh
- **Carbon per query (us-east-1):** 0.091 gCO₂e
- **Best region (carbon):** `europe-north1`

### Region Comparison

| Region | gCO₂/kWh | $/kWh | Carbon/query | Electricity cost/query |
|---|---|---|---|---|
| `europe-north1` | 30 | $0.090 | 0.0072 gCO₂ | 0.0022 ¢ |
| `us-east-wa` | 90 | $0.055 | 0.0216 gCO₂ | 0.0013 ¢ |
| `us-west-2` | 120 | $0.070 | 0.0288 gCO₂ | 0.0017 ¢ |
| `us-east-1` | 380 | $0.120 | 0.0912 gCO₂ | 0.0029 ¢ |
| `europe-central2` | 660 | $0.180 | 0.1584 gCO₂ | 0.0043 ¢ |

> **Best region:** `europe-north1` (Norway) — 30 gCO₂/kWh vs 380 in us-east-1.
> Moving interruptible training jobs here cuts carbon **12.7×** and electricity
> cost is competitive (\$0.09/kWh vs \$0.12 in us-east-1).
> **Trade-off:** Norway may add 80–120ms latency for US users — acceptable for
> batch training, unacceptable for real-time inference. Deploy inference in
> `us-west-2` (Oregon hydro, \$0.07/kWh, 120 gCO₂) as the balanced choice.

---

_Figures are June-2026 as-of snapshots; re-baseline before acting._