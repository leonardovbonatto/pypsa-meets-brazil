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
| 38 | AR(1) recursion computes and the state carries | "the policy is persistence-aware" | policy blind — every cut coefficient on `z` exactly 0 (PR-40) |
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
      the objective.

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

- [ ] **For any regime/Markov formulation (ADR-0009): does the value
      function differ across regimes?** At identical storage, water must
      be worth more in the dry state than the wet one. "The transition
      matrix is wired up" is *not* this check.

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
- [ ] **Root-node assumption.** Every simulated year currently starts from
      `z = 0` (unconditional mean), not a real observed prior December.

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

Regenerate and compare when something looks off. Seed 0, 4000 iterations,
1000 simulations, as of PR-43.

| | expectation | CVaR (λ=0.5, α=0.1) |
|---|---|---|
| simulated mean cost | R$ 342,926,583,437 | R$ 378,921,913,280 |
| risk-adjusted bound | R$ 566,392,495,294 | R$ 711,199,047,937 |
| mean load shed | 38,452 MW-months | 43,066 MW-months |
| P50 load shed | 38,898 | 43,615 |
| P90 load shed | 56,818 | 61,417 |
| cuts | 44,000 | 44,000 |
| numeric issues | 0 | 2 |

λ sweep (1500 iterations, 2000 simulations — a *different* setting, do not
mix with the table above):

| λ | mean shed | P90 shed | cost |
|---|---|---|---|
| 0.00 | 39,493 | 56,812 | R$ 347.4 bn |
| 0.25 | 38,472 | 55,967 | R$ 342.2 bn |
| 0.50 | 39,831 | 57,127 | R$ 358.5 bn |
| 0.75 | 40,644 | 57,776 | R$ 359.9 bn |
| 1.00 | 45,872 | 63,947 | R$ 395.2 bn |

Cut structure, from the 4000-iteration expectation run (44,000 cuts):

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

- No automated regression test asserts the cut-sensitivity check in
  Bucket 2. It would have caught PR-38 on day one and costs almost
  nothing — worth adding alongside ADR-0009's implementation, where it is
  already named as the acceptance test.
- Whether PRIMER Sec 4.4's `(1-λ)E + λCVaR` intends a nested or
  end-of-horizon measure is unresolved, and matters for any eventual
  comparison against official ONS CMO figures.
