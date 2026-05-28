# permutator

Personalized word list permutation generator

`permutator` generates ordered token permutations without repetition, optionally expanding shortened token forms and applying deterministic string transformations.

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

### Required in permutation mode

| Option | Argument | Meaning |
|---|---:|---|
| `--start`, `-s` | positive integer | Minimum subset size `s`. |
| `--end`, `-e` | positive integer | Maximum subset size `e`. |

Permutation mode requires at least one input token after the options.

### Output

| Option | Argument | Meaning |
|---|---:|---|
| `--output`, `-o` | path | Output file path. Default: `out.txt`. |

### Transform modifiers

| Option | Argument | Meaning |
|---|---:|---|
| `--last`, `-l` | comma-separated strings | Append each suffix to generated candidates. |
| `--connectors`, `-c` | string of chars | Insert each character as a connector between adjacent tokens. |
| `--upper`, `-u` | `first`, `full` | Emit uppercase-transformed variants. |
| `--leet`, `-k` | `vowel`, `full` | Emit leet-transformed variants. |
| `--reverse`, `-r` | `words`, `full` | Emit reversed variants. |
| `--only_transformations`, `-p` | none | Emit only candidates produced by transformations. |

## Token model

Let the input token list be:

```math
T = (t_1, t_2, \dots, t_W)
```

For each `k ∈ [s,e]`, `permutator` selects a subset of `k` distinct input tokens and emits all `k!` orderings.

Input order does not constrain output order.

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

## Modifiers

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

`words` reverses the generated string before later transformations.

`full` emits a reversed-character variant after other transformations.

Reverse is skipped when it is semantically useless for the selected token set, specifically when all selected tokens are one-character tokens or all selected non-one-character tokens are palindromes.

Let:

```math
\rho(S)=
\begin{cases}
1 & \text{if reverse is useful for } S\\
0 & \text{otherwise}
\end{cases}
```

Then:

```math
R_w(S)=1+\mathbf{1}_{reverse\_words}\rho(S)
```

```math
R_f(S)=1+\mathbf{1}_{reverse\_full}\rho(S)
```

## Generation count

Let:

```math
W = \text{number of input tokens}
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

define:

```math
k = |S|
```

```math
d(S) = \#\{t \in S : t \text{ is comma-form}\}
```

```math
c = |\texttt{connectors}|
```

```math
\lambda = |\texttt{last}|
```

The base number of ordered candidates before modifiers is:

```math
N_0
=
\sum_{k=s}^{e}
\binom{W}{k}k!
=
\sum_{k=s}^{e}
\frac{W!}{(W-k)!}
```

With comma-form expansion and structural modifiers:

```math
N_{\text{struct}}
=
\sum_{\substack{S \subseteq T \\ s \le |S| \le e}}
|S|!
\cdot 2^{d(S)}
\cdot \left(1 + (|S|-1)c\right)
\cdot (1+\lambda)
```

Transform modifiers are value-dependent because uppercase, leet, and reverse may not change every candidate.

For a concrete generated string `x` from subset `S`, define:

```math
U(x)=1+\mathbf{1}_{upper(x)\ne x}
```

```math
K(x)=1+\mathbf{1}_{leet(x)\ne x}
```

```math
R_w(S)=1+\mathbf{1}_{reverse\_words}\rho(S)
```

```math
R_f(S)=1+\mathbf{1}_{reverse\_full}\rho(S)
```

A practical upper bound is:

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
\cdot R_w(S)
\cdot R_f(S)
```

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

If no comma-form tokens are used, this simplifies to:

```math
N
\le
\sum_{k=s}^{e}
\binom{W}{k}
k!
\left(1+(k-1)c\right)
(1+\lambda)
U_{\max}
K_{\max}
R_{w,\max}
R_{f,\max}
```

The growth is factorial in `k`. Large `--end` values explode quickly.

## Examples

All permutations of exactly 11 tokens:

```sh
./permutator --start 11 --end 11 a b c d e f g h i l m
```

All permutations from length 1 to 11:

```sh
./permutator --start 1 --end 11 a b c d e f g h i l m
```

Length 3 to 5, with connectors and suffixes:

```sh
./permutator --start 3 --end 5 \
  --last 0,1 \
  --connectors ,. \
  a b c d e f g h i l m
```

Name-style generation:

```sh
./permutator --start 2 --end 4 \
  --connectors . \
  --last '!,?,2024,24' \
  --leet vowel \
  --upper first \
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
  john tit,or ibm time travel
```
