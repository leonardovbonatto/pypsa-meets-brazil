<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# SDDP diagnostics — the bucket chase

A standing checklist of **measurements to take before believing anything**
about the SDDP model. Run the relevant bucket before attributing a cause,
writing a handoff claim, or building on a previous PR's explanation.

**Why this file exists.** Three times in this epic a real, reproducible
measurement was shipped with a *wrong explanation attached*:

| PR | The measurement (sound) | The explanation (wrong) | What it actually was |
|---|---|---|---|
| 38 | AR(1) recursion computes and the state carries | "the policy is persistence-aware" | policy blind — every cut coefficient on `z` exactly 0 (PR-40); fixed by ADR-0009 in PR-45 |
| 39 | training crashes at iteration 2277 / 1569 | "the LP degrades as cuts accumulate" | objective *magnitude*; scaling removed the ceiling (PR-42) |
| 32/33/39/40 | CVaR scores worse on tail statistics | "backwards from theory" (convergence, then persistence) | nested risk measure — the comparison metric was wrong (PR-43) |

In all three, the check that settled it was cheap — a docstring, a cut
export, a known endpoint, a 20-line toy — and came *after* multiple
expensive speculative explanations.

## Ground rules

1. **Test the claim, not the mechanism.** "The recursion runs" is not
   "the policy uses it." Find the artifact that *must* change if the claim
   is true, and look at it. For anything about what an SDDP policy knows,
   **the cuts are the policy**.
2. **Check the metric is what the optimiser optimises.** Before calling a
   result "backwards from theory", confirm which theory applies to the
   quantity being reported.
3. **Build the cheapest control that would rule a cause out.** A toy with
   i.i.d. noise ruled out data, persistence and convergence in one run
   (PR-43). Prefer that to another full-model experiment.
4. **Never pipe a long experimental run through `grep`.** PR-39 lost an
   hour to a sweep whose failures were filtered away. Capture the full
   log, filter afterwards.

All commands below run from the repo root inside WSL, after
`export PATH=$HOME/.pixi/bin:$PATH`.

---

## Bucket 0 — Reproducibility (do this first, always)

Nothing else is interpretable if runs are not reproducible.

- [ ] **Same seed gives identical output.** Run the same policy twice and
      diff `summary.json`. They must be byte-identical (established
      PR-33).
- [ ] **The result reproduces outside Snakemake.** A standalone Julia
      invocation with the same args must match the rule's output to every
      digit (confirmed PR-42).
- [ ] **Inputs actually exist.** `resources/` and `results/` are gitignored
      working outputs — a fresh session will not have them. Rebuild before
      concluding anything is missing or broken.

```bash
pixi run -e dev snakemake -j1 prepare_sddp_inputs
pixi run -e dev snakemake -j1 sddp_first_policy sddp_cvar_policy
```

## Bucket 1 — Did training actually succeed?

- [ ] **Termination status.** `status : iteration_limit` is expected today.
      Anything else, especially a stack trace, means the run failed —
      check before reading any number from it.
- [ ] **Numeric issues count.** Should be ~0. Non-trivial counts mean the
      LP is ill-conditioned and every downstream figure is suspect.
- [ ] **`Termination status: OPTIMAL` with `Primal status:
      INFEASIBLE_POINT`** is the ill-conditioning signature. `OTHER_ERROR`
      is worse — the solver failing outright.
- [ ] **Bound trajectory: is it still climbing at the cap?** If yes the
      policy is *not converged*, whatever the iteration count.

```bash
grep -E "^status|numeric issues" logs/sddp_first_policy/run.log
grep -E "^ +[0-9]+ +[0-9]" logs/sddp_first_policy/run.log | tail -5
```

- [ ] **Crashing runs litter the repo root** with
      `model_infeasible_node_*.cuts.json`, `subproblem_*.mof.json` and
      `SDDP.log`. These are **not** gitignored (`reuse lint` catches them
      at commit). Run experimental Julia from a scratch cwd, or clean up.
- [ ] **A killed Snakemake leaves a directory lock.** The next run fails
      with `LockException`; clear it with `snakemake --unlock`. Note the
      failure is easy to miss — appending a cleanup command
      (`... ; rm -f ...`) after the run **masks the exit code as 0**, and
      stale results from the previous run look plausible. Never append
      cleanup to a command whose exit status matters.
- [ ] **Cut count should equal `iterations x (stages - 1) x K`.** The
      terminal stage carries no cost-to-go and therefore no cuts. A count
      matching `iterations x stages x K` would mean something unexpected is
      being written.

## Bucket 2 — Is the policy what you think it is? (read the cuts)

**This is the bucket that catches "the model accounts for X" claims.**

- [ ] **Every state variable has nonzero cut coefficients.** A state with
      all-zero coefficients is invisible to the value function — the
      policy cannot use it, no matter what the code appears to do.
- [ ] **Coefficient magnitudes are physically interpretable.** Storage
      coefficients currently saturate at **7.44**, and that number should
      reconcile exactly:
      `LOAD_SHED_COST × hours_in_longest_month ÷ MONEY_SCALE`
      `= 10,000 × 744 ÷ 1e6 = 7.44`.
      The marginal value of water tops out at the cost of the shedding it
      avoids — a genuine physical check, and a compact way to confirm the
      hours factor *and* the money scale are both applied. (Before PR-42
      this saturated at 10,000, because neither was.)
- [ ] **A state that only enters via `JuMP.fix_value` in `parameterize`
      is not in the LP** and will always have zero duals. If a quantity is
      supposed to inform the policy, it must appear in a `@constraint` or
      the objective. (This was PR-38's `z`, removed in PR-45.)
- [ ] **For the Markovian formulation (ADR-0009), the regime is a NODE, not
      a state column** — so Bucket 2's zero-coefficient check does not apply
      to it. The equivalent claim-level test is below.

```bash
python3 - <<'PY'
import pandas as pd, numpy as np
df = pd.read_parquet('results/sddp_first_policy/cuts.parquet')
names = df['state_variable'].iloc[0].split(',')
coefs = np.array([[float(x) for x in r.split(',')] for r in df['coefficient']])
for i, n in enumerate(names):
    col = coefs[:, i]
    print(f'{n:>16}  max|c|={np.abs(col).max():<12.6g} nonzero={int((np.abs(col)>1e-9).sum())}/{len(col)}')
print('intercepts:', df['intercept'].min(), '->', df['intercept'].max())
PY
```

- [ ] **Does water value differ across regimes?** At identical storage,
      water must be worth at least as much when a subsystem's OWN region is
      dry as when it is wet, with the other regions held at normal (ADR-0010;
      never "dry everywhere" vs "wet everywhere"). Compare the *slope* of the
      cost-to-go, not its level: a constant gap changes no dispatch, and
      lower inflows raise the level almost by construction. PR-45's first
      version compared levels and passed; the slope test failed on the same
      cuts.
- [ ] **One threaded run cannot settle a close pass or fail.** Two CVaR
      lambda=0.5 runs with identical cost (R$240.3bn) gave opposite verdicts:
      N's value at the reference point jumped from 0.18 to 7.44 (PR-46).
      Repeat the run, or train serially, before believing a verdict.

```bash
pixi run -e dev snakemake -j1 results/sddp_first_policy/regime_check.json
cat logs/check_sddp_regimes/sddp_first_policy.log
```

      Healthy: `passed: true`, and a `grid_counts` with few `wet_above_dry`.
      Water value sitting exactly on thermal cost x hours (N: 237.04 x 744
      / 1e6 = 0.17636) is a plateau; differences there can be month length
      rather than regime. With regional regimes the expectation policy
      passes (threaded, PR-46); serial confirmation pending.

## Bucket 3 — Are the units right?

- [ ] **Reconstruct the reported cost from simulated quantities.** Compute
      `sum_s(marginal_cost_s * thermal_gen_s) + LOAD_SHED_COST * load_shed`
      *without* any hours factor and compare to the reported cost:

      - **ratio ≈ 1.0** → the objective has **no hours factor** and is a
        rate (R$/h), not R$. This is the failure PR-39 found; the ratio
        came back `1.0000000000000018`.
      - **ratio ≈ 1/730** → healthy, hours factor present (current state).

      The cheap sanity version, no simulation needed: a run reporting
      ~38,000 MW-months of shedding at R$10,000/MWh must be on the order
      of `38,000 × 730 × 10,000 ≈ R$280 bn`. A "R$500 m annual cost"
      alongside that much shedding is arithmetically impossible.
- [ ] **`R$/MWh × MW = R$/h`**, not R$. PyPSA applies snapshot weightings
      automatically; **SDDP.jl does not**. A constant copied correctly
      from `build_network.py` can still be wrong in context.
- [ ] **Exported cuts are in the solver's working unit**, currently
      *millions* of R$ per MWmes (`MONEY_SCALE`). Multiply before adding
      them to a PyPSA objective in R$. `summary.json` carries
      `cuts_money_scale` and `cuts_units`.
- [ ] **At monthly granularity MWmed / MWmes / MW are commensurable** with
      no conversion — that is what Brazil's NEWAVE convention is for. This
      holds for the *water balance*; it does **not** license skipping the
      hours factor in the *objective*.

## Bucket 4 — Are the inputs real?

Run against the **full data volume**, never a fixture — several of these
are structurally invisible at fixture scale.

- [ ] **Zeros that are really "not tracked yet."** TELES PIRES reports
      `ena_bruta_mwmed == 0.0` for its first 213 days; in log space that is
      `-inf` and it silently poisons `mu`, then `phi`, then the simulated
      series (PR-37).
- [ ] **Negative or over-capacity storage** — real in ONS data, clipped in
      both directions, concentrated in the smallest-capacity REEs (PR-36).
- [ ] **Storable ENA exceeding gross ENA** — 346/41,649 rows; mostly
      floating-point noise but a real unexplained ~7% pattern for PARANA
      (PR-36).
- [ ] **Coverage windows differ per REE.** Three REEs only exist from
      2017-12-30. Do not assume uniform history (PR-36).
- [ ] **Check the data dictionary, not the raw file**, and build the
      dictionary from the full volume, not a sample (PR-14/15 lesson).

## Bucket 5 — Do the scenarios match the fit?

- [ ] **Re-estimate the process from the simulator's own output.** Fitted
      persistence and spatial correlation must be recoverable from
      simulated series (PR-29: all 66 REE pairs within 0.06; PR-37).
- [ ] **Recover known parameters from synthetic data** before trusting a
      fit on real data.
- [ ] **AR shock variance.** A log-space AR(1) needs `sqrt(1 - phi^2)`
      scaling or `z`'s stationary variance inflates to `1/(1-phi^2)` —
      omitting it roughly doubled every downstream statistic (PR-38).
- [ ] **Regime scenarios must keep PAR(1)'s persistence, not just its
      means.** Compare month-to-month log correlation and annual inflow
      spread against a PAR(1) simulation of the same parameters. At K=3, N
      gives 0.48 vs 0.88 and annual sd 20,794 vs 31,036 (PR-45), so droughts
      are milder than the fit.
- [ ] **Root-node assumption.** Every simulated year starts from a uniform
      draw across regimes, not a real observed prior December.

## Bucket 6 — Comparing two policies

- [ ] **Is the comparison metric the quantity being optimised?** SDDP.jl
      substitutes the risk measure for `E` *inside* the Bellman recursion,
      so a CVaR-trained policy minimises a **nested** composition of
      per-stage risk measures — **not** CVaR of the total annual cost.
      Judging it by P90 of an annual total is a category error (PR-43).
- [ ] **Verify a known endpoint.** `lambda = 0` must reproduce the
      expectation policy to every digit. If it does not, the translation
      or plumbing is broken, and nothing else in the comparison means
      anything.
- [ ] **Never compare `risk_adjusted_bound_rs` across risk measures.** A
      CVaR bound is a tail average and is structurally above an
      expectation bound. Use the plain Monte Carlo mean, which is computed
      identically for both.
- [ ] **Both policies must be trained identically** — same seed, same
      iterations, same simulation count. `SDDP_ITERATION_LIMIT` and
      `SDDP_N_SIMULATIONS` are shared constants in `rules/sddp.smk` for
      exactly this reason.
- [ ] **Structural check before expecting risk aversion to pay:** with
      `LOAD_SHED_COST` uniform across months and no discounting, hoarding
      water *relocates* shortfall rather than reducing it. There may be
      nothing for risk aversion to win on an annual-total metric.

---

## Current known-good baselines

Regional regimes (ADR-0010, 3 regions at K=3), seed 0, 4000 iterations, 12
threads, as of PR-46. Threaded runs vary about 0.5% in cost; serial baselines
replace these once recorded.

| | expectation | CVaR (λ=0.5, α=0.1) |
|---|---|---|
| PAR(1) paths, mean cost | R$ 233.7 bn | R$ 240.3 bn (two runs) |
| PAR(1) paths, mean load shed | 22,429 MW-months | 23,707 MW-months |
| PAR(1) paths, P90 load shed | 46,042 | 46,025 |
| cuts | 1,191,267 | 1,191,267 |
| numeric issues | 7 | 25 and 20 |
| peak memory | 6.6 GB | 6.2 GB |

National K=5, PR-45 (serial). Compare costs across designs only on the PAR(1)
rows.

| | expectation | CVaR (λ=0.5, α=0.1) |
|---|---|---|
| in-sample mean cost | R$ 225.2 bn | R$ 238.4 bn |
| PAR(1) paths, mean cost | R$ 238.9 bn | R$ 249.0 bn |
| PAR(1) paths, mean load shed | 22,966 MW-months | 24,782 MW-months |
| PAR(1) paths, P90 load shed | 46,530 | 46,851 |
| cuts | 220,000 | 220,000 |
| numeric issues | 1 | 34 |

The same at K=3 (seed 0, 4000 iterations, 1000 simulations), PR-45's first
full run. These reproduce the model, but they are
**not** a known-good policy: ADR-0009's acceptance test fails on them, and the
regime scenarios have milder droughts than PR-43's, so do not compare the two
tables as an improvement.

| | expectation | CVaR (λ=0.5, α=0.1) |
|---|---|---|
| simulated mean cost | R$ 213,402,633,724 | R$ 225,649,810,589 |
| risk-adjusted bound | R$ 206,588,973,290 | R$ 533,775,062,498 |
| mean load shed | 19,922 MW-months | 22,114 MW-months |
| P50 load shed | 15,932 | 18,091 |
| P90 load shed | 46,919 | 47,080 |
| cuts | 132,000 | 132,000 |
| numeric issues | 2 | 4 |
| training time | 934 s | 850 s |

PR-43's figures, before the Markovian graph (blind policy, PAR(1) scenarios):

| | expectation | CVaR (λ=0.5, α=0.1) |
|---|---|---|
| simulated mean cost | R$ 342,926,583,437 | R$ 378,921,913,280 |
| risk-adjusted bound | R$ 566,392,495,294 | R$ 711,199,047,937 |
| mean load shed | 38,452 MW-months | 43,066 MW-months |
| P50 load shed | 38,898 | 43,615 |
| P90 load shed | 56,818 | 61,417 |
| cuts | 44,000 | 44,000 |
| numeric issues | 0 | 2 |

λ sweep from PR-43 (1500 iterations, 2000 simulations — a *different* setting,
do not mix with the tables above):

| λ | mean shed | P90 shed | cost |
|---|---|---|---|
| 0.00 | 39,493 | 56,812 | R$ 347.4 bn |
| 0.25 | 38,472 | 55,967 | R$ 342.2 bn |
| 0.50 | 39,831 | 57,127 | R$ 358.5 bn |
| 0.75 | 40,644 | 57,776 | R$ 359.9 bn |
| 1.00 | 45,872 | 63,947 | R$ 395.2 bn |

Cut structure, from PR-43's 4000-iteration expectation run (44,000 cuts). In
PR-45 the `z` rows no longer exist and storage coefficients top out at 7.44
(NE, N), 7.33 (S) and 7.31 (SE_CO):

| state | max abs coefficient | nonzero |
|---|---|---|
| `storage[NE]` | 7.44 | 43,271 / 44,000 |
| `storage[N]` | 7.44 | 33,615 / 44,000 |
| `storage[SE_CO]` | 7.44 | 41,252 / 44,000 |
| `storage[S]` | 7.44 | 42,510 / 44,000 |
| `z[*]` (all four) | **0** | **0 / 44,000** |

Intercepts run 1,397.8 → 613,584.9, in **millions** of R$ (`MONEY_SCALE`).
The all-zero `z` row is the known persistence-blindness ADR-0009 addresses
— it is the reference example for Bucket 2.

## Known-answer tests worth keeping

- `lambda = 0` ≡ expectation policy, exactly.
- Uniform positive scaling of the objective (e.g. `MONEY_SCALE`) must not
  change the policy — only the numbers the solver handles.
- Simulated series must reproduce the fitted `phi` and correlation matrix.
- Synthetic data with a known `phi` must be recovered by the fitter.

## Open items this checklist does not yet cover

- Bucket 5's persistence check for regime scenarios is still a manual
  measurement, not an automated test.
- Whether PRIMER Sec 4.4's `(1-λ)E + λCVaR` intends a nested or
  end-of-horizon measure is unresolved, and matters for any eventual
  comparison against official ONS CMO figures.
