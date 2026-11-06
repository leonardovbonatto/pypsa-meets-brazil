# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the T0 network: one bus per subsystem, snapshots from config, the tidy
demand series (PR-05) attached as time-varying loads, the aggregated
generator capacity (PR-08) attached as one Generator per (subsystem,
technology), a `marginal_cost` on every generator (PR-10) - CVU-derived for
thermal, an explicit documented default for everything else - inter-
subsystem transfer `Link`s per ADR-0006 (PR-13), a real hourly wind/solar
`p_max_pu` availability profile (PR-15), and a load-shedding slack generator
per bus (PR-11) as the last-resort backstop for whatever the transfer links
still can't cover.

Still no real transmission physics (Links are a transport model, not DC-OPF,
per ADR-0006): see docs/handoffs/PR-15-*.md for exactly what is and isn't
here yet, and why the marginal costs, the availability gaps and the
load-shedding usage are all a real simplification worth reading before
trusting a dispatch result.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

sys.path.insert(0, str(Path(__file__).resolve().parent))


def load_demand(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["snapshot"])


def wide_demand(demand: pd.DataFrame, *, subsystems: list[str]) -> pd.DataFrame:
    """One column per subsystem, one row per snapshot - what `n.add("Load", ...)` wants."""
    missing = set(subsystems) - set(demand["subsystem"])
    if missing:
        raise ValueError(f"demand series is missing configured subsystem(s): {sorted(missing)}")

    wide = demand.pivot(index="snapshot", columns="subsystem", values="load_mw").sort_index()
    wide = wide[subsystems]
    if wide.isna().any().any():
        raise ValueError("demand series has gaps after pivoting to wide form")
    return wide


def build_network(demand: pd.DataFrame, *, subsystems: list[str]) -> pypsa.Network:
    wide = wide_demand(demand, subsystems=subsystems)

    n = pypsa.Network()
    n.set_snapshots(wide.index)

    # Buses reference a carrier by name; PyPSA only resolves it against
    # n.carriers, which n.add("Bus", carrier=...) does not populate itself.
    # Skipping this passes consistency_check() (it only warns) but leaves the
    # carrier's own attributes (color, nice_name, ...) undefined.
    n.add("Carrier", "AC")
    for subsystem in subsystems:
        n.add("Bus", subsystem, carrier="AC")

    n.add("Load", subsystems, bus=subsystems, p_set=wide[subsystems])

    n.consistency_check()
    return n


def load_generators(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def attach_generators(n: pypsa.Network, generators: pd.DataFrame) -> pypsa.Network:
    """
    Add one Generator per (subsystem, technology) row: `p_nom` only.

    No `marginal_cost` (needs CVU for thermal, water value for hydro - both
    unbuilt) and no `p_max_pu` (needs atlite/ERA5 for renewables, also
    unbuilt) - both default to PyPSA's own defaults (0 and 1 respectively),
    which is a placeholder, not a modelling claim. Mutates `n` in place and
    returns it for convenience.
    """
    unknown_buses = set(generators["subsystem"]) - set(n.buses.index)
    if unknown_buses:
        raise ValueError(f"generator subsystem(s) have no matching bus: {sorted(unknown_buses)}")

    for carrier in generators["carrier"].unique():
        if carrier not in n.carriers.index:
            n.add("Carrier", carrier)

    names = (generators["subsystem"] + " " + generators["carrier"]).tolist()
    n.add(
        "Generator",
        names,
        bus=generators["subsystem"].to_numpy(),
        carrier=generators["carrier"].to_numpy(),
        p_nom=generators["p_nom_mw"].to_numpy(),
    )

    n.consistency_check()
    return n


def load_links(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


# PR-61: a tie-break, not a price. In a lossless transport model, N's surplus
# reaches SE_CO at the same cost directly or through NE, and the 2024 solve
# routed ~2 GW through NE (N-NE +2,029 MW mean against ONS's -1,467). A tiny
# cost per MWh per hop makes the direct path win. It sits below the coupled
# run's RESERVOIR_DISPATCH_COST (0.005) and SPILL_COST (0.01), so exporting
# water stays cheaper than spilling it.
LINK_TIE_BREAK_COST = 0.001


def attach_links(n: pypsa.Network, links: pd.DataFrame) -> pypsa.Network:
    """
    Add two one-way transfer Links per real ONS boundary (ADR-0006): `b0-b1`
    and `b1-b0`, each up to `p_nom`, matching the real data, which shows
    every boundary reversing direction over the year. One-way because each
    carries LINK_TIE_BREAK_COST (PR-61): on a single two-way Link a cost on
    negative flow would be a credit. No losses (`efficiency` 1.0), a stated
    T0 simplification. Reuses the "AC" carrier already registered for buses.
    Mutates `n` in place and returns it for convenience.
    """
    unknown_buses = (set(links["bus0"]) | set(links["bus1"])) - set(n.buses.index)
    if unknown_buses:
        raise ValueError(f"link bus(es) have no matching bus: {sorted(unknown_buses)}")

    for bus0, bus1 in (("bus0", "bus1"), ("bus1", "bus0")):
        n.add(
            "Link",
            [f"{a}-{b}" for a, b in zip(links[bus0], links[bus1], strict=True)],
            bus0=links[bus0].to_numpy(),
            bus1=links[bus1].to_numpy(),
            p_nom=links["p_nom_mw"].to_numpy(),
            p_min_pu=0.0,
            marginal_cost=LINK_TIE_BREAK_COST,
            carrier="AC",
        )

    n.consistency_check()
    return n


def load_availability(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["snapshot"])


def attach_availability(n: pypsa.Network, availability: pd.DataFrame) -> pypsa.Network:
    """
    Set `p_max_pu` on whichever (subsystem, technology) generators have real
    hourly capacity-factor data (PR-14/PR-15).

    Anything absent from `availability` keeps PyPSA's own default of 1.0 -
    currently only `SE_CO wind` (~0.3% of SE_CO's installed capacity, see
    docs/handoffs/PR-14-*.md), an explicit documented gap rather than a
    silent one. Mutates `n` in place and returns it for convenience.
    """
    named = availability.assign(name=availability["subsystem"] + " " + availability["carrier"])

    unknown = set(named["name"]) - set(n.generators.index)
    if unknown:
        raise ValueError(f"availability row(s) have no matching generator: {sorted(unknown)}")

    wide = named.pivot(index="snapshot", columns="name", values="p_max_pu").sort_index()
    wide = wide.reindex(n.snapshots)
    if wide.isna().any().any():
        raise ValueError("availability series has gaps after aligning to network snapshots")

    for name in wide.columns:
        n.generators_t.p_max_pu[name] = wide[name]

    return n


def attach_exports(n: pypsa.Network, exports: pd.DataFrame) -> pypsa.Network:
    """
    PR-64: net international exports as a Load `{s} exports` per border
    subsystem (negative in import hours). Mutates `n` in place.
    """
    wide = exports.assign(snapshot=pd.to_datetime(exports["snapshot"])).pivot(
        index="snapshot", columns="subsystem", values="p_set_mw"
    )
    wide = wide.reindex(pd.DatetimeIndex(n.snapshots))
    if wide.isna().any().any():
        raise ValueError("exports series has gaps after aligning to network snapshots")
    for s in wide.columns:
        n.add("Load", f"{s} exports", bus=s, p_set=wide[s].to_numpy())
    return n


MUST_RUN_SUFFIX = "_small"


def attach_must_run(n: pypsa.Network) -> pypsa.Network:
    """
    PR-60: small TIPO III plants are not centrally dispatched, so they run
    exactly as observed: p_min_pu = p_max_pu. Mutates `n` in place.
    """
    names = n.generators.index[n.generators["carrier"].str.endswith(MUST_RUN_SUFFIX)]
    for name in names:
        n.generators_t.p_min_pu[name] = n.generators_t.p_max_pu[name]
    return n


# Carriers whose availability is NOT already a backcast of observed output:
# their p_max_pu is scaled by the share of the fleet operating each month
# (PR-59). Hydro and MMGD availability is observed generation over p_nom,
# and nuclear availability (PR-62) is ONS's operational availability in MW
# over p_nom: both already reflect the plants that were running.
COMMISSIONED_CARRIERS = ("wind", "solar", "thermal")


def attach_commissioning(n: pypsa.Network, share: pd.DataFrame) -> pypsa.Network:
    """
    PR-59: multiply p_max_pu by each month's operating share of p_nom, for
    COMMISSIONED_CARRIERS, so capacity that entered operation mid-year is not
    available before it did. Mutates `n` in place and returns it.
    """
    work = share[share["carrier"].isin(COMMISSIONED_CARRIERS)]
    names = work["subsystem"] + " " + work["carrier"]
    unknown = set(names) - set(n.generators.index)
    if unknown:
        raise ValueError(f"commissioning row(s) have no matching generator: {sorted(unknown)}")
    snapshots = pd.DatetimeIndex(n.snapshots)
    keys = pd.MultiIndex.from_arrays([snapshots.year, snapshots.month])
    p_max_pu = n.get_switchable_as_dense("Generator", "p_max_pu")
    for name, rows in work.assign(name=names).groupby("name"):
        by_month = rows.set_index(["year", "month"])["share"]
        factor = by_month.reindex(keys)
        if factor.isna().any():
            raise ValueError(f"{name}: commissioning share missing for some snapshot months")
        n.generators_t.p_max_pu[name] = p_max_pu[name].to_numpy() * factor.to_numpy()
    return n


def load_costs(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


# Every carrier this T0 network can produce that CVU does not cover, all get
# the same explicit value rather than PyPSA's implicit 0.0 default. Each is
# a real simplification, stated here instead of silently:
#   - hydro: true marginal cost is the water value, an opportunity cost that
#     has to be *computed* (PRIMER Sec 4), not looked up - unbuilt until
#     SDDP.jl lands. Treated as free/must-run in the interim, per the PR-08
#     handoff's own suggestion, now made an explicit decision rather than an
#     accident of the default.
#   - wind, solar: true marginal cost is genuinely near-zero (no fuel), so
#     0.0 is a defensible value here, not just a placeholder.
#   - nuclear: has a real but small fuel cost; approximated as a must-run
#     baseload at 0.0, the standard simplification at this level of detail.
NON_THERMAL_MARGINAL_COST = 0.0


def attach_marginal_costs(n: pypsa.Network, costs: pd.DataFrame) -> pypsa.Network:
    """
    Set `marginal_cost` (R$/MWh) on every generator: the CVU-derived value
    from `costs` for thermal, `NON_THERMAL_MARGINAL_COST` for everything
    else. Mutates `n` in place and returns it for convenience.
    """
    names = (costs["subsystem"] + " " + costs["carrier"]).tolist()
    unknown = set(names) - set(n.generators.index)
    if unknown:
        raise ValueError(
            f"cost row(s) have no matching generator in the network: {sorted(unknown)}"
        )

    n.generators["marginal_cost"] = NON_THERMAL_MARGINAL_COST
    n.generators.loc[names, "marginal_cost"] = costs["marginal_cost"].to_numpy()

    return n


def attach_thermal_bands(
    n: pypsa.Network,
    bands: pd.DataFrame,
    availability: pd.DataFrame,
    floor: pd.DataFrame,
    residual_capacity: pd.DataFrame,
) -> pypsa.Network:
    """
    ADR-0021: one generator per CVU band of joined plants, carrier `thermal`,
    with hourly availability and a monthly floor capped at it; `{s} thermal`
    shrinks to the residual registry capacity. Call after
    attach_marginal_costs, which resets every cost. Mutates `n` in place.
    """
    snapshots = pd.DatetimeIndex(n.snapshots)
    wide = availability.assign(snapshot=pd.to_datetime(availability["snapshot"])).pivot(
        index="snapshot", columns="name", values="p_max_pu"
    )
    wide = wide.reindex(snapshots)
    gaps = float(wide.isna().to_numpy().mean())
    if gaps > 0.01:
        raise ValueError(f"band availability missing for {gaps:.1%} of hours")
    wide = wide.ffill().bfill()
    months = snapshots.month
    floor_wide = floor.pivot(index="month", columns="name", values="floor_mw")
    for _, band in bands.iterrows():
        name = band["name"]
        n.add(
            "Generator",
            name,
            bus=band["subsystem"],
            carrier="thermal",
            p_nom=float(band["p_nom_mw"]),
            marginal_cost=float(band["marginal_cost"]),
        )
        n.generators_t.p_max_pu[name] = wide[name].to_numpy()
        if name in floor_wide:
            share = (floor_wide[name].reindex(months).fillna(0.0) / band["p_nom_mw"]).to_numpy()
            n.generators_t.p_min_pu[name] = np.minimum(share, wide[name].to_numpy())
    for _, row in residual_capacity.iterrows():
        n.generators.loc[f"{row['subsystem']} thermal", "p_nom"] = float(row["p_nom_mw"])
    return n


def attach_thermal_floor(n: pypsa.Network, floor: pd.DataFrame) -> pypsa.Network:
    """
    ADR-0016: each subsystem's thermal must run at least its monthly floor -
    what ONS dispatched for reasons other than price in the reference year -
    as `p_min_pu` on `{s} thermal`, held for every hour of the month.
    Mutates `n` in place and returns it for convenience.
    """
    names = floor["subsystem"] + " thermal"
    unknown = set(names) - set(n.generators.index)
    if unknown:
        raise ValueError(f"floor row(s) have no matching generator: {sorted(unknown)}")
    months = pd.DatetimeIndex(n.snapshots).month
    for name, rows in floor.assign(name=names).groupby("name"):
        p_nom = float(n.generators.loc[name, "p_nom"])
        if p_nom <= 0.0:
            continue  # ADR-0021: a residual with no capacity carries no floor
        by_month = rows.set_index("month")["floor_mw"] / p_nom
        if set(months) - set(by_month.index):
            raise ValueError(f"{name}: floor missing for some snapshot months")
        # Never above what is available that hour (PR-59 scales p_max_pu).
        ceiling = n.get_switchable_as_dense("Generator", "p_max_pu")[name].to_numpy()
        n.generators_t.p_min_pu[name] = np.minimum(by_month.reindex(months).to_numpy(), ceiling)
    return n


# Every bus gets an always-available slack generator so the network is
# solvable at all despite having no transmission lines: with real 2024 data,
# S's own generator capacity falls short of S's own peak demand in 2 of
# 8784 hours (267 MWh/year total, see docs/handoffs/PR-11-*.md) - with no
# lines to import NE's 41 GW of spare capacity, that makes the network
# infeasible without a slack. LOAD_SHED_COST is not a researched value-of-
# lost-load estimate - it is picked only to sit clearly above every real
# generator's marginal_cost (max observed thermal CVU: 3681.59 R$/MWh, see
# the cvu_usina_termica data dictionary) so load shedding is always the
# dispatch of last resort, never competitive in merit order. LOAD_SHED_P_NOM
# is effectively unlimited so shedding itself is never the binding
# constraint - the real constraint is every other generator's own p_nom.
LOAD_SHED_CARRIER = "load_shedding"
LOAD_SHED_COST = 10_000.0
LOAD_SHED_P_NOM = 1_000_000.0


def attach_load_shedding(n: pypsa.Network, *, subsystems: list[str]) -> pypsa.Network:
    """
    Add one always-available load-shedding generator per bus.

    Its dispatch is the honest signal for "no transmission lines yet": any
    nonzero load-shedding after a solve means that bus's own generators
    could not cover that bus's own demand at that hour, which real
    transmission would resolve by importing from a neighbouring subsystem.
    Mutates `n` in place and returns it for convenience.
    """
    if LOAD_SHED_CARRIER not in n.carriers.index:
        n.add("Carrier", LOAD_SHED_CARRIER)

    names = [f"{subsystem} {LOAD_SHED_CARRIER}" for subsystem in subsystems]
    n.add(
        "Generator",
        names,
        bus=subsystems,
        carrier=LOAD_SHED_CARRIER,
        p_nom=LOAD_SHED_P_NOM,
        marginal_cost=LOAD_SHED_COST,
    )

    n.consistency_check()
    return n


def write_network(n: pypsa.Network, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(str(out_path))
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    demand = load_demand(Path(snake.input.demand))
    n = build_network(demand, subsystems=list(snake.params.subsystems))

    # ONS-dispatched units (capacidade_geracao) plus MMGD, which that
    # registry does not cover - see scripts/build_mmgd.py.
    generators = pd.concat(
        [
            load_generators(Path(snake.input.generators)),
            load_generators(Path(snake.input.mmgd_generators)),
            load_generators(Path(snake.input.small_generators)),
        ],
        ignore_index=True,
    )
    attach_generators(n, generators)

    links = load_links(Path(snake.input.links))
    attach_links(n, links)
    attach_exports(n, pd.read_csv(Path(snake.input.exports)))

    # Wind/solar (measured capacity factors) and hydro (observed generation,
    # a backcast - see ADR-0007) come from different datasets with different
    # filtering rules, so they are built separately and concatenated here.
    availability = pd.concat(
        [
            load_availability(Path(snake.input.availability)),
            load_availability(Path(snake.input.hydro_availability)),
            load_availability(Path(snake.input.mmgd_availability)),
            load_availability(Path(snake.input.small_availability)),
            load_availability(Path(snake.input.nuclear_availability)),
        ],
        ignore_index=True,
    )
    attach_availability(n, availability)
    attach_must_run(n)
    attach_commissioning(n, pd.read_csv(Path(snake.input.commissioning)))

    costs = load_costs(Path(snake.input.costs))
    attach_marginal_costs(n, costs)

    # ADR-0021: joined plants as CVU bands; the residual keeps the rest of the
    # registry capacity and the part of the floor the bands do not carry.
    attach_thermal_bands(
        n,
        pd.read_csv(Path(snake.input.thermal_bands)),
        pd.read_csv(Path(snake.input.thermal_band_availability)),
        pd.read_csv(Path(snake.input.thermal_band_floor)),
        pd.read_csv(Path(snake.input.thermal_residual_capacity)),
    )
    attach_thermal_floor(n, pd.read_csv(Path(snake.input.thermal_residual_floor)))

    attach_load_shedding(n, subsystems=list(snake.params.subsystems))

    write_network(n, Path(snake.output[0]))


if __name__ == "__main__":
    main()
