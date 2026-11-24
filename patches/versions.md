 Tool versions and environment

All six evaluated tools are pinned to the versions used by Liu et al.
(ICSE '26, Table 1), so that figures reported here are directly
comparable to theirs.

## Evaluated tools

| Tool | Version | Matches upstream Table 1 | How pinned | Detection technique (upstream Table 1) |
|---|---|---|---|---|
| Bandit | 1.8.0 | yes | `pip install bandit==1.8.0` | pattern matching + heuristic |
| Bearer | 1.49.0 | yes | installer `-b /usr/local/bin v1.49.0` | pattern matching + heuristic |
| CodeQL | 2.20.0 | yes | CLI and queries pinned to tag `codeql-cli/v2.20.0` | taint analysis (pattern matching secondary) |
| DevSkim | 1.0.59 | yes | `COPY ./DevSkim_CLI_linux_1.0.59` (binary reports `1.0.59+ae389f54ac`) | pattern matching |
| Dlint | 0.16.0 | yes | `pip install dlint==0.16.0` | pattern matching |
| Semgrep | 1.101.0 | yes | `pip install semgrep==1.101.0` | pattern matching (taint analysis secondary) |

The DevSkim image copies the CLI 1.0.59 Linux release into the build
context rather than installing from a package feed. Obtain it from
<https://github.com/microsoft/DevSkim/releases> (tag v1.0.59) and
extract to `./DevSkim_CLI_linux_1.0.59` before building.

## Tools excluded from this study

| Tool | Upstream version | Upstream synthetic recall | Reason for exclusion |
|---|---|---|---|
| Pysa | 0.9.23 | 2.5% | Requires project-level Pyre configuration and hand-specified taint models, unlike the six included tools which run on a file under default rules. Including it would make results depend on configuration choices absent for every other tool. Liu et al. report 2.5% recall on the synthetic dataset, 0% on real-world, empty results in 44.4% of cases and timeouts in 11.1% (§6.1.2). |
| Snyk | 1.1293.1 | 70.5% | Commercial product requiring an authenticated account, so results are not reproducible by readers and depend on licence tier. Liu et al. note that "with the exception of Snyk, all selected tools provide fully accessible and transparent rule sets" (§3.2) and that its training data cannot be audited (§7.3). |

## Reproduction of published figures

Running the six pinned tools over the DeepSeek-V3 synthetic dataset
that ships with PySASTBench reproduces every published figure exactly.

| Tool | Published P / R / F1 (Table 3) | Reproduced P / R / F1 |
|---|---|---|
| DevSkim | 100 / 8.3 / 15.4 | 100 / 8.33 / 15.38 |
| Dlint | 100 / 49.2 / 65.9 | 100 / 49.17 / 65.92 |
| Bandit | 70.6 / 40.0 / 51.1 | 70.59 / 40.00 / 51.06 |
| Bearer | 72.4 / 59.2 / 65.1 | 72.45 / 59.17 / 65.14 |
| CodeQL | 84.5 / 40.8 / 55.1 | 84.48 / 40.83 / 55.06 |
| Semgrep | 83.2 / 65.8 / 73.5 | 83.16 / 65.83 / 73.49 |

Reproduction required four corrections to the published artifact; see
`cwemapping-additions.md` and the repository README.

