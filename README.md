# permutator

Personalized word list permutation generator

`permutator` generates ordered token permutations without repetition by default, or Cartesian-product candidates with `--repeat`, optionally expanding shortened token forms and applying deterministic string transformations.

Output is streamed to a file through a large buffered `write(2)` path.

## Build

```sh
make
```

The root `Makefile` delegates to `src/Makefile` and writes the binary to:

```text
./permutator
```

Equivalent direct build from `src/`:

```sh
cd src
make clean all
```

Debug build:

```sh
make -C src clean all DEBUG=1
```

Custom compiler:

```sh
make clean all CC=clang
```

## Synopsis

```sh
./permutator --start <s> --end <e> [options] <token_1> ... <token_W>
```

## Parameters

### Required generation bounds

| Option | Argument | Meaning |
|---|---:|---|
| `--start`, `-s` | positive integer | Minimum candidate token length `s`. |
| `--end`, `-e` | positive integer | Maximum candidate token length `e`. |

Generation requires at least one input token after the options.

### Output

| Option | Argument | Meaning |
|---|---:|---|
| `--output`, `-o` | path | Output file path. Default: `out.txt`. Use `-` to discard output through `/dev/null`. |

`--output -` is intended for throughput benchmarking. It discards generated candidates through `/dev/null` without output-file preallocation or final truncation.

### Transform modifiers

| Option | Argument | Meaning |
|---|---:|---|
| `--last`, `-l` | comma-separated strings | Append each suffix to generated candidates. |
| `--connectors`, `-c` | string of chars | Insert each character as a connector between adjacent tokens. |
| `--upper`, `-u` | `first`, `full` | Emit uppercase-transformed variants. |
| `--leet`, `-k` | `vowel`, `full` | Emit leet-transformed variants. |
| `--reverse`, `-r` | `words`, `full` | Emit reversed variants. |
| `--only_transformations`, `-p` | none | Emit only candidates produced by transformations. |
| `--repeat` | none | Allow the same input token to be selected more than once. |

## Token model

Let the input token list be:

```math
T = (t_1, t_2, \dots, t_W)
```

For each `k ∈ [s,e]`, `permutator` selects a subset of `k` distinct input tokens and emits all `k!` orderings.

With `--repeat`, selection switches from distinct-token permutations to Cartesian-product generation with replacement. For each `k ∈ [s,e]`, every position can use any input token, so the base count becomes `W^k` instead of `W!/(W-k)!`.

Input order does not restrict which orderings can be emitted. It may still affect traversal order.

The mathematical formulas treat input positions as distinct tokens. If the same string is passed more than once, different generation paths may collide in output text.

Example:

```sh
./permutator --start 2 --end 2 john titor ibm
```

Base permutations include:

```text
johntitor
titorjohn
johnibm
ibmjohn
titoribm
ibmtitor
```

With repetition enabled:

```sh
./permutator --start 2 --end 2 --repeat a b c
```

Base output is the Cartesian product:

```text
aa
ab
ac
ba
bb
bc
ca
cb
cc
```

## Comma-form tokens

A token containing `,` defines a two-form token:

```text
base,suffix
```

It expands to:

```text
base
basesuffix
```

Example:

```text
tit,or
```

represents:

```text
tit
titor
```

For a selected subset `S`, if `d(S)` selected tokens contain comma forms, the comma expansion factor is:

```math
2^{d(S)}
```

Comma-form expansion is internal to the token. It does not create an extra independent token.
In `--repeat` mode, comma-form expansion is counted per selected position. Reusing the same comma-form token twice contributes two independent expansion choices.
The current parser uses the first comma as the split point; extra commas are not interpreted as additional forms.

## Modifiers

### Repetition: `--repeat`

```sh
--repeat
```

By default, `permutator` uses each selected input token at most once per candidate.

With `--repeat`, every candidate position can reuse any input token. Generation becomes a Cartesian product over the input token list instead of a permutation of distinct selected tokens.

For `W` input tokens and exact length `k`, the base count changes from:

```math
\frac{W!}{(W-k)!}
```

to:

```math
W^k
```

Example:

```sh
./permutator --start 2 --end 2 --repeat a b c
```

```text
aa
ab
ac
ba
bb
bc
ca
cb
cc
```

### Suffixes: `--last`

```sh
./permutator --start 2 --end 2 --last '1,123,!' john titor
```

For suffix set:

```math
L = \{\ell_1,\dots,\ell_\lambda\}
```

the suffix multiplier is:

```math
1 + \lambda
```

unless `--only_transformations` suppresses the unmodified candidate.

### Connectors: `--connectors`

```sh
./permutator --start 3 --end 3 --connectors '._-' john titor ibm
```

For a candidate of length `k`, there are `k-1` internal boundaries.

If the connector alphabet has size `c`, the connector multiplier is:

```math
1 + (k-1)c
```

not `1 + c`.

Connectors are inserted one boundary at a time, not in every boundary simultaneously.

### Uppercase: `--upper`

```sh
--upper first
--upper full
```

Modes:

```text
first : uppercase first character if lowercase
full  : uppercase every lowercase character
```

Let:

```math
U(x)=
\begin{cases}
2 & \text{if uppercase transform changes } x\\
1 & \text{otherwise}
\end{cases}
```

### Leet: `--leet`

```sh
--leet vowel
--leet full
```

`vowel` map:

```text
a/A -> 4
e/E -> 3
i/I -> 1
o/O -> 0
```

`full` adds:

```text
s/S -> 5
t/T -> 7
g/G -> 9
z/Z -> 2
```

Let:

```math
K(x)=
\begin{cases}
2 & \text{if leet transform changes } x\\
1 & \text{otherwise}
\end{cases}
```

### Reverse: `--reverse`

```sh
--reverse words
--reverse full
```

`words` emits a reversed-character variant of the concatenated candidate before later suffix/leet/upper processing.
Despite the flag name, the current implementation does not reverse token order.

`full` emits a reversed-character variant after other transformations.

Example:

```sh
./permutator --start 2 --end 2 --reverse words john titor
```

emits `johntitor` and `rotitnhoj`, not `titorjohn` as the reverse variant of `johntitor`.

`reverse words` and `reverse full` act at different stages:

- `reverse words`: reverse the current base string first, then apply suffix/leet/upper handling to that reversed seed.
- `reverse full`: after a concrete string variant is formed, also emit its full character reversal.

Both reverse modes are gated by the program's internal "useful reverse" heuristic, so exact reverse counts remain candidate-dependent.

### Only transformed output: `--only_transformations`

```sh
--only_transformations
```

By default, `permutator` emits the base candidate and every enabled transformed variant.

With `--only_transformations`, the unmodified base candidate is suppressed and only candidates produced by enabled transformations are emitted.

## Generation count

```math
W = \text{number of input tokens}
```

```math
m = \#\{t \in T : t \text{ is comma-form}\}
```

```math
s = \texttt{--start}
```

```math
e = \texttt{--end}
```

For a selected subset:

```math
S \subseteq T,\quad s \le |S| \le e
```

For a concrete emitted token ordering in default non-repeat mode, write:

```math
\pi = (p_1,\dots,p_k) \text{ is a permutation of } S
```

define:

```math
k = |S|
```

```math
d(S) = \#\{t \in S : t \text{ is comma-form}\}
```

For repeat mode, let a generated token sequence be:

```math
Q = (q_1,\dots,q_k),\quad q_i \in T
```

and define:

```math
d(Q) = \#\{i : q_i \text{ is comma-form}\}
```

```math
c = |\texttt{connectors}|
```

```math
\lambda = |\texttt{last}|
```

The formulas below assume normal emission mode, where the unmodified base candidate is emitted. With `--only_transformations`, the unmodified base contribution is suppressed, so exact counts depend on which enabled transformations actually change each candidate.

Counts are generation-path emission counts, not guaranteed unique output-line counts. If different paths produce the same string, `permutator` does not promise global output deduplication.

In default non-repeat mode, the base number of ordered candidates before modifiers is:

```math
N_0
=
\sum_{k=s}^{\min(e,W)}
\binom{W}{k}k!
=
\sum_{k=s}^{\min(e,W)}
\frac{W!}{(W-k)!}
```

With `--repeat`, the base count is instead:

```math
N_{0,repeat}
=
\sum_{k=s}^{e} W^k
```

With comma-form expansion and structural modifiers in default non-repeat mode:

```math
N_{\text{struct}}
=
\sum_{\substack{S \subseteq T \\ s \le |S| \le e}}
|S|!
\cdot 2^{d(S)}
\cdot \left(1 + (|S|-1)c\right)
\cdot (1+\lambda)
```

With `--repeat`, subsets disappear. The structural count is over all ordered token sequences with replacement:

```math
N_{\text{struct,repeat}}
=
\sum_{k=s}^{e}
\sum_{Q \in T^k}
2^{d(Q)}
\cdot \left(1 + (k-1)c\right)
\cdot (1+\lambda)
```

If no comma-form tokens are used, this simplifies to:

```math
N_{\text{struct,repeat}}
=
\sum_{k=s}^{e}
W^k
\left(1 + (k-1)c\right)
(1+\lambda)
```

More generally, because each repeated position contributes weight `1` for a normal token and `2` for a comma-form token:

```math
\sum_{Q \in T^k} 2^{d(Q)} = (W+m)^k
```

so the repeat structural count can also be written as:

```math
N_{\text{struct,repeat}}
=
\sum_{k=s}^{e}
(W+m)^k
\left(1 + (k-1)c\right)
(1+\lambda)
```

Transform modifiers are value-dependent because uppercase, leet, and reverse may not change every candidate.
Because these transforms are staged and can interact, the symbols `U(x)`, `K(x)`, `R_w(x)`, and `R_f(x)` below are not an exact multiplicative decomposition of total output count in the general case. They are used to express safe candidate-level factors and upper bounds.

The implemented mutating pipeline is:

```text
base candidate
-> optional reverse-words seed
-> optional suffix append
-> optional leet variant
-> optional uppercase variant
-> optional reverse-full variant
```

`--connectors` produces alternate base candidates before this pipeline runs.

For a concrete generated string `x`, define:

```math
U(x)=1+\mathbf{1}_{upper(x)\ne x}
```

```math
K(x)=1+\mathbf{1}_{leet(x)\ne x}
```

```math
R_w(x)\in\{1,2\}
```

```math
R_f(x)\in\{1,2\}
```

A practical upper bound for default non-repeat mode is:

```math
N
\le
\sum_{\substack{S \subseteq T \\ s \le |S| \le e}}
|S|!
\cdot 2^{d(S)}
\cdot \left(1 + (|S|-1)c\right)
\cdot (1+\lambda)
\cdot U_{\max}
\cdot K_{\max}
\cdot R_{w,\max}
\cdot R_{f,\max}
```

For `--repeat`, the analogous bound is:

```math
N_{repeat}
\le
\sum_{k=s}^{e}
\sum_{Q \in T^k}
2^{d(Q)}
\cdot \left(1 + (k-1)c\right)
\cdot (1+\lambda)
\cdot U_{\max}
\cdot K_{\max}
\cdot R_{w,\max}
\cdot R_{f,\max}
```

The exact reverse multipliers are candidate-dependent, so the upper bounds use `R_{w,\max}` and `R_{f,\max}`.

where:

```math
U_{\max} =
\begin{cases}
2 & \text{if } --upper \text{ is enabled}\\
1 & \text{otherwise}
\end{cases}
```

```math
K_{\max} =
\begin{cases}
2 & \text{if } --leet \text{ is enabled}\\
1 & \text{otherwise}
\end{cases}
```

```math
R_{w,\max} =
\begin{cases}
2 & \text{if } --reverse\ words \text{ is enabled}\\
1 & \text{otherwise}
\end{cases}
```

```math
R_{f,\max} =
\begin{cases}
2 & \text{if } --reverse\ full \text{ is enabled}\\
1 & \text{otherwise}
\end{cases}
```

If no comma-form tokens are used, the default non-repeat bound simplifies to:

```math
N
\le
\sum_{k=s}^{\min(e,W)}
\binom{W}{k}
k!
\left(1+(k-1)c\right)
(1+\lambda)
U_{\max}
K_{\max}
R_{w,\max}
R_{f,\max}
```

If no comma-form tokens are used, the repeat-mode bound simplifies to:

```math
N_{repeat}
\le
\sum_{k=s}^{e}
W^k
\left(1+(k-1)c\right)
(1+\lambda)
U_{\max}
K_{\max}
R_{w,\max}
R_{f,\max}
```

With comma-form tokens in repeat mode, the analogous bound is:

```math
N_{repeat}
\le
\sum_{k=s}^{e}
(W+m)^k
\left(1+(k-1)c\right)
(1+\lambda)
U_{\max}
K_{\max}
R_{w,\max}
R_{f,\max}
```

The default mode grows factorially in `k`; repeat mode grows exponentially as `W^k`. Large `--end` values explode quickly in both modes.

## Examples

All permutations of exactly 11 tokens:

```sh
./permutator --start 11 --end 11 --output out.txt a b c d e f g h i l m
```

All permutations from length 1 to 11:

```sh
./permutator --start 1 --end 11 --output out.txt a b c d e f g h i l m
```

All repeated ordered candidates of exactly 4 characters from a small alphabet:

```sh
./permutator --start 4 --end 4 --repeat --output out.txt a b c d e f
```

All repeated candidates from length 2 to 4:

```sh
./permutator --start 2 --end 4 --repeat --output out.txt john titor ibm
```

Length 3 to 5, with connectors and suffixes:

```sh
./permutator --start 3 --end 5 \
  --last 0,1 \
  --connectors ,. \
  --output out.txt \
  a b c d e f g h i l m
```

Name-style generation:

```sh
./permutator --start 2 --end 4 \
  --connectors . \
  --last '!,?,2024,24' \
  --leet vowel \
  --upper first \
  --output out.txt \
  john tit,or ibm time travel
```

Only transformed candidates:

```sh
./permutator --start 2 --end 4 \
  --connectors . \
  --last '!,?,2024,24' \
  --leet vowel \
  --upper first \
  --only_transformations \
  --output out.txt \
  john tit,or ibm time travel
```

## Testing

Run the correctness suite:

```sh
python3 tests/check_corretness.py --permutator ./permutator
```

This checks generated output against independent Python standard-library oracles and runs a compact `bench.py` smoke test in correctness-check mode.

## Benchmarking

Correctness-verified benchmark run:

```sh
python3 tests/bench.py --permutator ./permutator --runs 1
```

Throughput-only benchmark run:

```sh
python3 tests/bench.py --permutator ./permutator --bench --runs 5
```

In `--bench` mode, `bench.py` invokes `permutator` through `--output -`, while competitor pipelines discard output through `/dev/null`.
