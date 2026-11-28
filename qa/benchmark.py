"""Bounded offline benchmark for ApexVoice ASGI and synthetic voice stages."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import gc
import json
import math
from pathlib import Path
import platform
import tempfile
from time import perf_counter
from xml.etree import ElementTree

from qa.call_harness import MOCK_MP3, simulate
from qa.offline import install_egress_guard


def resources(harness):
    proc = Path("/proc/self")
    status = (proc / "status").read_text().splitlines()
    rss = next(int(line.split()[1]) for line in status if line.startswith("VmRSS:"))
    return {
        "rss_kib": rss,
        "open_fds": len(list((proc / "fd").iterdir())),
        "audio_cache_entries": len(harness.module.db._local_tts_audio),
        "sqlite_bytes": Path(harness.module.db.db_path).stat().st_size,
    }


def percentiles(samples):
    samples = sorted(samples)
    return {
        "samples": len(samples),
        **{f"p{p}_ms": round(samples[math.ceil(len(samples) * p / 100) - 1], 2)
           for p in (50, 95, 99)},
    }


def call_turn(harness, index):
    sid = f"CA-offline-benchmark-{index:05d}"
    harness.model_reply = f"I can take a message for the team. Reference {index}."
    start = perf_counter()
    greeting = harness.inbound(sid)
    if greeting.status_code != 200 or ElementTree.fromstring(greeting.text).find("Gather") is None:
        raise RuntimeError("Synthetic inbound call was not admitted")
    turn = harness.turn(sid, "Can I leave a message for the team?")
    if turn.status_code != 200:
        raise RuntimeError("Synthetic gather request failed")
    audio = harness.audio(turn.text)
    if audio.status_code != 200 or audio.content != MOCK_MP3:
        raise RuntimeError("Synthetic audio retrieval failed")
    harness.latency_ms["inbound-to-turn-audio"].append((perf_counter() - start) * 1000)
    if harness.end(sid).status_code != 200:
        raise RuntimeError("Synthetic call settlement failed")


def run(args):
    install_egress_guard()
    with tempfile.TemporaryDirectory(prefix="apex-bench-") as temp:
        with simulate(Path(temp), tts=True) as harness:
            harness.provider_delays_ms.update(llm=args.llm_ms, tts=args.tts_ms)
            for index in range(5):
                call_turn(harness, index)
            harness.latency_ms.clear()
            harness.model_requests.clear()
            harness.actions.clear()
            gc.collect()
            baseline = resources(harness)
            started = perf_counter()
            for index in range(5, args.calls + 5):
                call_turn(harness, index)
                harness.model_requests.clear()
                harness.actions.clear()
            call_elapsed = perf_counter() - started

            def health(_):
                started = perf_counter()
                response = harness.client.get("/api/health")
                if response.status_code != 200 or response.json().get("status") != "ok":
                    raise RuntimeError("Health request failed")
                return (perf_counter() - started) * 1000

            started = perf_counter()
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                harness.latency_ms["health"] = list(pool.map(health, range(args.requests)))
            health_elapsed = perf_counter() - started
            gc.collect()
            final = resources(harness)
            stages = {stage: percentiles(samples) for stage, samples in harness.latency_ms.items()}

    return {
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "settings": vars(args) | {"output": str(args.output) if args.output else None},
        "latency": stages,
        "calls_per_second": round(args.calls / call_elapsed, 2),
        "health_requests_per_second": round(args.requests / health_elapsed, 2),
        "resources_before": baseline,
        "resources_after": final,
        "resource_delta": {key: final[key] - baseline[key] for key in baseline},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=int, default=80)
    parser.add_argument("--requests", type=int, default=400)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--llm-ms", type=int, default=20)
    parser.add_argument("--tts-ms", type=int, default=20)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true", help="Apply CI regression thresholds")
    args = parser.parse_args()
    if not (1 <= args.calls <= 500 and 1 <= args.requests <= 5000 and 1 <= args.workers <= 32
            and 0 <= args.llm_ms <= 250 and 0 <= args.tts_ms <= 250):
        parser.error("Use 1–500 calls, 1–5000 health requests, 1–32 workers, and 0–250 ms provider delays")
    report = run(args)
    output = json.dumps(report, indent=2)
    print(output)
    if args.output:
        args.output.write_text(output + "\n")
    if args.check:
        latency = report["latency"]
        if (latency["inbound-to-turn-audio"]["p95_ms"] > 1000
                or latency["health"]["p95_ms"] > 250
                or report["resource_delta"]["open_fds"] > 2):
            raise SystemExit("Offline latency or file descriptor budget exceeded")


if __name__ == "__main__":
    main()
