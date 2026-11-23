<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-78 — Corridors of the clustered T1

PR-77's clustered T1 failed NE-SE_CO on 2024 because single cross-border
branches with near-zero reactance and small ratings bound and blocked the
Northeast. This PR fixes the cause and the way corridors are reduced.
Every variant below was chosen after seeing 2024 results, so all of it is
**post hoc on 2024**. The rule (from the hydro work) was: keep a change
only if the results get better, otherwise note it. Local only (EPE-derived).

## What the binding lines were

MA-TO, PE-PI and one BA-TO branch were each one 69/138 kV branch with
x = 0.001 % (EPE's busbar ties, "jumpers") crossing a state border; MT-RO
was three series-capacitor segments (x < 0). None is a corridor: each sits
inside one substation.

## Variants, in order

- **(a) Substation rule extended.** Buses joined by a transformer, a jumper
  (|x| < 0.001 pu on 100 MVA) or a series capacitor (x < 0) stay in one
  node. Fixes generation (thermal 1.41 -> 1.14 of ONS), but all four
  boundaries fail: NE's export now goes NE -> N -> SE_CO.
- **(b) = (a) + drop low-voltage ties.** A branch below 230 kV between two
  nodes is dropped where a >= 230 kV corridor joins the same two nodes (so
  no node is cut off). 103 branches. Better on all four boundaries.
- **(c) = (b) + fitted reactances.** Parallel combination treats each node
  as a copper plate and loses the impedance inside it, which is what sets
  how parallel corridors share a transfer. For each node, a unit transfer
  to a reference node is solved on T3's main AC island (injection spread
  by load and capacity); a corridor's susceptance is the least-squares fit
  of its T3 flow against the difference of the two nodes' weighted-mean
  angles. All 60 lines fitted.
- **(d) = (c) + one-way HVDC** (plant to load centre, T0's tie-break cost).
  In (c) one Belo Monte pole ran backwards (RJ -> Xingu -> MG) to loop
  power around AC limits, free of cost. Mixed result, so **not adopted**:
  `HVDC_ONE_WAY = False` in `build_network_t3.py`.

Also fixed: the substation rule broke voltage ties in set order, which
Python varies between runs (buses moved: 167, then 165). Ties now go to the
node most of the top-voltage buses are in, then by name.

## 2024 (post hoc), error as share of boundary capacity

| | PR-77 | (a) | (b) | **(c) adopted** | (d) |
|---|---|---|---|---|---|
| N-NE | 4.3% ✓ | 16.8% | 8.4% | **4.3% ✓** | 4.2% ✓ |
| N-SE_CO | 1.9% ✓ | 21.8% | 18.0% | **14.9%** | 7.5% |
| NE-SE_CO | 22.2% | 20.3% | 13.4% | **4.1% ✓** | 5.5% |
| SE_CO-S | 4.1% ✓ | 15.8% | 0.3% ✓ | **0.7% ✓** | 1.5% ✓ |
| wind / ONS | 0.928 | 1.001 | 1.011 | **1.058** | 1.067 |
| solar / ONS | 0.855 | 0.991 | 1.008 | **1.057** | 1.077 |
| nuclear / ONS | 0.997 | 0.984 | 0.989 | **0.998** | 0.998 |
| thermal / ONS | 1.414 | 1.144 | 1.123 | **1.032** | 1.080 |

(b) above is the run with deterministic ties; the random-tie run gave
N-NE 10.2%, N-SE_CO 17.7%, NE-SE_CO 13.2%, SE_CO-S 15.1%: SE_CO-S moves
with which node two substations land in.

Against T0 (pre-registered 1% criterion) no variant passes; T0 itself is
not ONS.

## Open

- N-SE_CO: Belo Monte's HVDC carries 5.6 GW mean in (c); the AC lines carry
  0.9 GW back. The loop through the two poles is unphysical; (d) removes it
  but costs NE-SE_CO. Next: look at what ONS does with Belo Monte's poles
  in the dry season, rather than at more variants on 2024.
- All of this is tuned on 2024. The honest test is a held-out year with
  T3 rebuilt (2022 untouched).
