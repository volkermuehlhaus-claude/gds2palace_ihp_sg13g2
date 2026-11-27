"""Files that are copied by hand between the sibling repositories must not drift apart.

Several files exist in more than one repository on purpose (each package installs on its own): the stackup
reader, the Stackup Editor, the run scripts, the bundled stackups, the PDF build. Nothing syncs them, so a fix in one
copy is easily missing in the other. This test compares each pair.

- IDENTICAL: the two files must have the same text (line endings don't count).
- SHARED_FUNCTIONS: two files that share most of their functions, but each has parts of its own (the GDS reader:
  polygon repair for gmsh in gds2palace, the via flag in gds2openEMS). The functions and methods that both have
  are compared as code, without comments and docstrings; which ones differ, and how, is recorded like below.
- DIFFERENT_ON_PURPOSE: the two files differ where one names its own package or solver. Their differences are
  recorded in tests/sibling_copies/<name>.diff. The test fails when the differences are no longer the recorded
  ones: a change that went into one copy only shows up as a new block. A change made in both copies changes
  nothing.

After an intended change of the differences:
    UPDATE_SIBLING_COPIES=1 python -m pytest tests/test_sibling_copies.py
and look at the changed .diff files before committing them.

The sibling repositories are expected next to this one (as in the developer's workspace); a pair with a missing
repository is skipped, so the test does nothing in a checkout of gds2palace alone.

    python -m pytest tests/test_sibling_copies.py
"""
import ast
import difflib
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.normpath(os.path.join(HERE, "..", ".."))
RECORDED = os.path.join(HERE, "sibling_copies")
G2P, SETUPEM, OPENEMS, KLAYOUT = "gds2palace_ihp_sg13g2", "setupEM", "openems_ihp_sg13g2", "klayout_em_export"

IDENTICAL = [
    # the scripts that run Palace and convert its results
    *[(f"{G2P}/scripts/{name}", f"{SETUPEM}/src/scripts/{name}")
      for name in ("combine_extend_snp.py", "combine_snp", "run_palace", "run_palace_remote")],
    # the IHP stackups that setupEM bundles
    *[(f"{G2P}/XML_stackup/latest/IHP/{name}", f"{SETUPEM}/src/setupEM/data/{name}")
      for name in ("SG13G2_FEM_200um.xml", "SG13G2_FEM_200um_passi3D.xml", "SG13CMOS5L_200um.xml")],
    # the PDF build of the user's guides
    *[(f"{G2P}/doc/pdf_build/{name}", f"{OPENEMS}/doc/pdf_build/{name}")
      for name in ("build_userguide_pdf.py", "userguide_template.typ", "README.md", "requirements.txt")],
    *[(f"{G2P}/doc/pdf_build/{name}", f"{KLAYOUT}/doc/pdf_build/{name}") for name in ("README.md", "requirements.txt")],
    # gds2openEMS: the local modules copy of its example (scripts/sync_local_modules_copy.py)
    *[(f"{OPENEMS}/workflow/modules/{name}", f"{OPENEMS}/more_examples/local_modules_copy/modules/{name}")
      for name in ("__init__.py", "util_gds_reader.py", "util_meshlines.py", "util_simulation_setup.py",
                   "util_stackup_reader.py", "util_utilities.py", "util_resonance_estimation.py")],
]

DIFFERENT_ON_PURPOSE = {
    # name of the recorded difference: (file, its copy)
    "stackup_reader": (f"{G2P}/workflow/gds2palace/util_stackup_reader.py", f"{OPENEMS}/workflow/modules/util_stackup_reader.py"),
    "stackup_writer": (f"{SETUPEM}/src/setupEM/stackup_writer.py", f"{OPENEMS}/stackup_editor/stackup_writer.py"),
    "stackup_editor": (f"{SETUPEM}/src/setupEM/stackupEditor.py", f"{OPENEMS}/stackup_editor/stackupEditor.py"),
    "momentum_import": (f"{SETUPEM}/src/setupEM/momentum_import.py", f"{OPENEMS}/stackup_editor/momentum_import.py"),
    "klayout_pdf_template": (f"{G2P}/doc/pdf_build/userguide_template.typ", f"{KLAYOUT}/doc/pdf_build/userguide_template.typ"),
    "klayout_pdf_build": (f"{G2P}/doc/pdf_build/build_userguide_pdf.py", f"{KLAYOUT}/doc/pdf_build/build_userguide_pdf.py"),
}


SHARED_FUNCTIONS = {
    "gds_reader_functions": (f"{G2P}/workflow/gds2palace/util_gds_reader.py", f"{OPENEMS}/workflow/modules/util_gds_reader.py"),
}


def lines_of(relative):
    """The file's lines without line endings, or skip the test if its repository is not there."""
    path = os.path.join(WORKSPACE, *relative.split("/"))
    if not os.path.isdir(os.path.join(WORKSPACE, relative.split("/")[0])):
        pytest.skip(f"sibling repository {relative.split('/')[0]} is not next to this one")
    assert os.path.isfile(path), f"{relative} is missing"
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n").split("\n")


def differences(a, b):
    """The blocks in which two files differ, as text: '-' lines of the first file, '+' lines of the second, without
    line numbers, so that the same change in both files leaves it unchanged."""
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            out += ["@@"] + ["-" + line for line in a[i1:i2]] + ["+" + line for line in b[j1:j2]]
    return "\n".join(out) + "\n"


@pytest.mark.parametrize("first, second", IDENTICAL, ids=[pair[1] for pair in IDENTICAL])
def test_identical_copies(first, second):
    a, b = lines_of(first), lines_of(second)
    found = differences(a, b) if a != b else ""
    assert a == b, (f"{second} is no longer a copy of {first}: bring the change into the other file too.\n"
                    + found[:3000])


@pytest.mark.parametrize("name", sorted(DIFFERENT_ON_PURPOSE))
def test_copies_differ_only_as_recorded(name):
    first, second = DIFFERENT_ON_PURPOSE[name]
    found = differences(lines_of(first), lines_of(second))
    recorded_file = os.path.join(RECORDED, name + ".diff")
    if os.environ.get("UPDATE_SIBLING_COPIES"):
        os.makedirs(RECORDED, exist_ok=True)
        with open(recorded_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(found)
    assert os.path.isfile(recorded_file), f"no recorded differences: run with UPDATE_SIBLING_COPIES=1"
    with open(recorded_file, encoding="utf-8", newline="") as f:
        recorded = f.read().replace("\r\n", "\n")
    if found != recorded:
        new = [block for block in found.split("@@\n") if block and block not in recorded.split("@@\n")]
        gone = [block for block in recorded.split("@@\n") if block and block not in found.split("@@\n")]
        pytest.fail(
            f"{first}\nand {second}\nno longer differ as recorded in tests/sibling_copies/{name}.diff.\n"
            "A change went into one of them only: bring it into the other one. If the new difference is meant, "
            "run with UPDATE_SIBLING_COPIES=1.\n"
            + "".join("\nnew difference:\n" + block for block in new[:5])[:3000]
            + "".join("\nno longer there:\n" + block for block in gone[:5])[:1500])


def functions_of(relative):
    """{name: code lines} of the functions and methods of a Python file ("Class.method" for methods), without
    comments and docstrings, so that only a change of the code counts."""
    tree = ast.parse("\n".join(lines_of(relative)))
    found = {}

    def visit(node, prefix):
        for child in node.body:
            if isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                first = child.body[0] if child.body else None
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                        and isinstance(first.value.value, str):
                    child.body = child.body[1:] or [ast.Pass()]
                found[prefix + child.name] = ast.unparse(child).split("\n")
    visit(tree, "")
    return found


@pytest.mark.parametrize("name", sorted(SHARED_FUNCTIONS))
def test_shared_functions_differ_only_as_recorded(name):
    first, second = SHARED_FUNCTIONS[name]
    a, b = functions_of(first), functions_of(second)
    report = [f"only in {first.split('/')[0]}: " + ", ".join(sorted(set(a) - set(b))),
              f"only in {second.split('/')[0]}: " + ", ".join(sorted(set(b) - set(a)))]
    for function in sorted(set(a) & set(b)):
        if a[function] != b[function]:
            report.append(f"== {function}\n" + differences(a[function], b[function]).rstrip("\n"))
    found = "\n".join(report) + "\n"
    recorded_file = os.path.join(RECORDED, name + ".diff")
    if os.environ.get("UPDATE_SIBLING_COPIES"):
        os.makedirs(RECORDED, exist_ok=True)
        with open(recorded_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(found)
    assert os.path.isfile(recorded_file), "no recorded differences: run with UPDATE_SIBLING_COPIES=1"
    with open(recorded_file, encoding="utf-8", newline="") as f:
        recorded = f.read().replace("\r\n", "\n")
    if found != recorded:
        changed = "\n".join(difflib.unified_diff(recorded.split("\n"), found.split("\n"), "recorded", "now",
                                                 lineterm="", n=2))
        pytest.fail(
            f"The functions that {first}\nand {second}\nshare no longer differ as recorded in "
            f"tests/sibling_copies/{name}.diff.\nA change went into one reader only: bring it into the other one. "
            "If the new difference is meant, run with UPDATE_SIBLING_COPIES=1.\n" + changed[:4000])
