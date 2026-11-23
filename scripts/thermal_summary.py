########################################################################
#
# Copyright 2026 Volker Muehlhaus and IHP PDK Authors
#
# Licensed under the GNU General Public License, Version 3.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.gnu.org/licenses/gpl-3.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
########################################################################

"""Print a summary of Elmer thermal results for a given <model>_data directory, or for every Elmer
thermal model directory found below a given search path: minimum and maximum temperature, and the
heat flow through each constant-temperature boundary. Standalone CLI equivalent of setupThermal's
results summary, for workflows that run gds2palace without the GUI. Only the Python standard library.
"""

import os
import re
import sys
import argparse

__version__ = "1.0"

_RESULTS_DAT = "thermal_results.dat"
_HEATFLOW_DAT = "thermal_heatflow.dat"
_HEATFLOW_COLUMN_RE = re.compile(r'over bc heatflow_(\S+)')


def _last_row(path):
    """The numbers of the last non-empty line of an Elmer SaveScalars file, or None."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]
        return [float(v) for v in lines[-1].split()] if lines else None
    except (OSError, ValueError):
        return None


def read_case(run_path):
    """(constant temperatures {boundary name: T in K}, total input power in W) from the model's case.sif,
    or None if it is not an Elmer thermal model."""
    path = os.path.join(run_path, 'case.sif')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return None
    if 'Heat Equation' not in text:
        return None
    temps = {}
    for block in re.findall(r'^Boundary Condition \d+\n(.*?)^End', text, flags=re.M | re.S):
        name = re.search(r'Name\s*=\s*"([^"]+)"', block)
        temp = re.search(r'Temperature\s*=\s*Real\s+(\S+)', block)
        if name and temp:
            temps[name.group(1)] = float(temp.group(1))
    power = sum(float(p) for p in re.findall(r'Volumetric Heat Source\s*=\s*-distribute\s+(\S+)', text))
    return temps, power


def read_heatflow(run_path):
    """[(boundary name, heat out of the model in W)] from thermal_heatflow.dat, or None (no file yet, or a
    model from gds2palace before 0.13.0). Elmer's loads are negative for heat that leaves the model."""
    values = _last_row(os.path.join(run_path, _HEATFLOW_DAT))
    if values is None:
        return None
    try:
        with open(os.path.join(run_path, _HEATFLOW_DAT + '.names'), 'r', encoding='utf-8') as f:
            names = [m.group(1) for m in map(_HEATFLOW_COLUMN_RE.search, f) if m]
    except OSError:
        return None
    if len(names) != len(values):
        return None
    return [(name, -value) for name, value in zip(names, values)]


def build_summary(run_path):
    """Summary text for one model directory, and whether it has results."""
    case = read_case(run_path)
    temps, power = case if case else ({}, 0.0)
    lines = [f"Elmer thermal results: {os.path.abspath(run_path)}"]
    minmax = _last_row(os.path.join(run_path, _RESULTS_DAT))
    if not minmax or len(minmax) < 2:
        lines.append("  no results yet (thermal_results.dat not found)")
        return "\n".join(lines), False
    lines.append(f"  Min temperature : {minmax[0]:.2f} K")
    lines.append(f"  Max temperature : {minmax[1]:.2f} K")
    lines.append(f"  Input power     : {power:.4g} W")

    heatflow = read_heatflow(run_path)
    if heatflow is None:
        lines.append("  Heat flow per boundary: not in this result (model from gds2palace before 0.13.0)")
        return "\n".join(lines), True
    lines.append("")
    lines.append("  Heat flow through the constant-temperature boundaries (negative: heat flows into the model)")
    header = ["Boundary", "T (K)", "Heat out (W)", "Share"]
    rows = []
    for name, heat_out in heatflow:
        t = temps.get(name)
        share = f"{100 * heat_out / power:.1f} %" if power else "-"
        rows.append([name, f"{t:.2f}" if t is not None else "-", f"{heat_out:.4g}", share])
    total = sum(h for _, h in heatflow)
    rows.append(["Total", "", f"{total:.4g}", f"{100 * total / power:.1f} %" if power else "-"])
    widths = [max(len(r[i]) for r in [header] + rows) for i in range(4)]
    for r in [header] + rows:
        lines.append("  " + "  ".join(c.ljust(widths[0]) if i == 0 else c.rjust(widths[i]) for i, c in enumerate(r)))
    lines.append("  The total equals the input power on any mesh (energy balance of the FEM solution), so it")
    lines.append("  shows where the heat goes, not how accurate the mesh is.")
    return "\n".join(lines), True


def find_thermal_dirs(search_root):
    """Every directory at or below search_root whose case.sif is an Elmer thermal model."""
    found = []
    for root, dirs, files in os.walk(search_root):
        dirs[:] = sorted(d for d in dirs if d != 'mesh')
        if 'case.sif' in files and read_case(root) is not None:
            found.append(root)
    return found


def main():
    parser = argparse.ArgumentParser(
        description="Summary of Elmer thermal results (gds2palace): min/max temperature and the heat flow "
                    "through each constant-temperature boundary.")
    parser.add_argument("path", nargs="?", default=".",
                        help="a <model>_data directory, or a folder searched for them (default: current directory)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()
    print(f"thermal_summary.py {__version__}, path = {os.path.abspath(args.path)}")

    run_dirs = find_thermal_dirs(args.path)
    if not run_dirs:
        print("No Elmer thermal model found (a directory with a case.sif that solves the heat equation).")
        sys.exit(1)
    complete = True
    for run_path in run_dirs:
        text, has_results = build_summary(run_path)
        complete = complete and has_results
        print()
        print(text)
    sys.exit(0 if complete else 1)


if __name__ == "__main__":
    main()
