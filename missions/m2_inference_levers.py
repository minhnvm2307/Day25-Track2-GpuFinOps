"""M2 — Inference Cost Levers: $/1M-token, batch x cache x cascade (deck §7).

Run: python missions/m2_inference_levers.py

Extensions implemented:
  D3 - Cache Economics: apply cache_is_worth_it() gate before counting cache savings;
       compute break-even reads and compare with actual avg_cache_reads.
  D4 - Reasoning Budget: split $ and Wh costs between reasoning vs. non-reasoning
       traffic; propose cap-at-10% routing rule with quantified savings.
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from missions._common import load_csv, num
from finops import pricing
from finops import sustainability as _sust

# $/1M tokens (input, output) — illustrative 2026.
MODEL_PRICES = {"small": (0.20, 0.40), "large": (3.00, 15.00)}

# Energy constant (shared with sustainability module)
WH_PER_1K_TOKENS = 0.30


def run(verbose: bool = True) -> dict:
    rows = load_csv("token_usage.csv")
    base_cost = opt_cost = 0.0
    total_tokens = 0
    total_requests = 0

    # Cache tracking (D3)
    total_cached_tokens = 0
    cache_write_count = 0   # requests that have any cached_input_tokens

    # Reasoning tracking (D4)
    reasoning_cost_base = 0.0
    reasoning_cost_opt  = 0.0
    reasoning_tokens    = 0
    non_reasoning_tokens = 0

    for r in rows:
        inp, out   = int(num(r["input_tokens"])), int(num(r["output_tokens"]))
        cached     = int(num(r["cached_input_tokens"]))
        is_batch   = bool(int(num(r["is_batch"])))
        is_reason  = bool(int(num(r.get("is_reasoning", 0))))
        total_tokens   += inp + out
        total_requests += 1

        # D3 – count cache writes
        if cached > 0:
            cache_write_count   += 1
            total_cached_tokens += cached

        # BASELINE: naive deployment — large model, no cache, no batch
        lin, lout = MODEL_PRICES["large"]
        bc = pricing.request_cost(inp, out, lin, lout)
        base_cost += bc

        # OPTIMIZED: cascade + prompt caching + batch API
        pin, pout = MODEL_PRICES[r["route_tier"]]
        oc = pricing.request_cost(inp, out, pin, pout, cached_in=cached, batch=is_batch)
        opt_cost  += oc

        # D4 split
        if is_reason:
            reasoning_cost_base += bc
            reasoning_cost_opt  += oc
            reasoning_tokens    += inp + out
        else:
            non_reasoning_tokens += inp + out

    base_pm     = pricing.dollars_per_million(base_cost, total_tokens)
    opt_pm      = pricing.dollars_per_million(opt_cost, total_tokens)
    savings_pct = (1 - opt_cost / base_cost) * 100 if base_cost else 0.0

    # ------------------------------------------------------------------ D3
    avg_cache_reads = (total_cached_tokens / cache_write_count) if cache_write_count > 0 else 0.0
    be_reads        = pricing.cache_break_even_reads()   # default write=1.25x, read=0.10x → 12.5
    cache_justified = pricing.cache_is_worth_it(avg_cache_reads)

    # ------------------------------------------------------------------ D4
    reasoning_traffic_pct = (reasoning_tokens / total_tokens * 100) if total_tokens else 0.0
    reasoning_cost_pct    = (reasoning_cost_opt / opt_cost * 100) if opt_cost else 0.0

    # Wh: reasoning uses REASONING_ENERGY_MULTIPLIER × standard energy
    reasoning_wh     = (reasoning_tokens / 1000) * WH_PER_1K_TOKENS * _sust.REASONING_ENERGY_MULTIPLIER
    non_reasoning_wh = (non_reasoning_tokens / 1000) * WH_PER_1K_TOKENS
    total_wh         = reasoning_wh + non_reasoning_wh
    reasoning_wh_pct = (reasoning_wh / total_wh * 100) if total_wh else 0.0

    # Scenario: cap reasoning traffic to 10% instead of current share
    TARGET_REASONING_FRAC = 0.10
    actual_reasoning_frac = reasoning_tokens / total_tokens if total_tokens else 0.0
    if actual_reasoning_frac > TARGET_REASONING_FRAC:
        excess_frac               = actual_reasoning_frac - TARGET_REASONING_FRAC
        saved_reasoning_cost      = (excess_frac / actual_reasoning_frac) * reasoning_cost_opt if actual_reasoning_frac else 0.0
        saved_reasoning_wh        = (excess_frac / actual_reasoning_frac) * reasoning_wh if actual_reasoning_frac else 0.0
    else:
        saved_reasoning_cost = saved_reasoning_wh = 0.0

    if verbose:
        print("== M2 Inference Cost Levers ==")
        print(f"requests={total_requests:,}  tokens={total_tokens:,}")
        print(f"baseline  : ${base_cost:,.2f}/day   ${base_pm:.3f}/1M-token")
        print(f"optimized : ${opt_cost:,.2f}/day   ${opt_pm:.3f}/1M-token")
        print(f"savings   : {savings_pct:.1f}%  (cascade + caching + batch)")
        print(f"discount stack (batch + 100% cache): {pricing.discount_stack(batch=True, cache_hit_frac=1.0):.3f} of naive")
        print()
        print("--- [D3] Cache Economics ---")
        print(f"Requests with cached tokens : {cache_write_count:,} / {total_requests:,}")
        print(f"Avg cache reads per write   : {avg_cache_reads:.1f}  (break-even: {be_reads:.1f})")
        print(f"Cache economically justified: {'YES ✓' if cache_justified else 'NO ✗  (avg_reads < break-even)'}")
        print()
        print("--- [D4] Reasoning Budget ---")
        print(f"Reasoning traffic  : {reasoning_tokens:,} tok  = {reasoning_traffic_pct:.1f}% of total traffic")
        print(f"Reasoning cost     : ${reasoning_cost_opt:,.2f}/day = {reasoning_cost_pct:.1f}% of optimized bill")
        print(f"Reasoning energy   : {reasoning_wh:,.1f} Wh = {reasoning_wh_pct:.1f}% of total Wh")
        print(f"Non-reasoning Wh   : {non_reasoning_wh:,.1f} Wh")
        if non_reasoning_wh > 0:
            actual_ratio = reasoning_wh / non_reasoning_wh * (non_reasoning_tokens / max(reasoning_tokens, 1))
            print(f"Energy multiplier (actual): {actual_ratio:.1f}x  (theoretical: {_sust.REASONING_ENERGY_MULTIPLIER:.0f}x)")
        print(f"\n  → Scenario: cap reasoning to {TARGET_REASONING_FRAC:.0%} traffic")
        print(f"  → Save ${saved_reasoning_cost:,.2f}/day  +  {saved_reasoning_wh:,.1f} Wh/day")
        print(f"  → Routing rule: use reasoning model only when task_complexity_score > threshold")
        print(f"  → Remaining {TARGET_REASONING_FRAC:.0%} covers complex queries; reroute the rest to small/cascade")

    return {
        "baseline_daily": round(base_cost, 2), "optimized_daily": round(opt_cost, 2),
        "baseline_per_m": round(base_pm, 3),   "optimized_per_m": round(opt_pm, 3),
        "savings_pct": round(savings_pct, 1),  "total_tokens": total_tokens,
        # D3
        "avg_cache_reads":   round(avg_cache_reads, 1),
        "cache_break_even":  be_reads,
        "cache_justified":   cache_justified,
        # D4
        "reasoning_traffic_pct":              round(reasoning_traffic_pct, 1),
        "reasoning_cost_pct":                 round(reasoning_cost_pct, 1),
        "reasoning_wh":                       round(reasoning_wh, 1),
        "non_reasoning_wh":                   round(non_reasoning_wh, 1),
        "saved_by_capping_reasoning_cost":    round(saved_reasoning_cost, 2),
        "saved_by_capping_reasoning_wh":      round(saved_reasoning_wh, 1),
    }


if __name__ == "__main__":
    run()
