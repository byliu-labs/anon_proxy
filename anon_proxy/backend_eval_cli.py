from __future__ import annotations

import argparse
import json

from anon_proxy.backend_eval import DEFAULT_EVAL_TEXTS, check_parity, compare_backends
from anon_proxy.privacy_filter import PrivacyFilter


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare PrivacyFilter backends for entity parity and latency."
    )
    parser.add_argument(
        "--texts",
        nargs="*",
        default=DEFAULT_EVAL_TEXTS,
        help="Texts to evaluate. Defaults to built-in PII samples.",
    )
    parser.add_argument(
        "--warmups",
        type=int,
        default=1,
        help="Warmup iterations before timing.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Measured timing iterations.",
    )
    parser.add_argument(
        "--min-speedup",
        type=float,
        default=0.30,
        help="Required ONNX warm-median speedup versus torch.",
    )
    parser.add_argument(
        "--onnx-provider",
        default="CPUExecutionProvider",
        help="ONNX Runtime execution provider.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    args = parser.parse_args()

    torch_filter = PrivacyFilter(backend="torch", device="cpu")
    onnx_filter = PrivacyFilter(
        backend="onnx",
        onnx_provider=args.onnx_provider,
    )

    parity = check_parity(torch_filter, onnx_filter, args.texts)
    benchmark = compare_backends(
        torch_filter,
        onnx_filter,
        args.texts,
        warmups=args.warmups,
        iterations=args.iterations,
    )
    passed = all(result.passed for result in parity) and (
        benchmark.speedup >= args.min_speedup
    )

    payload = {
        "parity_passed": all(result.passed for result in parity),
        "benchmark_passed": benchmark.speedup >= args.min_speedup,
        "required_speedup": args.min_speedup,
        "speedup": benchmark.speedup,
        "torch_median_s": benchmark.reference_median_s,
        "onnx_median_s": benchmark.candidate_median_s,
        "parity": [
            {
                "text": result.text,
                "reference": [entity.__dict__ for entity in result.reference],
                "candidate": [entity.__dict__ for entity in result.candidate],
                "missing": [entity.__dict__ for entity in result.missing],
            }
            for result in parity
        ],
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"torch median: {benchmark.reference_median_s:.3f}s; "
            f"onnx median: {benchmark.candidate_median_s:.3f}s; "
            f"speedup: {benchmark.speedup:.1%}"
        )
        for result in parity:
            if result.missing:
                print(f"missing entities for {result.text!r}: {result.missing}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
