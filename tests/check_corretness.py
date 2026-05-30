#!/usr/bin/env python3
import argparse
import hashlib
import itertools
import math
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Case:
    name: str
    words: tuple[str, ...]
    start: int
    end: int
    repeat: bool


def die(msg: str) -> None:
    print(f"[FATAL] {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], timeout: int) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", errors="replace"))
        die(f"command failed: {' '.join(cmd)}")


def run_checked(cmd: list[str], timeout: int) -> None:
    proc = subprocess.run(cmd, timeout=timeout)
    if proc.returncode != 0:
        die(f"command failed: {' '.join(cmd)}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def count_lines(path: Path) -> int:
    total = 0
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            total += b.count(b"\n")
    return total


def sorted_copy_hash(path: Path, tmpdir: Path) -> str:
    sorted_path = tmpdir / f"{path.name}.sorted"
    cmd = ["sort", "-T", str(tmpdir), "-o", str(sorted_path), str(path)]
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", errors="replace"))
        die(f"sort failed: {path}")
    h = sha256_file(sorted_path)
    sorted_path.unlink(missing_ok=True)
    return h


def make_cmd(permutator: Path, case: Case, out: Path) -> list[str]:
    cmd = [str(permutator), "--start", str(case.start), "--end", str(case.end), "--output", str(out)]
    if case.repeat:
        cmd.append("--repeat")
    cmd.extend(case.words)
    return cmd


def expected_lines(case: Case) -> list[str]:
    lines: list[str] = []
    max_len = case.end if case.repeat else min(case.end, len(case.words))
    for k in range(case.start, max_len + 1):
        if case.repeat:
            iterator = itertools.product(case.words, repeat=k)
        else:
            iterator = itertools.permutations(case.words, k)
        for tup in iterator:
            lines.append("".join(tup))
    return lines


def expected_count(case: Case) -> int:
    max_len = case.end if case.repeat else min(case.end, len(case.words))
    total = 0
    for k in range(case.start, max_len + 1):
        if case.repeat:
            total += len(case.words) ** k
        else:
            total += math.perm(len(case.words), k)
    return total


def write_expected(path: Path, lines: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(line)
            f.write("\n")


def run_bench_smoke(permutator: Path, timeout: int) -> None:
    bench = Path(__file__).resolve().with_name("bench.py")
    if not bench.exists():
        die(f"bench.py not found: {bench}")
    print("\n[*] bench smoke: non-bench mode, runs=1, tiny cases")
    cmd = [
        sys.executable,
        str(bench),
        "--permutator",
        str(permutator),
        "--runs",
        "1",
        "--cc",
        "--charset",
        "abcdef",
        "--crunch-k",
        "2",
        "3",
        "--words",
        "8",
        "--small-words",
        "5",
        "--token-width",
        "3",
        "--timeout",
        str(timeout),
    ]
    run_checked(cmd, timeout)


def cases() -> list[Case]:
    return [
        # Core no-repeat: exactly itertools.permutations(words, k), checked as a multiset.
        Case("perm_1of1_single", ("a",), 1, 1, False),
        Case("perm_1of2", ("a", "b"), 1, 1, False),
        Case("perm_2of2", ("a", "b"), 2, 2, False),
        Case("perm_1of3", ("a", "b", "c"), 1, 1, False),
        Case("perm_2of3", ("a", "b", "c"), 2, 2, False),
        Case("perm_3of3", ("a", "b", "c"), 3, 3, False),
        Case("perm_1of4", ("a", "b", "c", "d"), 1, 1, False),
        Case("perm_2of4", ("a", "b", "c", "d"), 2, 2, False),
        Case("perm_3of4", ("a", "b", "c", "d"), 3, 3, False),
        Case("perm_4of4", ("a", "b", "c", "d"), 4, 4, False),
        Case("perm_2of5", ("a", "b", "c", "d", "e"), 2, 2, False),
        Case("perm_3of5", ("a", "b", "c", "d", "e"), 3, 3, False),
        Case("perm_4of5", ("a", "b", "c", "d", "e"), 4, 4, False),
        Case("perm_5of5", ("a", "b", "c", "d", "e"), 5, 5, False),

        # No-repeat ranges.
        Case("perm_range_1_2_of3", ("a", "b", "c"), 1, 2, False),
        Case("perm_range_2_3_of3", ("a", "b", "c"), 2, 3, False),
        Case("perm_range_1_3_of3", ("a", "b", "c"), 1, 3, False),
        Case("perm_range_1_4_of4", ("a", "b", "c", "d"), 1, 4, False),
        Case("perm_range_2_4_of4", ("a", "b", "c", "d"), 2, 4, False),
        Case("perm_range_3_5_of5", ("a", "b", "c", "d", "e"), 3, 5, False),

        # No-repeat end clamp: program must behave like permutations only up to len(words).
        Case("perm_end_clamp_1_9_of3", ("a", "b", "c"), 1, 9, False),
        Case("perm_end_clamp_2_9_of3", ("a", "b", "c"), 2, 9, False),
        Case("perm_end_clamp_3_9_of3", ("a", "b", "c"), 3, 9, False),
        Case("perm_end_clamp_4_9_of4", ("a", "b", "c", "d"), 4, 9, False),

        # No-repeat treats equal values as distinct positions, exactly like itertools.permutations.
        Case("perm_positional_dupes_1", ("a", "a", "b"), 1, 1, False),
        Case("perm_positional_dupes_2", ("a", "a", "b"), 2, 2, False),
        Case("perm_positional_dupes_3", ("a", "a", "b"), 3, 3, False),
        Case("perm_positional_dupes_range", ("a", "a", "b"), 1, 3, False),
        Case("perm_all_equal_2of3", ("x", "x", "x"), 2, 2, False),
        Case("perm_all_equal_3of3", ("x", "x", "x"), 3, 3, False),

        # No-repeat with multi-byte-length words as opaque tokens.
        Case("perm_multilen_1", ("ab", "c", "def"), 1, 1, False),
        Case("perm_multilen_2", ("ab", "c", "def"), 2, 2, False),
        Case("perm_multilen_3", ("ab", "c", "def"), 3, 3, False),
        Case("perm_multilen_range", ("ab", "c", "def"), 1, 3, False),
        Case("perm_numeric_tokens", ("12", "34", "56"), 2, 3, False),
        Case("perm_punctuation_tokens", ("a!", "b?", "c_"), 2, 3, False),
        Case("perm_mixed_case_tokens", ("Aa", "bB", "CC"), 2, 3, False),

        # Repeat: exactly itertools.product(words, repeat=k).
        Case("product_1of1_single", ("a",), 1, 1, True),
        Case("product_1of2", ("a", "b"), 1, 1, True),
        Case("product_2of2", ("a", "b"), 2, 2, True),
        Case("product_3of2", ("a", "b"), 3, 3, True),
        Case("product_4of2", ("a", "b"), 4, 4, True),
        Case("product_1of3", ("a", "b", "c"), 1, 1, True),
        Case("product_2of3", ("a", "b", "c"), 2, 2, True),
        Case("product_3of3", ("a", "b", "c"), 3, 3, True),
        Case("product_4of3", ("a", "b", "c"), 4, 4, True),
        Case("product_2of4", ("a", "b", "c", "d"), 2, 2, True),
        Case("product_3of4", ("a", "b", "c", "d"), 3, 3, True),
        Case("product_4of4", ("a", "b", "c", "d"), 4, 4, True),

        # Repeat ranges.
        Case("product_range_1_2_of2", ("a", "b"), 1, 2, True),
        Case("product_range_1_3_of2", ("a", "b"), 1, 3, True),
        Case("product_range_2_4_of2", ("a", "b"), 2, 4, True),
        Case("product_range_1_2_of3", ("a", "b", "c"), 1, 2, True),
        Case("product_range_2_3_of3", ("a", "b", "c"), 2, 3, True),
        Case("product_range_1_4_of3", ("a", "b", "c"), 1, 4, True),

        # Repeat is not clamped by word count.
        Case("product_not_clamped_3_of2", ("a", "b"), 3, 3, True),
        Case("product_not_clamped_4_of2", ("a", "b"), 4, 4, True),
        Case("product_not_clamped_5_of2", ("a", "b"), 5, 5, True),
        Case("product_not_clamped_range_3_5_of2", ("a", "b"), 3, 5, True),

        # Repeat with duplicate values: values are positional, exactly like itertools.product.
        Case("product_positional_dupes_1", ("a", "a", "b"), 1, 1, True),
        Case("product_positional_dupes_2", ("a", "a", "b"), 2, 2, True),
        Case("product_positional_dupes_3", ("a", "a", "b"), 3, 3, True),
        Case("product_positional_dupes_range", ("a", "a", "b"), 1, 3, True),
        Case("product_all_equal_2of3", ("x", "x", "x"), 2, 2, True),
        Case("product_all_equal_3of3", ("x", "x", "x"), 3, 3, True),

        # Repeat with opaque multi-length tokens.
        Case("product_multilen_1", ("ab", "c", "def"), 1, 1, True),
        Case("product_multilen_2", ("ab", "c", "def"), 2, 2, True),
        Case("product_multilen_3", ("ab", "c", "def"), 3, 3, True),
        Case("product_multilen_range", ("ab", "c", "def"), 1, 3, True),
        Case("product_numeric_tokens", ("12", "34", "56"), 2, 3, True),
        Case("product_punctuation_tokens", ("a!", "b?", "c_"), 2, 3, True),
        Case("product_mixed_case_tokens", ("Aa", "bB", "CC"), 2, 3, True),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--permutator", default="./permutator")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--check-order", action="store_true", help="Also require exact output order. Sorted multiset check is always enforced.")
    ap.add_argument("--skip-bench-smoke", action="store_true", help="Skip the small bench.py non-bench output-verification smoke test.")
    args = ap.parse_args()

    permutator = Path(args.permutator).expanduser().resolve()
    if not permutator.exists():
        die(f"permutator not found: {permutator}")
    if not permutator.is_file():
        die(f"permutator is not a file: {permutator}")
    if not os.access(permutator, os.X_OK):
        die(f"permutator is not executable: {permutator}")

    tmp = Path(tempfile.mkdtemp(prefix="perm_check_"))
    print(f"[*] tmp: {tmp}")
    print("[*] oracle: Python stdlib itertools only")

    try:
        for case in cases():
            got = tmp / f"{case.name}.got"
            exp = tmp / f"{case.name}.expected"

            expected = expected_lines(case)
            expected_n = expected_count(case)
            if len(expected) != expected_n:
                die(f"internal stdlib count mismatch for {case.name}: materialized={len(expected)} formula={expected_n}")
            write_expected(exp, expected)
            run(make_cmd(permutator, case, got), args.timeout)

            got_lines = count_lines(got)
            exp_lines = count_lines(exp)
            if got_lines != exp_lines:
                print(f"\n[FAIL] {case.name}")
                print(f"line count mismatch: got={got_lines} expected={exp_lines}")
                print(f"got={got}")
                print(f"expected={exp}")
                return 2

            got_hash = sorted_copy_hash(got, tmp)
            exp_hash = sorted_copy_hash(exp, tmp)
            if got_hash != exp_hash:
                print(f"\n[FAIL] {case.name}")
                print("sorted multiset hash mismatch against itertools")
                print(f"got      {got_hash} {got}")
                print(f"expected {exp_hash} {exp}")
                print("debug:")
                print(f"  LC_ALL=C sort {got} > /tmp/got.sorted")
                print(f"  LC_ALL=C sort {exp} > /tmp/exp.sorted")
                print("  comm -3 /tmp/got.sorted /tmp/exp.sorted | head -100")
                return 3

            if args.check_order:
                got_raw = sha256_file(got)
                exp_raw = sha256_file(exp)
                if got_raw != exp_raw:
                    print(f"\n[FAIL] {case.name}")
                    print("exact order mismatch against itertools")
                    print(f"got      {got_raw} {got}")
                    print(f"expected {exp_raw} {exp}")
                    print("debug:")
                    print(f"  diff -u {exp} {got} | head -200")
                    return 4

            mode = "product" if case.repeat else "permutations"
            print(f"[OK] {case.name:38s} {mode:12s} lines={got_lines:8d} hash={got_hash[:16]}")

        print("\n[+] itertools correctness: PASS")
        if not args.skip_bench_smoke:
            run_bench_smoke(permutator, args.timeout)
        print("\n[+] correctness: PASS")
        return 0

    finally:
        if args.keep:
            print(f"[*] kept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
