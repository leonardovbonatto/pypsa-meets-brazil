<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-43 — the CVaR "anomaly" is a nested risk measure, not a bug

**Landed:** documentation and comment corrections only — no behaviour
change. `julia/sddp_first_policy.jl` (`KNOWN_LIMITATIONS`),
`rules/sddp.smk` (`sddp_cvar_policy` docstring),
`docs/decisions/ADR-0009-*.md` (correction note), `CHANGELOG.md`.

Since PR-32 this epic has carried an open finding: the CVaR-trained policy
scores *worse* on tail statistics than the expectation-trained one,
"backwards from theory". PR-33 partly attributed it to under-convergence,
PR-39 to the LP conditioning ceiling, PR-40/ADR-0009 to
persistence-blindness. **All of those attributions were wrong.** It is not
a defect at all.

## What was checked, in order

**1. The risk-measure translation is correct.** Re-derived from the
installed package's own docstring rather than trusting PR-32's earlier
check: `EAVaR(lambda, beta)` = `lambda * E + (1 - lambda) * AVaR(beta)`,
and `AVaR(beta)` averages the `beta` fraction of *worst* outcomes. Our
`EAVaR(lambda = 1 - lambda_PRIMER, beta = alpha)` is therefore right, and
`alpha = 0.1` really is the worst decile.

**2. Verified empirically at a known endpoint.** `lambda_PRIMER = 0`
should collapse to pure expectation. It reproduces the expectation-trained
policy *exactly* — mean 39,493, P50 39,780, P90 56,812, R$347.4bn, every
digit identical. Plumbing confirmed end to end.

**3. Swept lambda on the real model** (1500 iterations, 2000 simulations,
seed 0, everything else held identical):

| lambda | mean shed | P50 | P90 | cost |
|---|---|---|---|---|
| expectation | 39,493 | 39,780 | 56,812 | R$347.4 bn |
| 0.00 | 39,493 | 39,780 | 56,812 | R$347.4 bn |
| 0.25 | 38,472 | 38,598 | 55,967 | R$342.2 bn |
| 0.50 | 39,831 | 39,834 | 57,127 | R$358.5 bn |
| 0.75 | 40,644 | 41,442 | 57,776 | R$359.9 bn |
| 1.00 | 45,872 | 46,635 | **63,947** | R$395.2 bn |

Monotonic degradation in lambda (the small improvement at 0.25 is within
sampling noise and not claimed as an effect).

**4. Reproduced it in a control that removes every previously blamed
cause.** A 6-stage toy with **i.i.d. noise** (no persistence to be blind
to), hedging plainly available, a genuine tail under the expectation
policy, and the *verbatim* `parse_risk_measure` from production:

| lambda | mean | P90 | P99 |
|---|---|---|---|
| 0.0 | 9.06 | 46 | 92 |
| 0.5 | 9.06 | 46 | 92 |
| **1.0** | **47.39** | **70** | **136** |

Same pattern, on a problem with no Brazilian data, no persistence, no
convergence ceiling, and no conditioning trouble.

## The actual explanation

From SDDP.jl's own theory documentation, the risk-averse Bellman
recursion is:

```
V_i(x, ω) = min  C_i(x̄, u, ω) + 𝔽_{j, φ}[V_j(x′, φ)]
```

The risk measure **replaces the expectation operator inside the
recursion, at every stage**. Training with CVaR therefore does *not*
minimise CVaR of the total annual cost — it minimises a **nested**
composition of per-stage risk measures. Nesting compounds: applied at each
of 12 monthly stages, a per-stage `AVaR(0.1)` is far more conservative
than "the worst 10% of years", and no theorem says such a policy should
improve a **non-nested, end-of-horizon** statistic like P90 of annual
total load shed.

So the mistake was in the comparison, not the model: a nested-risk-optimal
policy was being judged by a metric it does not optimise.

**A second, structural reason specific to this model**, worth recording
because it limits what risk aversion could ever buy here: `LOAD_SHED_COST`
is uniform across months and there is no discounting, so total annual
shortfall is largely set by total annual inflow against total annual
demand. Hoarding water mostly **relocates** shedding between months rather
than reducing it — which is exactly what the toy shows when the
conservative lambda=1.0 policy sheds *early* and ends up worse overall.

## What this corrects

- **ADR-0009** used "CVaR will finally have something to hedge against" as
  a supporting argument. Withdrawn — a correction note is added there.
  **The ADR's decision stands unchanged**, because it rests on the
  independently measured fact that every cut coefficient on the anomaly
  state is exactly zero (PR-40). Persistence-blindness is a real defect on
  its own terms; it just has nothing to do with the CVaR comparison.
- **PR-32/33/39's** framing of this as convergence sensitivity is
  superseded. Their measurements were sound; the causal story was not.
  This is now the third time in this epic that a real measurement carried
  a wrong explanation (PR-38's persistence claim, PR-39's cut-accumulation
  claim, and this one) — a pattern worth naming.

## The lesson, which is the same one PR-40 found

PR-40's was "test the claim, not the mechanism". This one is its twin:
**check that the metric you are comparing on is the quantity the
optimiser actually optimises.** Four PRs asserted something was
"backwards from theory" without anyone re-reading which theory applied —
and the check that settled it (a docstring, a known endpoint, and a
20-line toy) cost far less than the three speculative explanations that
preceded it.

## Next PR needs

**Implement ADR-0009** — unchanged as the highest-value next item, on its
own merits: the policy is measurably blind to persistence, which makes the
epic's headline results misleading regardless of anything here.

If a genuine risk-aversion comparison is wanted later, the honest routes
are to report a **nested-consistent** metric, or to introduce discounting
so that deferring shortfall is actually worth something. Neither is
attempted here, and neither blocks ADR-0009.

## Open questions

- Is there a defensible nested-consistent statistic to report alongside
  the plain Monte Carlo mean, so the two policies can be compared on terms
  the CVaR one actually optimises? Not investigated.
- Does Brazil's real regulatory formulation (PRIMER Sec 4.4's
  `(1-λ)E + λCVaR`) intend a nested or an end-of-horizon measure? This
  matters for eventual comparison against official CMO figures, and was
  not resolved here — PRIMER states the blend without specifying which.
