# Building a Palace Apptainer Container

This is a step-by-step guide for building your own [Apptainer](https://apptainer.org/)
(formerly Singularity) container image of [Palace](https://github.com/awslabs/palace), the
AWS Center for Quantum Computing's finite element solver for computational
electromagnetics.

Palace's own CI builds container images too, but it does not publish anything you can just
`apptainer pull` — its build artifacts go to a private AWS registry. So getting your own
Apptainer image means building it yourself from source via [Spack](https://spack.io/),
which compiles Palace and every dependency (MFEM, libCEED, Hypre, PETSc, SLEPc, OpenBLAS,
OpenMPI, SuperLU_DIST, ...) from scratch. Budget **1–3+ hours** and a few GB of disk space.
This guide covers a CPU-only build using Palace's default solver variants (SuperLU_DIST +
SLEPc), the most common setup for sharing a working Palace environment with others.

The walkthrough below uses real, literal values (today's release, `0.17.0`) so you can copy
and paste each step as-is. Building a different release just means replacing `0.17.0` (and
its tag form, `v0.17.0`) wherever it appears — see the [Appendix](#appendix) for exactly
where, and for a shell-variable version of these same commands if you expect to repeat this
often.

## Faster alternative: a prebuilt container image

Building from source (below) compiles Palace `0.17.0` — a version already tagged upstream but
not yet an official Palace release, so this guide builds it via the git-tag workaround in
Step 3b. If you'd rather start from the last officially released version instead of building
anything yourself, a prebuilt Apptainer image for Palace **0.16** is published on GitHub
Container Registry:

```bash
apptainer pull palace_016.sif oras://ghcr.io/volkermuehlhaus/palace_016:latest
```

This replaces Steps 1–4 entirely — skip straight to [Step 5](#step-5-verify-the-image) to verify
it, substituting `palace_016.sif` for `~/palace_0.17.0.sif` in the commands there. Check
[github.com/users/VolkerMuehlhaus/packages/container/package/palace_016](https://github.com/users/VolkerMuehlhaus/packages/container/package/palace_016)
for whether a newer prebuilt image has been published since.

## Prerequisites

### Windows

Palace and Apptainer are Linux-only. On Windows, install the Windows Subsystem for Linux (WSL2)
first — open the Microsoft Store, install "Ubuntu 24.04 LTS", then open it (the `wsl` command,
or the Ubuntu app) and follow the rest of this guide unchanged from inside that Ubuntu shell.

### Linux (native or WSL2)

You need two tools on your `PATH`: **Spack** (to resolve and drive the build) and
**Apptainer** (to produce the final `.sif` image). Docker/Podman are *not* required for this
approach.

### Install Spack

```bash
git clone --depth 1 https://github.com/spack/spack.git ~/spack
source ~/spack/share/spack/setup-env.sh
spack --version
```

Add the `source` line to your `~/.bashrc` (or shell equivalent) so `spack` stays on your
`PATH` in future sessions. Any reasonably recent Spack works here — this clones the current
`develop` branch, and you don't need to check out a specific release just to run Spack.[^spackver]

### Install Apptainer

On Ubuntu/Debian, the [Apptainer PPA](https://apptainer.org/docs/admin/main/installation.html)
has the most current release:

```bash
sudo add-apt-repository -y ppa:apptainer/ppa
sudo apt update
sudo apt install -y apptainer
apptainer --version
```

For other distributions/macOS, see the
[official installation guide](https://apptainer.org/docs/admin/main/installation.html).
Apptainer 1.4+ can build unprivileged (no root) on most modern Linux kernels via user
namespaces; the steps below note the fallback if your system needs it.

## Step 1: Set up a build directory

This directory holds only the build *recipe* (a few small text files) — the multi-GB
dependency build happens in an ephemeral container, not on your local disk directly.

```bash
mkdir -p ~/palace-containers/apptainer
cd ~/palace-containers/apptainer
```

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
  container:
    format: singularity
    images:
      os: "ubuntu:24.04"
      spack: "1.2"
  specs:
    - palace@0.17.0
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
  container:
    format: singularity
    images:
      os: "ubuntu:24.04"
      spack: "1.2"
  specs:
    - palace@git.v0.17.0=0.17.0
EOF
```

This is identical to Step 3a's `spack.yaml` except for the last line. Continue to Step 4.

Both variants pin `spack: "1.2"` — the Spack release baked into the container's build
environment. This is unrelated to which Palace version you're building, so you generally
won't need to change it; see the [Appendix](#appendix) if you ever do.

## Step 4: Generate the container definition and build

```bash
spack -e . containerize > palace.def
apptainer build ~/palace_0.17.0.sif palace.def
```

`spack -e .` reads the `spack.yaml` from the current directory and emits a Singularity
definition file describing a two-stage build: a throwaway stage that concretizes and
compiles every package, and a slim final stage that copies over just the installed software.
`apptainer build` then executes that definition and produces `~/palace_0.17.0.sif`.

This step is the long one (the dependency compilation happens here). If it fails with a
permission/privilege error instead of a build error, retry with:

```bash
apptainer build --fakeroot ~/palace_0.17.0.sif palace.def
```

and only as a last resort:

```bash
sudo apptainer build ~/palace_0.17.0.sif palace.def
```

## Step 5: Verify the image

**Check the version:**

```bash
apptainer exec ~/palace_0.17.0.sif palace --version
```

This should print a `Palace version:` line and a schema version. If you used Step 3b's
git-tag workaround, the printed version is a commit hash (matching the `v0.17.0` tag) rather
than the plain version string — that's expected.

**Run a bundled example end-to-end** — e.g. the `rings` magnetostatic example — to confirm the
solve actually works, not just that the binary starts. Fetch its two input files first, since
they aren't inside the container image itself:[^schema]

```bash
mkdir -p /tmp/palace-smoketest/mesh && cd /tmp/palace-smoketest
curl -fsSL -o rings.json \
  "https://raw.githubusercontent.com/awslabs/palace/v0.17.0/examples/rings/rings.json"
curl -fsSL -o mesh/rings.msh \
  "https://raw.githubusercontent.com/awslabs/palace/v0.17.0/examples/rings/mesh/rings.msh"
```

Then run it:

```bash
apptainer exec ~/palace_0.17.0.sif palace rings.json
```

A successful run prints an "Elapsed Time Report" and writes result files under `postpro/`
(e.g. `postpro/terminal-M.csv` for the extracted inductance matrix).

**For multi-process (MPI) runs**, call the underlying binary directly rather than the
`palace` wrapper script — `palace` already invokes its own internal `mpirun -n 1`, so
wrapping it in an outer `mpirun` double-nests MPI and aborts:

```bash
apptainer exec ~/palace_0.17.0.sif mpirun -n 2 palace-x86_64.bin rings.json
```

## Using this build with the gds2palace workflow

The [gds2palace](https://github.com/VolkerMuehlhaus/gds2palace_ihp_sg13g2) workflow for IHP
SG13G2 generates the `.msh`/`config.json` model files that this container simulates — it
doesn't care how Palace was installed. Point the repo's `scripts/run_palace` wrapper at this
image, e.g.:

```bash
#!/bin/bash
apptainer exec ~/palace_0.17.0.sif palace -np 8 $1
```

See [`scripts/README.md`](https://github.com/VolkerMuehlhaus/gds2palace_ihp_sg13g2/blob/main/scripts/README.md)
for the rest of the launch/postprocessing scripts (`combine_snp` for Touchstone conversion,
`palace_summary.py` for a results summary).

## Appendix

### What to adjust for a future release

| Value | Current example | Appears in | When to change it |
|---|---|---|---|
| Palace version | `0.17.0` (tag form: `v0.17.0`) | Steps 2, 3a/3b, 4, 5 | Every new Palace release you want to build. |
| Step 3a vs. 3b | 3b (git-tag workaround) | Step 3 | Determined by the `spack versions palace` check in Step 2 — use 3a once your target version is listed directly. |
| Base OS image | `ubuntu:24.04` | Step 3a/3b | Rarely — only if you need a different base OS. |
| Output image path | `~/palace_0.17.0.sif` | Steps 4, 5 | Anytime — any path/filename works. |
| Build directory | `~/palace-containers/apptainer` | Step 1 | Anytime — any location works; reusing the same one is fine across versions. |
| `spack: "1.2"` (inside `spack.yaml`) | `1.2` | Step 3a/3b | Rarely — only if you deliberately want a newer Spack release baked into the image; unrelated to the Palace version, so leave it alone by default. |

Everything else in this guide (the `spack.yaml` structure, the `containerize`/`build`
commands, the verification steps) should stay the same across Palace releases.

### Alternative: using shell variables for repeat builds

Everything above uses literal values so each command can be copied and run as-is. If you
expect to build several Palace releases over time, it's more convenient to define the
version once as a shell variable and let the rest of the commands reference it — that way,
upgrading to a new release means changing one line instead of hunting through every command.
The steps and their explanations are identical to the ones above; only the literal values are
replaced by variable references (`$OUTPUT_SIF` etc.).

Define these once per session, after Step 1:

```bash
PALACE_VERSION=0.17.0      # <-- the Palace release to build, e.g. from
                            #     https://github.com/awslabs/palace/tags (no leading "v")
OS_IMAGE="ubuntu:24.04"     # <-- base OS image for the container
OUTPUT_SIF=~/palace_${PALACE_VERSION}.sif   # <-- where the finished image ends up
```

**Step 2** is unchanged — run `spack versions palace` and check whether `$PALACE_VERSION`
appears in the output.

**Step 3a** (version already known to Spack):

```bash
cat > spack.yaml <<EOF
spack:
  concretizer:
    unify: true
  container:
    format: singularity
    images:
      os: "${OS_IMAGE}"
      spack: "1.2"
  specs:
    - palace@${PALACE_VERSION}
EOF
```

**Step 3b** (version not yet known to Spack — the git-tag workaround):

```bash
cat > spack.yaml <<EOF
spack:
  concretizer:
    unify: true
  container:
    format: singularity
    images:
      os: "${OS_IMAGE}"
      spack: "1.2"
  specs:
    - palace@git.v${PALACE_VERSION}=${PALACE_VERSION}
EOF
```

**Step 4** (build):

```bash
spack -e . containerize > palace.def
apptainer build "$OUTPUT_SIF" palace.def
```

**Step 5** (verify):

```bash
apptainer exec "$OUTPUT_SIF" palace --version

mkdir -p /tmp/palace-smoketest/mesh && cd /tmp/palace-smoketest
curl -fsSL -o rings.json \
  "https://raw.githubusercontent.com/awslabs/palace/v${PALACE_VERSION}/examples/rings/rings.json"
curl -fsSL -o mesh/rings.msh \
  "https://raw.githubusercontent.com/awslabs/palace/v${PALACE_VERSION}/examples/rings/mesh/rings.msh"

apptainer exec "$OUTPUT_SIF" palace rings.json
apptainer exec "$OUTPUT_SIF" mpirun -n 2 palace-x86_64.bin rings.json
```

[^spackver]: This is the Spack you drive the build with. The container's own `spack.yaml` separately pins which Spack release gets baked inside the image (the `spack: "1.2"` line in Step 3) — that's unrelated and you generally won't need to touch it.
[^schema]: Use the example from the matching release tag (`v0.17.0` above), not from a newer checkout like `main` — Palace's config schema evolves between releases, and a newer example may use options your build doesn't recognize. If you already have a matching Palace source checkout on hand (e.g. the one you built the container from), you can copy the files from there instead of downloading them: `git -C /path/to/palace/checkout show v0.17.0:examples/rings/rings.json > rings.json` and `cp -r /path/to/palace/checkout/examples/rings/mesh .`
