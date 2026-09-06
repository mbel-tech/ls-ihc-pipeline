"""Emit docs/software_versions.md from the environments that actually ran.

Read rather than remembered: the table in the methods document is generated from
`pip freeze` of the analysis venv and from R itself, so a version cannot drift
between what is installed and what is claimed. Anything not installed is reported
as such rather than silently omitted - a missing row in a methods table reads as
"not used", which is a different statement.

Run:  python docs/make_versions_table.py
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

APPENV = os.path.join(ROOT, "work", "appenv", "Scripts", "python.exe")
RSCRIPT = r"C:\Program Files\R\R-4.6.0\bin\Rscript.exe"

# package name -> (display name, what it does in this pipeline)
PY_PACKAGES = [
    ("pylibCZIrw",       "pylibCZIrw",     "reads every CZI pixel whose value reaches a result"),
    ("czifile",          "czifile",        "raw per-tile pixels, for instrument characterisation only"),
    ("imagecodecs",      "imagecodecs",    "JPEG-XR decoding, required by czifile"),
    ("numpy",            "NumPy",          "arrays, the affine algebra, the mask lookups"),
    ("scipy",            "SciPy",          "rotation, filtering, optimal assignment"),
    ("pandas",           "pandas",         "tabular joins in the dataset stages"),
    ("pillow",           "Pillow",         "image resizing in the reformat and its inverse"),
    ("scikit-image",     "scikit-image",   "per-object measurement (regionprops)"),
    ("stardist",         "StarDist",       "nucleus segmentation"),
    ("csbdeep",          "csbdeep",        "percentile intensity normalisation before segmentation"),
    ("tensorflow",       "TensorFlow",     "the neural-network backend StarDist runs on"),
    ("keras",            "Keras",          "model API above TensorFlow"),
    ("pymupdf",          "PyMuPDF",        "atlas plate and region-seed extraction from the PDF"),
    ("itk-elastix",      "itk-elastix",    "affine and B-spline registration (assessed, QC only)"),
    ("opencv-python-headless", "OpenCV",   "connected components and morphology"),
    ("tifffile",         "tifffile",       "TIFF interchange with Fiji"),
    ("matplotlib",       "matplotlib",     "QC figures and the workflow diagram"),
    ("openpyxl",         "openpyxl",       "the output workbooks"),
    ("PySide6",          "PySide6",        "the desktop application shell"),
]

R_PACKAGES = [
    ("ggplot2",  "the figures"),
    ("ggtext",   "rich-text axis and panel labels"),
    ("lme4",     "mixed models where an animal contributes more than one row"),
    ("lmerTest", "degrees of freedom and p-values for those models"),
    ("emmeans",  "estimated marginal means and contrasts"),
    ("multcomp", "multiplicity adjustment across contrasts"),
    ("officer",  "writing the figure deck"),
    ("readxl",   "reading the workbooks back in"),
]


def pip_versions(python_exe):
    if not os.path.exists(python_exe):
        return {}
    out = subprocess.run([python_exe, "-m", "pip", "freeze"],
                         capture_output=True, text=True).stdout
    versions = {}
    for line in out.splitlines():
        if "==" in line:
            name, _, ver = line.partition("==")
            versions[name.strip().lower()] = ver.strip()
    return versions


def python_version(python_exe):
    if not os.path.exists(python_exe):
        return "not found"
    out = subprocess.run([python_exe, "-V"], capture_output=True, text=True)
    return (out.stdout + out.stderr).strip().replace("Python ", "")


def r_versions():
    if not os.path.exists(RSCRIPT):
        return "not found", {}
    names = ",".join('"%s"' % p for p, _ in R_PACKAGES)
    script = (
        'cat(R.version.string, "\\n"); '
        'for (p in c(%s)) { '
        'v <- tryCatch(as.character(packageVersion(p)), error = function(e) "not installed"); '
        'cat(p, v, "\\n") }' % names
    )
    out = subprocess.run([RSCRIPT, "-e", script], capture_output=True, text=True).stdout
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    rver = lines[0].replace("R version ", "").split(" (")[0] if lines else "unknown"
    vers = {}
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 2:
            vers[parts[0]] = " ".join(parts[1:])
    return rver, vers


BEGIN = "<!-- BEGIN software-versions -->"
END = "<!-- END software-versions -->"


def splice(table):
    """Write the table into pipeline-methods.md between the two sentinels.

    The methods document is a deliverable in its own right, so it carries the
    finished table rather than a placeholder that only pandoc resolves. Splicing
    keeps that copy current without a second source of truth.
    """
    path = os.path.join(HERE, "pipeline-methods.md")
    if not os.path.exists(path):
        print("no pipeline-methods.md to splice into", file=sys.stderr)
        return
    with open(path, encoding="utf8") as fh:
        doc = fh.read()
    if BEGIN not in doc or END not in doc:
        raise SystemExit("pipeline-methods.md is missing the software-versions sentinels")
    head, _, rest = doc.partition(BEGIN)
    _, _, tail = rest.partition(END)
    with open(path, "w", encoding="utf8", newline="\n") as fh:
        fh.write(head + BEGIN + "\n\n" + table + "\n" + END + tail)
    print("spliced the table into %s" % path)


def main():
    py = pip_versions(APPENV)
    pyver = python_version(APPENV)
    rver, rv = r_versions()

    rows = ["| Software | Version | What it does here |", "|---|---|---|"]
    rows.append("| Python | %s | the interpreter every stage runs under |" % pyver)
    for key, name, role in PY_PACKAGES:
        rows.append("| %s | %s | %s |" % (name, py.get(key.lower(), "not installed"), role))
    rows.append("| R | %s | the statistics and figure layer |" % rver)
    for name, role in R_PACKAGES:
        rows.append("| %s (R) | %s | %s |" % (name, rv.get(name, "not installed"), role))

    text = "\n".join(rows) + "\n"
    path = os.path.join(HERE, "software_versions.md")
    with open(path, "w", encoding="utf8", newline="\n") as fh:
        fh.write(text)
    print("wrote %s (%d rows)" % (path, len(rows) - 2))
    splice(text)
    missing = [r for r in rows if "not installed" in r or "not found" in r]
    if missing:
        print("NOTE - reported as unavailable:", file=sys.stderr)
        for m in missing:
            print("  " + m, file=sys.stderr)


if __name__ == "__main__":
    main()
