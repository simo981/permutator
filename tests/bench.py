#!/usr/bin/env python3
import argparse
import hashlib
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SHELL = "/bin/bash" if Path("/bin/bash").exists() else "/bin/sh"


@dataclass
class ToolRun:
    name: str
    cmd_factory: Callable[[Path], str]


@dataclass
class BenchCase:
    name: str
    expected_lines: int
    runs: list[ToolRun]


def die(msg: str) -> None:
    print(f"[FATAL] {msg}", file=sys.stderr)
    sys.exit(1)


def which(name: str) -> str | None:
    return shutil.which(name)


def q(s: str | Path) -> str:
    import shlex
    return shlex.quote(str(s))


def run_shell(cmd: str, timeout: int | None = None) -> float:
    full = f"set -euo pipefail; {cmd}" if SHELL.endswith("bash") else cmd
    start = time.perf_counter()
    proc = subprocess.run(
        full,
        shell=True,
        executable=SHELL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env={**os.environ, "LC_ALL": "C"},
    )
    end = time.perf_counter()
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", errors="replace"))
        die(f"command failed:\n{cmd}")
    return end - start


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(8 * 1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def count_lines(path: Path) -> int:
    total = 0
    with path.open("rb") as f:
        while True:
            b = f.read(8 * 1024 * 1024)
            if not b:
                break
            total += b.count(b"\n")
    return total


def sorted_hash(path: Path, tmpdir: Path, sort_mem: str) -> str:
    sorted_path = tmpdir / f"{path.name}.sorted"
    run_shell(f"sort -S {q(sort_mem)} -T {q(tmpdir)} {q(path)} -o {q(sorted_path)}")
    h = sha256_file(sorted_path)
    sorted_path.unlink(missing_ok=True)
    return h


def drop_caches(enabled: bool) -> None:
    if not enabled:
        return
    if not Path("/proc/sys/vm/drop_caches").exists():
        die("drop_caches richiesto ma /proc/sys/vm/drop_caches non esiste")
    subprocess.run(["sync"], check=True)
    if os.geteuid() == 0:
        Path("/proc/sys/vm/drop_caches").write_text("3\n")
    else:
        subprocess.run(["sudo", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"], check=True)


def make_ramdir(base: str) -> Path:
    if base == "auto":
        root = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path(tempfile.gettempdir())
    else:
        root = Path(base)
    root.mkdir(parents=True, exist_ok=True)
    d = root / f"bench_wordgens_{os.getpid()}_{int(time.time())}"
    d.mkdir()
    return d


def write_lines(path: Path, lines: list[str]) -> None:
    with path.open("w", encoding="ascii", newline="\n") as f:
        for line in lines:
            f.write(line)
            f.write("\n")


def fixed_tokens(n: int, width: int) -> list[str]:
    return [f"w{i:0{width - 1}d}" for i in range(n)]


def awk_reverse_pipeline() -> str:
    return "awk '{ r=\"\"; for (i=length($0); i>0; i--) r=r substr($0,i,1); print; print r }'"


def awk_unique_fixed_chunks(k: int, width: int) -> str:
    assigns = [f"a{i}=substr($0,{i * width + 1},{width})" for i in range(k)]
    conds = []
    for i in range(k):
        for j in range(i + 1, k):
            conds.append(f"a{i}!=a{j}")
    cond = " && ".join(conds) if conds else "1"
    prog = f"length($0)=={k * width} {{{'; '.join(assigns)}; if ({cond}) print}}"
    return f"awk {q(prog)}"


def build_cases(args, work: Path) -> list[BenchCase]:
    permutator = Path(args.permutator).expanduser().resolve()
    if not permutator.exists():
        die(f"permutator not found: {permutator}")
    if not permutator.is_file():
        die(f"permutator is not a file: {permutator}")
    if not os.access(permutator, os.X_OK):
        die(f"permutator is not executable: {permutator}")

    hashcat = which("hashcat")
    crunch = which("crunch")
    combinator = which("combinator") or which("combinator.bin")

    cases: list[BenchCase] = []

    chars = args.charset
    char_words = list(chars)
    char_args = " ".join(q(c) for c in char_words)

    for k in args.crunch_k:
        expected = len(chars) ** k
        runs = [
            ToolRun(
                f"permutator_repeat_chars_k{k}",
                lambda out, kk=k: f"{q(permutator)} --start {kk} --end {kk} --repeat --output {q(out)} {char_args}",
            )
        ]
        if crunch:
            runs.append(
                ToolRun(
                    f"crunch_chars_k{k}",
                    lambda out, kk=k: f"{q(crunch)} {kk} {kk} {q(chars)} > {q(out)}",
                )
            )
        if len(runs) > 1:
            cases.append(BenchCase(f"repeat_chars_k{k}", expected, runs))

        if crunch and k >= 2:
            expected_suffix = expected * 3
            runs_suffix = [
                ToolRun(
                    f"permutator_repeat_last_k{k}",
                    lambda out, kk=k: f"{q(permutator)} --start {kk} --end {kk} --repeat --last 1,2 --output {q(out)} {char_args}",
                ),
                ToolRun(
                    f"crunch_plus_awk_suffix_k{k}",
                    lambda out, kk=k: f"{q(crunch)} {kk} {kk} {q(chars)} | awk '{{ print; print $0 \"1\"; print $0 \"2\" }}' > {q(out)}",
                ),
            ]
            cases.append(BenchCase(f"repeat_chars_last_k{k}", expected_suffix, runs_suffix))

        if crunch and k >= 2:
            expected_connectors = expected * k
            runs_connectors = [
                ToolRun(
                    f"permutator_repeat_connector_k{k}",
                    lambda out, kk=k: f"{q(permutator)} --start {kk} --end {kk} --repeat --connectors - --output {q(out)} {char_args}",
                ),
                ToolRun(
                    f"crunch_plus_awk_connector_k{k}",
                    lambda out, kk=k: f"{q(crunch)} {kk} {kk} {q(chars)} | awk '{{ print; for (i=1; i<length($0); i++) print substr($0,1,i) \"-\" substr($0,i+1) }}' > {q(out)}",
                ),
            ]
            cases.append(BenchCase(f"repeat_chars_connector_k{k}", expected_connectors, runs_connectors))

        if crunch and k >= 2:
            expected_connector_suffix = expected * k * 3
            runs_connector_suffix = [
                ToolRun(
                    f"permutator_repeat_connector_last_k{k}",
                    lambda out, kk=k: f"{q(permutator)} --start {kk} --end {kk} --repeat --connectors - --last 1,2 --output {q(out)} {char_args}",
                ),
                ToolRun(
                    f"crunch_plus_awk_connector_suffix_k{k}",
                    lambda out, kk=k: f"{q(crunch)} {kk} {kk} {q(chars)} | awk '{{ print; print $0 \"1\"; print $0 \"2\"; for (i=1; i<length($0); i++) {{ v=substr($0,1,i) \"-\" substr($0,i+1); print v; print v \"1\"; print v \"2\" }} }}' > {q(out)}",
                ),
            ]
            cases.append(BenchCase(f"repeat_chars_connector_last_k{k}", expected_connector_suffix, runs_connector_suffix))

    tokens = fixed_tokens(args.words, args.token_width)
    words_file = work / "words_fixed.txt"
    write_lines(words_file, tokens)
    token_args = " ".join(q(t) for t in tokens)
    width = len(tokens[0])

    small_tokens = fixed_tokens(args.small_words, args.token_width)
    small_words_file = work / "words_fixed_small.txt"
    write_lines(small_words_file, small_tokens)
    small_token_args = " ".join(q(t) for t in small_tokens)
    small_width = len(small_tokens[0])

    if hashcat:
        expected = args.words ** 2
        cases.append(
            BenchCase(
                "repeat_words_k2_hashcat_a1",
                expected,
                [
                    ToolRun(
                        "permutator_repeat_words_k2",
                        lambda out: f"{q(permutator)} --start 2 --end 2 --repeat --output {q(out)} {token_args}",
                    ),
                    ToolRun(
                        "hashcat_a1_stdout",
                        lambda out: f"{q(hashcat)} --quiet --stdout -a 1 {q(words_file)} {q(words_file)} > {q(out)}",
                    ),
                ],
            )
        )

        # Insert larger repeat_words_k2_hashcat_a1_larger case
        cases.append(
            BenchCase(
                "repeat_words_k2_hashcat_a1_larger",
                expected,
                [
                    ToolRun(
                        "permutator_repeat_words_k2_large",
                        lambda out: f"{q(permutator)} --start 2 --end 2 --repeat --output {q(out)} {token_args}",
                    ),
                    ToolRun(
                        "hashcat_a1_stdout_large",
                        lambda out: f"{q(hashcat)} --quiet --stdout -a 1 {q(words_file)} {q(words_file)} > {q(out)}",
                    ),
                ],
            )
        )

        expected_nr = args.words * (args.words - 1)
        filt = awk_unique_fixed_chunks(2, width)
        cases.append(
            BenchCase(
                "norepeat_words_k2_hashcat_a1_filter",
                expected_nr,
                [
                    ToolRun(
                        "permutator_norepeat_words_k2",
                        lambda out: f"{q(permutator)} --start 2 --end 2 --output {q(out)} {token_args}",
                    ),
                    ToolRun(
                        "hashcat_a1_filter_norepeat",
                        lambda out: f"{q(hashcat)} --quiet --stdout -a 1 {q(words_file)} {q(words_file)} | {filt} > {q(out)}",
                    ),
                ],
            )
        )

        # Insert norepeat_words_k2_hashcat_a1_filter_larger case
        cases.append(
            BenchCase(
                "norepeat_words_k2_hashcat_a1_filter_larger",
                expected_nr,
                [
                    ToolRun(
                        "permutator_norepeat_words_k2_large",
                        lambda out: f"{q(permutator)} --start 2 --end 2 --output {q(out)} {token_args}",
                    ),
                    ToolRun(
                        "hashcat_a1_filter_norepeat_large",
                        lambda out: f"{q(hashcat)} --quiet --stdout -a 1 {q(words_file)} {q(words_file)} | {filt} > {q(out)}",
                    ),
                ],
            )
        )

        cases.append(
            BenchCase(
                "repeat_words_k2_reverse_full_hashcat_pipe",
                expected * 2,
                [
                    ToolRun(
                        "permutator_repeat_reverse_full_k2",
                        lambda out: f"{q(permutator)} --start 2 --end 2 --repeat --reverse full --output {q(out)} {token_args}",
                    ),
                    ToolRun(
                        "hashcat_a1_plus_awk_reverse",
                        lambda out: f"{q(hashcat)} --quiet --stdout -a 1 {q(words_file)} {q(words_file)} | {awk_reverse_pipeline()} > {q(out)}",
                    ),
                ],
            )
        )

    # Insert hashcat-comparable small-token k=3 cases before combinator
    if hashcat:
        expected_k3_small = args.small_words ** 3
        intermediate_k2 = work / "hashcat_small_k2.tmp"
        cases.append(
            BenchCase(
                "repeat_words_k3_hashcat_chained_small",
                expected_k3_small,
                [
                    ToolRun(
                        "permutator_repeat_words_k3_small",
                        lambda out: f"{q(permutator)} --start 3 --end 3 --repeat --output {q(out)} {small_token_args}",
                    ),
                    ToolRun(
                        "hashcat_a1_chained_k3_small",
                        lambda out: f"{q(hashcat)} --quiet --stdout -a 1 {q(small_words_file)} {q(small_words_file)} > {q(intermediate_k2)} && {q(hashcat)} --quiet --stdout -a 1 {q(intermediate_k2)} {q(small_words_file)} > {q(out)}",
                    ),
                ],
            )
        )

        filt_k3_small = awk_unique_fixed_chunks(3, small_width)
        expected_k3_nr_small = args.small_words * (args.small_words - 1) * (args.small_words - 2)
        cases.append(
            BenchCase(
                "norepeat_words_k3_hashcat_chained_filter_small",
                expected_k3_nr_small,
                [
                    ToolRun(
                        "permutator_norepeat_words_k3_small",
                        lambda out: f"{q(permutator)} --start 3 --end 3 --output {q(out)} {small_token_args}",
                    ),
                    ToolRun(
                        "hashcat_a1_chained_filter_norepeat_k3_small",
                        lambda out: f"{q(hashcat)} --quiet --stdout -a 1 {q(small_words_file)} {q(small_words_file)} > {q(intermediate_k2)} && {q(hashcat)} --quiet --stdout -a 1 {q(intermediate_k2)} {q(small_words_file)} | {filt_k3_small} > {q(out)}",
                    ),
                ],
            )
        )

        cases.append(
            BenchCase(
                "repeat_words_k3_reverse_hashcat_chained_small",
                expected_k3_small * 2,
                [
                    ToolRun(
                        "permutator_repeat_reverse_full_k3_small",
                        lambda out: f"{q(permutator)} --start 3 --end 3 --repeat --reverse full --output {q(out)} {small_token_args}",
                    ),
                    ToolRun(
                        "hashcat_a1_chained_plus_awk_reverse_k3_small",
                        lambda out: f"{q(hashcat)} --quiet --stdout -a 1 {q(small_words_file)} {q(small_words_file)} > {q(intermediate_k2)} && {q(hashcat)} --quiet --stdout -a 1 {q(intermediate_k2)} {q(small_words_file)} | {awk_reverse_pipeline()} > {q(out)}",
                    ),
                ],
            )
        )

    if combinator:
        expected = args.words ** 2
        cases.append(
            BenchCase(
                "repeat_words_k2_hashcat_utils_combinator",
                expected,
                [
                    ToolRun(
                        "permutator_repeat_words_k2",
                        lambda out: f"{q(permutator)} --start 2 --end 2 --repeat --output {q(out)} {token_args}",
                    ),
                    ToolRun(
                        "hashcat_utils_combinator",
                        lambda out: f"{q(combinator)} {q(words_file)} {q(words_file)} > {q(out)}",
                    ),
                ],
            )
        )

        # Insert additional small k=3 chained combinator case
        expected_small_k3 = args.small_words ** 3
        combinator_intermediate_k2 = work / "combinator_small_k2.tmp"
        cases.append(
            BenchCase(
                "repeat_words_k3_hashcat_utils_combinator_chained_small",
                expected_small_k3,
                [
                    ToolRun(
                        "permutator_repeat_words_k3_small",
                        lambda out: f"{q(permutator)} --start 3 --end 3 --repeat --output {q(out)} {small_token_args}",
                    ),
                    ToolRun(
                        "hashcat_utils_combinator_chained_k3_small",
                        lambda out: f"{q(combinator)} {q(small_words_file)} {q(small_words_file)} > {q(combinator_intermediate_k2)} && {q(combinator)} {q(combinator_intermediate_k2)} {q(small_words_file)} > {q(out)}",
                    ),
                ],
            )
        )

    if hashcat:
        for k in args.hashcat_word_k:
            if k != 2:
                continue
            expected = args.words ** 2
            cases.append(
                BenchCase(
                    f"repeat_words_k{k}_reverse_full_hashcat_pipe",
                    expected * 2,
                    [
                        ToolRun(
                            f"permutator_repeat_reverse_full_k{k}",
                            lambda out: f"{q(permutator)} --start 2 --end 2 --repeat --reverse full --output {q(out)} {token_args}",
                        ),
                        ToolRun(
                            f"hashcat_a1_plus_awk_reverse_k{k}",
                            lambda out: f"{q(hashcat)} --quiet --stdout -a 1 {q(words_file)} {q(words_file)} | {awk_reverse_pipeline()} > {q(out)}",
                        ),
                    ],
                )
            )
            cases.append(
                BenchCase(
                    f"repeat_words_k{k}_last_hashcat_pipe",
                    expected * 3,
                    [
                        ToolRun(
                            f"permutator_repeat_last_k{k}",
                            lambda out: f"{q(permutator)} --start 2 --end 2 --repeat --last 1,2 --output {q(out)} {token_args}",
                        ),
                        ToolRun(
                            f"hashcat_a1_plus_awk_suffix_k{k}",
                            lambda out: f"{q(hashcat)} --quiet --stdout -a 1 {q(words_file)} {q(words_file)} | awk '{{ print; print $0 \"1\"; print $0 \"2\" }}' > {q(out)}",
                        ),
                    ],
                )
            )
            cases.append(
                BenchCase(
                    f"repeat_words_k{k}_connector_hashcat_pipe",
                    expected * 2,
                    [
                        ToolRun(
                            f"permutator_repeat_connector_k{k}",
                            lambda out: f"{q(permutator)} --start 2 --end 2 --repeat --connectors - --output {q(out)} {token_args}",
                        ),
                        ToolRun(
                            f"hashcat_a1_plus_awk_connector_k{k}",
                            lambda out: f"{q(hashcat)} --quiet --stdout -a 1 {q(words_file)} {q(words_file)} | awk '{{ print; print substr($0,1,{width}) \"-\" substr($0,{width + 1}) }}' > {q(out)}",
                        ),
                    ],
                )
            )
            cases.append(
                BenchCase(
                    f"repeat_words_k{k}_connector_last_hashcat_pipe",
                    expected * 6,
                    [
                        ToolRun(
                            f"permutator_repeat_connector_last_k{k}",
                            lambda out: f"{q(permutator)} --start 2 --end 2 --repeat --connectors - --last 1,2 --output {q(out)} {token_args}",
                        ),
                        ToolRun(
                            f"hashcat_a1_plus_awk_connector_suffix_k{k}",
                            lambda out: f"{q(hashcat)} --quiet --stdout -a 1 {q(words_file)} {q(words_file)} | awk '{{ print; print $0 \"1\"; print $0 \"2\"; v=substr($0,1,{width}) \"-\" substr($0,{width + 1}); print v; print v \"1\"; print v \"2\" }}' > {q(out)}",
                        ),
                    ],
                )
            )

    return cases


def verify_outputs(case: BenchCase, outputs: list[tuple[str, Path]], tmp: Path, sort_mem: str) -> str:
    baseline_hash = None
    baseline_name = None
    for name, path in outputs:
        lines = count_lines(path)
        if lines != case.expected_lines:
            print(f"\n[FAIL] {case.name} / {name}")
            print(f"line mismatch: got={lines} expected={case.expected_lines}")
            print(f"file={path}")
            sys.exit(2)
        h = sorted_hash(path, tmp, sort_mem)
        if baseline_hash is None:
            baseline_hash = h
            baseline_name = name
        elif h != baseline_hash:
            print(f"\n[FAIL] OUTPUT MISMATCH: {case.name}")
            print(f"baseline {baseline_name}: {baseline_hash}")
            print(f"bad      {name}: {h}")
            for n, p in outputs:
                print(f"{n}: {p}")
            print("debug:")
            print(f"  LC_ALL=C sort {outputs[0][1]} > /tmp/a.sorted")
            print(f"  LC_ALL=C sort {path} > /tmp/b.sorted")
            print("  comm -3 /tmp/a.sorted /tmp/b.sorted | head -100")
            sys.exit(3)
    assert baseline_hash is not None
    return baseline_hash

# --- Per-case summary function ---
def print_case_summary(case: BenchCase, timings: dict[str, list[float]], verification: str) -> None:
    means = {name: statistics.mean(values) for name, values in timings.items() if values}
    if not means:
        return
    fastest_name = min(means, key=means.get)
    fastest_mean = means[fastest_name]
    slowest_mean = max(means.values())
    print("    " + "-" * 104)
    print(f"    {'TOOL':38} {'N':>3} {'MEAN(s)':>10} {'STDEV':>10} {'BEST':>10} {'SPEEDUP':>8} {'LINES/s':>16}")
    print("    " + "-" * 104)
    for name, values in sorted(timings.items(), key=lambda item: statistics.mean(item[1])):
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0.0
        best = min(values)
        speedup = slowest_mean / mean if mean > 0 else float("inf")
        throughput = case.expected_lines / mean if mean > 0 else float("inf")
        print(f"    {name[:38]:38} {len(values):3d} {mean:10.4f} {stdev:10.4f} {best:10.4f} {speedup:7.2f}x {throughput:16.2f}")
    print("    " + "-" * 104)
    print(f"    Case summary: fastest={fastest_name}; fastest_speedup_over_slowest={slowest_mean / fastest_mean:.2f}x; {verification}")
    print("    " + "-" * 104)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--permutator", default="./permutator")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--ramdir", default="auto")
    ap.add_argument("--sort-mem", default="80%")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--drop-caches", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--bench", action="store_true", help="Benchmark-only mode: redirect outputs to /dev/null and skip line-count, sort, and hash verification.")
    ap.add_argument("--cc", action="store_true", help="Compact correctness-check mode: verify outputs but suppress benchmark tables and noisy per-run logs.")
    ap.add_argument("--charset", default="abcdefghijkl")
    ap.add_argument("--crunch-k", type=int, nargs="+", default=[5, 6, 7])
    ap.add_argument("--hashcat-word-k", type=int, nargs="+", default=[2])
    ap.add_argument("--words", type=int, default=64)
    ap.add_argument("--small-words", type=int, default=16)
    ap.add_argument("--token-width", type=int, default=4)
    args = ap.parse_args()

    if args.runs < 1:
        die("--runs must be >= 1")

    if args.words < 2:
        die("--words must be >= 2")
    if args.small_words < 3:
        die("--small-words must be >= 3")
    if args.token_width < 2:
        die("--token-width must be >= 2")
    if args.cc and args.bench:
        die("--cc cannot be combined with --bench")

    if args.drop_caches and os.geteuid() != 0:
        subprocess.run(["sudo", "-v"], check=True)

    work = make_ramdir(args.ramdir)
    if args.cc:
        print(f"[*] bench smoke workdir: {work}")
    else:
        print(f"[*] workdir: {work}")

    try:
        cases = build_cases(args, work)
        if not cases:
            die("no comparable competitor found: install hashcat/crunch/hashcat-utils")

        all_results: dict[str, dict[str, list[float]]] = {}
        hashes: dict[str, str] = {}

        for case in cases:
            if not args.cc:
                print("\n" + "=" * 90)
                print(f"CASE: {case.name} expected_lines={case.expected_lines}")
                print("=" * 90)
            all_results[case.name] = {r.name: [] for r in case.runs}

            for i in range(1, args.runs + 1):
                if not args.cc:
                    print(f"[*] run {i}/{args.runs}")
                outputs: list[tuple[str, Path]] = []

                for r in case.runs:
                    if args.bench:
                        if r.name.startswith("permutator_"):
                            out = Path("-")
                        else:
                            out = Path(os.devnull)
                    else:
                        out = work / f"{case.name}.{r.name}.run{i}.out"
                        out.unlink(missing_ok=True)
                    drop_caches(args.drop_caches)
                    cmd = r.cmd_factory(out)
                    t = run_shell(cmd, timeout=args.timeout)
                    all_results[case.name][r.name].append(t)
                    if not args.bench:
                        outputs.append((r.name, out))
                        if not args.cc:
                            print(f"    {r.name:38s} {t:9.4f}s size={out.stat().st_size}")
                    elif r.name.startswith("permutator_"):
                        if not args.cc:
                            print(f"    {r.name:38s} {t:9.4f}s output=permutator-null")
                    else:
                        if not args.cc:
                            print(f"    {r.name:38s} {t:9.4f}s output=/dev/null")

                if args.bench:
                    hashes[case.name] = "not_verified_bench_mode"
                    if not args.cc:
                        print("    verification skipped: --bench mode discards output through permutator --output - and competitor /dev/null")
                else:
                    h = verify_outputs(case, outputs, work, args.sort_mem)
                    hashes[case.name] = h
                    if not args.cc:
                        print(f"    verified sorted-sha256={h[:16]}")

                    if not args.keep:
                        for _, p in outputs:
                            p.unlink(missing_ok=True)

            # Per-case summary after all runs for this case
            if args.cc:
                tools = ",".join(r.name for r in case.runs)
                print(f"[OK] bench_{case.name:44s} lines={case.expected_lines:8d} hash={hashes[case.name][:16]} tools={tools}")
            elif args.bench:
                print_case_summary(case, all_results[case.name], "verification=skipped (--bench; permutator=--output -; competitors=/dev/null)")
            else:
                print_case_summary(case, all_results[case.name], f"verified_sorted_sha256={hashes[case.name][:16]}")

        if args.cc:
            print("\n[+] bench smoke: PASS")
            return 0

        print("\n" + "=" * 132)
        print(f"{'CASE':42} {'TOOL':42} {'N':>3} {'MEAN(s)':>10} {'STDEV':>10} {'BEST':>10} {'SPEEDUP':>8} {'THROUGHPUT lines/s':>20}")
        print("=" * 132)

        for case_name, tools in all_results.items():
            means = {name: statistics.mean(ts) for name, ts in tools.items()}
            fastest = min(means.values())
            winner = min(means, key=means.get)
            slowest = max(means.values())

            for name, ts in sorted(tools.items(), key=lambda kv: statistics.mean(kv[1])):
                mean = statistics.mean(ts)
                stdev = statistics.stdev(ts) if len(ts) > 1 else 0.0
                best = min(ts)
                speedup = slowest / mean if mean > 0 else float("inf")
                case_obj = next(c for c in cases if c.name == case_name)
                throughput = case_obj.expected_lines / mean if mean > 0 else float("inf")
                print(f"{case_name[:42]:42} {name[:42]:42} {len(ts):3d} {mean:10.4f} {stdev:10.4f} {best:10.4f} {speedup:7.2f}x {throughput:20.2f}")

            print("-" * 132)
            if args.bench:
                print(f"Summary: fastest={winner}; fastest_speedup_over_slowest={slowest / fastest:.2f}x; verification=skipped (--bench; permutator=--output -; competitors=/dev/null)")
            else:
                print(f"Summary: fastest={winner}; fastest_speedup_over_slowest={slowest / fastest:.2f}x; verified_sorted_sha256={hashes[case_name][:16]}")
            print("-" * 132)

        return 0

    finally:
        if args.keep:
            print(f"[*] kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
