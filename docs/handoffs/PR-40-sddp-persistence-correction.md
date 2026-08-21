<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-40 — correction: the SDDP policy is blind to temporal persistence

**Landed:** documentation and comment corrections only — no behaviour
change. `julia/sddp_first_policy.jl` (module header, the `z` state's
comment, `KNOWN_LIMITATIONS`), `scripts/prepare_sddp_inputs.py` (module
docstring), `docs/handoffs/PR-38-*.md` (correction banner), `CHANGELOG.md`.

PR-38 shipped under the title "temporal persistence in the SDDP policy".
Half of that is true. This PR corrects the record before any further work
builds on the wrong half.

## What was actually measured

Inspecting the real exported cuts (`results/*/cuts.parquet`, 11,000 cuts
per policy), across **both** policies:

```
storage[NE] max|c|=10000   nonzero(>1e-9)=10875/11000
storage[N]  max|c|=10000   nonzero(>1e-9)= 8717/11000
z[NE]       max|c|=0       nonzero(>1e-9)=    0/11000
z[N]        max|c|=0       nonzero(>1e-9)=    0/11000   ← all four z, both policies
```

**All 22,000 cut coefficients on `z[*]` are exactly `0.0`.** Not small —
zero.

## Why (structural, visible in the code, not a solver quirk)

A Benders cut's coefficient on a state is the dual of that state's
incoming-value fixing constraint. `z` is declared `SDDP.State`, but:

- it appears in **no `@constraint`**,
- it appears in **no objective term**,
- the AR(1) recursion runs in **plain Julia** inside `parameterize`
  (`z_in = JuMP.fix_value(z[s].in)`), and both `z.out` and `inflow` are
  `fix()`-ed to already-computed constants.

So from the LP's perspective `z` is a disconnected variable. Its dual is
identically zero, the cost-to-go function is **flat** in it, and the policy
cannot express the one thing persistence is for: *"water is worth more this
month because last month was dry and next month probably will be too."*

The root cause is the **log-space** formulation. `inflow = exp(mu +
sigma*z)` is nonlinear, so it cannot be written as a linear constraint —
which is precisely why PR-38 moved the recursion outside the LP. The design
that made the code work is the same design that made the policy blind.

## What this means for previously reported results

Two PR-38 findings need reinterpreting, and both are now recorded that way:

1. **The ~2x cost/load-shed increase is not evidence that persistence is
   priced correctly.** The likelier reading: the simulated world got harder
   (scenarios now contain multi-month droughts, which they structurally
   could not before) while the policy did not improve at all. An unchanged
   policy facing harder scenarios costs more — exactly what was observed.
2. **The CVaR-above-expectation anomaly has an obvious candidate cause.** A
   risk measure cannot hedge against a state variable it cannot observe. It
   may still also be the under-convergence PR-39 measured; these are not
   mutually exclusive, and neither is confirmed.

PR-39's convergence-ceiling findings are unaffected — those were about LP
conditioning and are independent of whether `z` carries information.

## The process lesson, worth more than the bug

PR-38 *did* verify its work — a standalone Julia smoke test confirmed the
recursion computes correctly and that `z.in` carries the previous stage's
`z.out`. Both were true. Both were **the wrong property to test.**

The claim being made was "the policy is persistence-aware". The test
checked the *mechanism* (does the state carry?) rather than the *claim*
(does the value function depend on it?). One look at a cut coefficient
would have falsified it immediately — and cuts are the policy, so they are
the natural place to check any claim about what the policy knows.

Generalisable: **test the claim, not the mechanism.** When a PR asserts a
model now "accounts for" something, find the artifact that would have to
change if that were true, and look at it.

## Next PR needs

An **ADR** choosing how to make the policy genuinely persistence-aware.
This supersedes part of ADR-0005's inflow formulation, so it is an ADR, not
a code change. The two real candidates:

1. **Markovian policy graph** — discretise the hydrological state into
   Markov states; SDDP.jl builds a separate value function per state and
   handles the transition probabilities natively. Closest in spirit to what
   the official Brazilian chain does. Cost: discretisation error, and the
   model grows by a factor of the number of Markov states.
2. **Levels-space AR** — `inflow_t = mu_m + phi_m*(inflow_{t-1} -
   mu_{m-1}) + sigma_m*eps_t` is **linear**, so `inflow_{t-1}` can be a
   genuine state entering the storage balance and earning a nonzero dual.
   Closer to NEWAVE's own PAR(p). Cost: Gaussian innovations in levels can
   produce negative inflows, which log-space was chosen to prevent — needs
   an explicit, defensible truncation/clipping decision, and the PAR(1) fit
   (PR-28/29/37) would need refitting in levels.

Whichever wins, **the acceptance test is now obvious and should be
automated**: after training, assert that the inflow-state cut coefficients
are not all zero. That check would have caught this PR's bug on day one and
costs almost nothing.

Also still open, unchanged by this correction: the LP conditioning ceiling
(PR-39), the R$-per-hour unit error (PR-39, authorised but not yet done),
the REE-level policy (ADR-0008/PR-37), and the Phase 7 backtest gate.

## Open questions

- Does the persistence-blindness fully explain the CVaR anomaly, or only
  partly? Unresolvable until a persistence-aware policy exists to compare.
- Do PR-31/32/33's pre-PR-38 results need any reinterpretation? Probably
  not — those were honestly i.i.d. and described as such — but nobody has
  re-read them with this in mind.
