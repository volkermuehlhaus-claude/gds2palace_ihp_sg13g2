# Building Palace Natively with Spack

This is a step-by-step guide for installing [Palace](https://github.com/awslabs/palace), the
AWS Center for Quantum Computing's finite element solver for computational electromagnetics,
directly on your machine using [Spack](https://spack.io/), so it's available as a normal
`palace` command on your `PATH`.

This compiles Palace and its dependencies from source via Spack — budget real time for a
from-scratch build, though if you've built Palace with Spack on this machine before, cached
dependencies make it much faster.[^cached]

Spack installs everything under a long, hash-named path you'd never want to type or put in a
script, for example:

```
/home/volker/spack/opt/spack/linux-zen4/palace-0.16.0-yzannz2n3633nninwhv6kuug6pjqybpk/bin/palace
```

This guide's Step 3 sets up a **Spack view** — a directory of symlinks Spack maintains at a
short, fixed, readable path (e.g. `~/palace-current/bin/palace`) that always points at the
current install. Once it's set up, add that `bin/` directory to `PATH` and just run
`palace ...`, without ever seeing the underlying path.

Every command below uses literal values (today's release, `0.17.0`) so you can copy and
paste each step as-is; see the [Appendix](#appendix) for what changes for a future release.

## Prerequisites

You need **Spack** on your `PATH`.

```bash
git clone --depth 1 https://github.com/spack/spack.git ~/spack
source ~/spack/share/spack/setup-env.sh
spack --version
```

Add the `source` line to your `~/.bashrc` (or shell equivalent) so `spack` stays on your
`PATH` in future sessions.

## Step 1: Set up a Spack environment directory

```bash
mkdir -p ~/palace-native
cd ~/palace-native
```

A Spack *environment* is a directory with a `spack.yaml` describing what to install — it gives
you a reusable, version-controlled recipe and, via Step 3, the readable-link view.[^environment]

## Step 2: Check Spack's package database for your target version

```bash
spack versions palace
```

Look for `0.17.0` in the output. This list only updates when someone submits a new
`version()` entry to Spack's package repository, which can lag a few weeks behind a new
Palace tag.

- If `0.17.0` **is** listed, use **Step 3a** below.
- If it's **not** listed, use **Step 3b** instead.

## Step 3a: Write `spack.yaml` (version already known to Spack)

```bash
cat > spack.yaml <<'EOF'
spack:
  concretizer:
    unify: true
  specs:
    - palace@0.17.0
  view: ~/palace-current
EOF
```

Continue to Step 4.

## Step 3b: Write `spack.yaml` (version not yet known to Spack)

Pin the git tag directly instead of the plain version — this works because Palace's Spack
package already points at its GitHub repo, so Spack can fetch and build a tag it doesn't have
a formal `version()` entry for yet:

```bash
cat > spack.yaml <<'EOF'
spack:
  concretizer:
    unify: true
  specs:
    - palace@git.v0.17.0=0.17.0
  view: ~/palace-current
EOF
```

This is identical to Step 3a's `spack.yaml` except for the version line. Continue to Step 4.

The `view: ~/palace-current` line is the piece that creates the readable link: Spack will
maintain a merged directory of symlinks there (`bin/`, `lib/`, `share/`, ...) that always
resolve to the real, hash-named install — refreshed automatically every time you install or
update inside this environment.

## Step 4: Concretize and install

```bash
spack -e . concretize
spack -e . install
```

`concretize` resolves and prints the full dependency graph — packages marked `[+]` are already
installed elsewhere on your system and will be reused, not rebuilt. `install` then builds
whatever's missing and updates the `~/palace-current` view.

This can take anywhere from well under a minute to **1–3+ hours** on a machine with nothing
cached, since Palace's dependency chain includes MFEM, libCEED, Hypre, PETSc, SLEPc, OpenBLAS,
OpenMPI, SuperLU_DIST, and more, all built from source.

## Step 5: Verify the install

**Check the version:**

```bash
~/palace-current/bin/palace --version
```

This should print a `Palace version:` line and a schema version. If you used Step 3b's
git-tag workaround, the printed version is a commit hash (matching the `v0.17.0` tag) rather
than the plain version string — that's expected.

**Put it on your `PATH`** so you can just type `palace` instead of the full view path:

```bash
echo 'export PATH="$HOME/palace-current/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
palace --version
```

**Run a bundled example end-to-end** — e.g. the `rings` magnetostatic example — to confirm the
solve actually works, not just that the binary starts. Fetch its two input files first, since
Spack doesn't install them for you:[^schema]

```bash
mkdir -p /tmp/palace-smoketest/mesh && cd /tmp/palace-smoketest
wget -q -O rings.json \
  "https://raw.githubusercontent.com/awslabs/palace/v0.17.0/examples/rings/rings.json"
wget -q -O mesh/rings.msh \
  "https://raw.githubusercontent.com/awslabs/palace/v0.17.0/examples/rings/mesh/rings.msh"
```

Then run it:

```bash
palace rings.json
```

A successful run prints an "Elapsed Time Report" and writes result files under `postpro/`
(e.g. `postpro/terminal-M.csv` for the extracted inductance matrix).

**For multi-process (MPI) runs**, use the `palace` wrapper script's own `--np` flag rather
than wrapping it in your own `mpirun` — the wrapper already calls `mpirun` internally, so an
outer `mpirun` double-nests MPI and aborts:

```bash
palace --np 2 rings.json
```

## Troubleshooting

**"Error: Could not locate MPI launcher, try specifying a value for --launcher"** — Palace needs
an MPI implementation on `PATH` at runtime. Spack's `palace` package normally pulls in its own
MPI provider (OpenMPI) as a dependency, so this is uncommon with the Step 1–5 workflow above;
it's more likely if you built or moved Palace outside of a Spack view. If you hit it, install
OpenMPI system-wide:

```bash
sudo apt install openmpi-bin libopenmpi-dev
```

## Using this build with the gds2palace workflow

The [gds2palace](https://github.com/VolkerMuehlhaus/gds2palace_ihp_sg13g2) workflow for IHP
SG13G2 generates the `.msh`/`config.json` model files that this Palace build simulates — it
doesn't care how Palace was installed. Point the repo's `scripts/run_palace` wrapper at this
build[^wrapper] and see
[`scripts/README.md`](https://github.com/VolkerMuehlhaus/gds2palace_ihp_sg13g2/blob/main/scripts/README.md)
for the rest of the launch/postprocessing scripts (`combine_snp` for Touchstone conversion,
`palace_summary.py` for a results summary).

## Appendix

### What to adjust for a future release

| Value | Current example | Appears in | When to change it |
|---|---|---|---|
| Palace version | `0.17.0` (tag form: `v0.17.0`) | Steps 2, 3a/3b, 5 | Every new Palace release you want to build. |
| Step 3a vs. 3b | 3b (git-tag workaround) | Step 3 | Determined by the `spack versions palace` check in Step 2 — use 3a once your target version is listed directly. |
| View path | `~/palace-current` | Step 3a/3b, all of Step 5 | Anytime — any path works. Keeping the same name across versions (as here) means upgrading in place just means re-running Step 4 with a new version in `spack.yaml`; use a version-specific name instead (e.g. `~/palace-0.17.0`) if you want several versions installed side by side. |
| Environment directory | `~/palace-native` | Step 1 | Anytime — any location works; reusing the same one is fine across versions. |

Everything else in this guide (the `spack.yaml` structure, the `concretize`/`install`
commands, the verification steps) should stay the same across Palace releases.

### If you already installed Palace without a view

Steps 1–5 use a Spack *environment* with a `view:` key, which is what creates the
`~/palace-current` shortcut for you automatically. If Palace was instead already installed a
different way — for example with a plain `spack install palace@0.17.0` and no environment —
you can still get convenient access to it, using either of the two options below.

#### Option 1: Create your own permanent shortcut

This gives you a shortcut similar to the view used above, but — unlike that view — it won't
update itself. If you reinstall or upgrade Palace later, you'll need to redo these steps.

1. Find where Spack actually put Palace:

   ```bash
   PALACE_PREFIX=$(spack location -i palace@0.17.0)
   ```

   (If it was installed using the git-tag workaround from Step 3b, use this instead:
   `PALACE_PREFIX=$(spack location -i palace@git.v0.17.0=0.17.0)`)

2. Make sure you have a personal folder for shortcuts like this, and that it's on your
   `PATH`. Many systems already set this up for `~/bin`; if `palace --version` at the end of
   this section doesn't work, run:

   ```bash
   mkdir -p ~/bin
   echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
   source ~/.bashrc
   ```

3. Create the shortcut. Palace ships as two files that need to stay together — the `palace`
   command itself, and the real program it runs behind the scenes — so link both into your
   shortcuts folder:

   ```bash
   ln -sf "$PALACE_PREFIX/bin/palace" ~/bin/palace
   ln -sf "$PALACE_PREFIX/bin/palace-x86_64.bin" ~/bin/palace-x86_64.bin
   ```

4. Confirm it works:

   ```bash
   palace --version
   ```

#### Option 2: Use Palace for just this terminal session

If you don't need a permanent shortcut — just a one-off session where `palace` works as a
command — Spack can add it to your `PATH` temporarily:

```bash
spack load palace@0.17.0
```

Two things to know about this option:

- It only lasts for your *current* terminal session. Close the terminal, or open a new one,
  and you'll need to run it again.
- It only works if you've *sourced* Spack's shell setup script in that terminal — the
  `source .../setup-env.sh` line from the Prerequisites step. Simply having `spack` available
  as a command is not enough; if you see an error mentioning "shell support", that's what's
  missing.

[^cached]: Dependencies already cached from a previous Spack build on this machine are reused, not recompiled — that's why this can also finish in well under a minute.
[^environment]: A bare `spack install palace` works too, but doesn't give you a reusable recipe file or the view set up in Step 3.
[^schema]: Use the example from the matching release tag (`v0.17.0` below), not from a newer checkout like `main` — Palace's config schema evolves between releases, and a newer example may use options your build doesn't recognize.
[^wrapper]: e.g. `~/palace-current/bin/palace -np 8 $1`, or simply `palace -np 8 $1` once it's on your `PATH` per Step 5.
