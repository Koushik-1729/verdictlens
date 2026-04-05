"""
VerdictLens SDK overhead benchmark — measures the cost of the @trace decorator.

Runs a no-op function 1000 times with and without the decorator, reports
p50/p95/p99 latency overhead.  Target: under 2ms overhead.  CI gate: p99 < 5ms.

Usage:
    cd verdictlens
    pip install -e ./sdk
    python benchmarks/overhead_test.py

Outputs: benchmarks/benchmark_results.json
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from verdictlens import configure
from verdictlens.trace import trace


configure(base_url="http://localhost:9999", disabled=True)

ITERATIONS = 1000
WARMUP = 50


def bare_function(x: int) -> int:
    """Minimal function to isolate decorator overhead."""
    return x + 1


@trace(name="bench_traced", framework="benchmark")
def traced_function(x: int) -> int:
    """Same function with @trace decorator applied."""
    return x + 1


async def bare_async(x: int) -> int:
    """Minimal async function."""
    return x + 1


@trace(name="bench_traced_async", framework="benchmark")
async def traced_async(x: int) -> int:
    """Same async function with @trace decorator applied."""
    return x + 1


def _percentile(data: list[float], pct: float) -> float:
    """
    Compute a percentile from sorted data.

    :param data: Sorted list of values.
    :param pct: Percentile (0-100).
    :returns: Interpolated percentile value.
    """
    k = (len(data) - 1) * (pct / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(data):
        return data[f]
    d0 = data[f] * (c - k)
    d1 = data[c] * (k - f)
    return d0 + d1


def benchmark_sync() -> dict:
    """
    Benchmark sync function overhead.

    :returns: Dict with timing stats.
    """
    for _ in range(WARMUP):
        bare_function(42)
        traced_function(42)

    bare_times: list[float] = []
    for i in range(ITERATIONS):
        t0 = time.perf_counter()
        bare_function(i)
        t1 = time.perf_counter()
        bare_times.append((t1 - t0) * 1_000_000)

    traced_times: list[float] = []
    for i in range(ITERATIONS):
        t0 = time.perf_counter()
        traced_function(i)
        t1 = time.perf_counter()
        traced_times.append((t1 - t0) * 1_000_000)

    overheads = [t - b for t, b in zip(traced_times, bare_times)]
    overheads.sort()

    return {
        "type": "sync",
        "iterations": ITERATIONS,
        "bare_p50_us": round(_percentile(sorted(bare_times), 50), 2),
        "bare_p99_us": round(_percentile(sorted(bare_times), 99), 2),
        "traced_p50_us": round(_percentile(sorted(traced_times), 50), 2),
        "traced_p99_us": round(_percentile(sorted(traced_times), 99), 2),
        "overhead_p50_us": round(_percentile(overheads, 50), 2),
        "overhead_p95_us": round(_percentile(overheads, 95), 2),
        "overhead_p99_us": round(_percentile(overheads, 99), 2),
        "overhead_mean_us": round(statistics.mean(overheads), 2),
        "overhead_p50_ms": round(_percentile(overheads, 50) / 1000, 4),
        "overhead_p95_ms": round(_percentile(overheads, 95) / 1000, 4),
        "overhead_p99_ms": round(_percentile(overheads, 99) / 1000, 4),
    }


def benchmark_async() -> dict:
    """
    Benchmark async function overhead.

    :returns: Dict with timing stats.
    """
    import asyncio

    async def _run() -> dict:
        for _ in range(WARMUP):
            await bare_async(42)
            await traced_async(42)

        bare_times: list[float] = []
        for i in range(ITERATIONS):
            t0 = time.perf_counter()
            await bare_async(i)
            t1 = time.perf_counter()
            bare_times.append((t1 - t0) * 1_000_000)

        traced_times: list[float] = []
        for i in range(ITERATIONS):
            t0 = time.perf_counter()
            await traced_async(i)
            t1 = time.perf_counter()
            traced_times.append((t1 - t0) * 1_000_000)

        overheads = [t - b for t, b in zip(traced_times, bare_times)]
        overheads.sort()

        return {
            "type": "async",
            "iterations": ITERATIONS,
            "bare_p50_us": round(_percentile(sorted(bare_times), 50), 2),
            "bare_p99_us": round(_percentile(sorted(bare_times), 99), 2),
            "traced_p50_us": round(_percentile(sorted(traced_times), 50), 2),
            "traced_p99_us": round(_percentile(sorted(traced_times), 99), 2),
            "overhead_p50_us": round(_percentile(overheads, 50), 2),
            "overhead_p95_us": round(_percentile(overheads, 95), 2),
            "overhead_p99_us": round(_percentile(overheads, 99), 2),
            "overhead_mean_us": round(statistics.mean(overheads), 2),
            "overhead_p50_ms": round(_percentile(overheads, 50) / 1000, 4),
            "overhead_p95_ms": round(_percentile(overheads, 95) / 1000, 4),
            "overhead_p99_ms": round(_percentile(overheads, 99) / 1000, 4),
        }

    return asyncio.run(_run())


def main() -> None:
    """Run all benchmarks and write results."""
    print("=" * 60)
    print("  VerdictLens @trace Decorator Overhead Benchmark")
    print(f"  Iterations: {ITERATIONS}")
    print("=" * 60)

    sync_result = benchmark_sync()
    print(f"\n  SYNC:")
    print(f"    p50 overhead: {sync_result['overhead_p50_ms']:.4f} ms")
    print(f"    p95 overhead: {sync_result['overhead_p95_ms']:.4f} ms")
    print(f"    p99 overhead: {sync_result['overhead_p99_ms']:.4f} ms")

    async_result = benchmark_async()
    print(f"\n  ASYNC:")
    print(f"    p50 overhead: {async_result['overhead_p50_ms']:.4f} ms")
    print(f"    p95 overhead: {async_result['overhead_p95_ms']:.4f} ms")
    print(f"    p99 overhead: {async_result['overhead_p99_ms']:.4f} ms")

    results = {
        "benchmark": "verdictlens_trace_overhead",
        "iterations": ITERATIONS,
        "sync": sync_result,
        "async": async_result,
    }

    p99_sync = sync_result["overhead_p99_ms"]
    p99_async = async_result["overhead_p99_ms"]
    passed = p99_sync < 5.0 and p99_async < 5.0

    results["ci_gate"] = {
        "threshold_p99_ms": 5.0,
        "target_p99_ms": 2.0,
        "sync_p99_ms": p99_sync,
        "async_p99_ms": p99_async,
        "passed": passed,
    }

    out_path = Path(__file__).parent / "benchmark_results.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\n  Results written to: {out_path}")

    print(f"\n  CI gate (p99 < 5ms): {'PASS' if passed else 'FAIL'}")
    if not passed:
        print("  ⚠ p99 overhead exceeds 5ms threshold!")
        raise SystemExit(1)

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
