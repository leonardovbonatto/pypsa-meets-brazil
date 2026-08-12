<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# Contributing

## 1. Bootstrap (PR-00) — do this once

Snakemake is **not supported on native Windows**: shell directives, conda integration
and symlinks all break. Work happens inside WSL2/Ubuntu.

### 1.1 Install a real Linux userland

Docker Desktop installs a `docker-desktop` WSL distro, but that is not a usable
development environment. Install Ubuntu properly, from an **elevated PowerShell**:

```powershell
wsl --install -d Ubuntu-24.04
```

This prompts for a UNIX username and password, and may require a reboot. It cannot be
run unattended.

### 1.2 Clone to the Linux filesystem

Inside the Ubuntu shell:

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/leonardovbonatto/pypsa-meets-brazil.git
cd pypsa-meets-brazil
```

**Clone to `~/projects`, not `/mnt/c/`.** Windows bind-mount I/O is roughly an order
of magnitude slower, which becomes intolerable on ERA5 cutouts and BDGD geodatabases.

### 1.3 Identity, CLI and environment

```bash
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"

# GitHub CLI
sudo mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null
sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update && sudo apt install gh -y
gh auth login

# pixi — environment manager (PyPSA-Eur's current convention)
curl -fsSL https://pixi.sh/install.sh | bash
exec $SHELL

pixi install
pixi run pre-commit install
pixi run pre-commit install --hook-type commit-msg
```

Julia is only needed from Epic 7 (PR-35) onward. Defer it.

### 1.4 Verify

```bash
pixi run snakemake -n                                            # DAG resolves
pixi run pytest                                                  # fixtures pass
pixi run snakemake -j4 --configfile config/test/config.smoke.yaml  # end-to-end smoke
```

If the smoke run breaks, fix that before anything else. It is the canary for the
whole workflow.

## 2. Workflow

One issue per PR, one milestone per epic. Branch from `main`:

```bash
git switch -c feat/ons-connector
```

Prefixes: `feat/`, `data/`, `fix/`, `docs/`, `spike/`.

`main` is protected — pull request required, lint and tests green, squash-merge only,
linear history, no force-push.

## 3. Commits

[Conventional Commits](https://www.conventionalcommits.org/), enforced by a
commit-msg hook:

```
feat(ons): add CKAN connector for verified load series
fix(hydro): correct MWmed to MWh conversion in ENA builder
data(aneel): refresh SIGA snapshot to 2026-08
docs(adr): record impedance source decision
```

Types: `feat` `fix` `data` `docs` `chore` `refactor` `test`.

Because merges are squashed, each PR becomes exactly one commit on `main` — the
history is meant to read as a project narrative.

## 4. The session budget

Every PR must fit one working session. The limits are in
[ADR-0001](docs/decisions/ADR-0001-repository-conventions.md) and restated in the PR
template. The short version:

- ≤ 12 files, ≤ ~600 net new lines of Python, exactly one concern, ≤ 3 new deps.
- **Never read a raw data file into session context.** Run `scripts/_inspect.py` once
  and read `docs/data-dictionary/<source>/<dataset>.yaml` thereafter.
- `L` is not a shippable size. Split before starting.
- At ~60% context with implementation incomplete: commit WIP, write the handoff, open
  a follow-up issue, split. Do not push through.

## 5. What every PR carries

1. A `CHANGELOG.md` entry under `[Unreleased]` (or the `no-changelog` label).
2. Data dictionaries for any new source.
3. Committed provenance records under `resources/_provenance/`.
4. An ADR for any consequential judgement call.
5. A handoff note at `docs/handoffs/PR-NN-*.md`.
6. Evidence in the PR body — for modelling changes, what was compared against which
   observed ONS/ANEEL series, and the resulting error. "Tests pass" is not evidence.

## 6. Data hygiene

- **Never commit data.** `resources/`, `results/`, `logs/` and `cutouts/` are ignored.
  The sole exceptions are `resources/_provenance/` (tiny JSON) and
  `test/fixtures/` (small, real-shaped samples).
- **CI never downloads real data.** Fixtures only — no credentials, no flakiness, no
  multi-GB pulls.
- Credentials (`.cdsapirc`, solver licences) are gitignored. If one is ever committed,
  treat it as compromised and rotate it.

## 7. Licensing

REUSE-compliant. Every file carries an SPDX header:

```python
# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
```

MIT for code, CC-BY-4.0 for docs, ODbL-1.0 for OpenStreetMap-derived artifacts —
which stay inside their marked output path so the copyleft boundary is auditable.
Fetch the full licence texts once with `reuse download --all`.

## 8. Reviewing agent-authored work

Most PRs here are produced in agent-assisted sessions. Review them harder, not more
softly — see [`docs/PRIMER.md`](docs/PRIMER.md) §7 for the checklist and the specific
failure modes to look for. The most important habit: **ask for the validation number,
not the claim.** A model that "looks reasonable" and one that reproduces the observed
ONS series are different things, and only the second is a result.
