"""Scanning, validating and staging slide files for the Add slides screen.

Kept apart from the Qt widget so the part that touches the user's 392 GB of data
can be tested without opening a window.

Two things this module exists to get right:

**A misnamed file is invisible.** `00_manifest` matches every candidate against
`NAME_RE` and silently skips what does not fit, so a file called `LS45_8b copy.czi`
never reaches any stage and nothing ever says so. The scan reports the failures
alongside the successes; that report is the whole point of the screen.

**Nothing is copied by accident.** The dataset here is 222 files and 392.7 GB.
Selecting a folder sets a path and moves nothing. Selecting scattered files makes
hardlinks, which cost no bytes on the same volume. Copying is the last resort,
never implicit, and always quoted in GB first.
"""

import os
import re
import shutil


# The grammar belongs to the study, not to this file - see name_pattern().
# This is the bootstrap only: before a study exists there is no grammar to read
# and the screen still has to draw something, which is also the one situation
# in which the stage module cannot be loaded.
_FALLBACK_NAME_RE = re.compile(
    r"^(?P<subject>[A-Za-z]+\d+)_(?P<slide>\d+)(?P<replicate>[a-z])?\.czi$",
    re.IGNORECASE)

def _natural_key(text):
    """LS7 < LS22 < LS120, and Fish-3 < Fish-12, with no grammar assumed.

    The previous key was `int(a[2:]) if a[2:].isdigit() else 0`, which sorted
    every id that was not two letters and digits into one bucket. ls_naming
    owns the real one; this is the copy the app can use before a study exists.
    """
    return tuple((1, int(part)) if part.isdigit() else (0, part.lower())
                 for part in re.split(r"(\d+)", str(text)) if part != "")


SLIDE_EXTS = (".czi", ".zip")          # 00_manifest reads zips of czis too


def name_pattern(runner=None):
    """The filename grammar, from 00_manifest if it can be loaded.

    One definition is the point: if the naming convention changes, the import
    screen must change with it rather than quietly accepting files the manifest
    will drop.
    """
    if runner is not None:
        try:
            return runner.load("00_manifest.py").name_pattern()
        except Exception:                                  # noqa: BLE001
            pass
    return _FALLBACK_NAME_RE


class SlideFile:
    def __init__(self, path, pattern):
        self.path = os.path.abspath(path)
        self.name = os.path.basename(self.path)
        try:
            self.size = os.path.getsize(self.path)
        except OSError:
            self.size = 0
        self.animal = self.slide = self.marker = ""
        self.recognised = False
        self.reason = ""

        stem = self.name
        if stem.lower().endswith(".zip"):
            # A zip is opened by 00_manifest and judged on what is inside, which
            # this screen does not unpack. Report it as carried, not as parsed.
            self.reason = "zip archive - contents checked when the manifest runs"
            self.recognised = True
            return

        m = pattern.match(stem)
        if m:
            g = m.groupdict()
            self.recognised = True
            # groupdict, not positional groups: a study's pattern may capture
            # anything it likes, and only these three have a meaning here.
            self.animal = g.get("subject") or ""
            self.slide = g.get("slide") or ""
            self.marker = g.get("replicate") or ""
        else:
            self.reason = "name does not match this study's slide_naming.pattern"

    @property
    def parent(self):
        return os.path.dirname(self.path)


def scan_paths(paths, pattern):
    """Turn a folder or a list of files into SlideFile records.

    A folder is scanned one level deep, matching `00_manifest`, which globs
    `SOURCE_DIR/*.czi` rather than walking. Recursing here would show the user
    files the pipeline will never look at.
    """
    found = []
    for p in paths:
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                if name.lower().endswith(SLIDE_EXTS):
                    found.append(os.path.join(p, name))
        elif os.path.isfile(p) and p.lower().endswith(SLIDE_EXTS):
            found.append(p)
    seen, out = set(), []
    for f in found:
        a = os.path.abspath(f)
        if a not in seen:
            seen.add(a)
            out.append(SlideFile(a, pattern))
    return out


def summarise(files):
    ok = [f for f in files if f.recognised]
    bad = [f for f in files if not f.recognised]
    animals = sorted({f.animal for f in ok if f.animal}, key=_natural_key)
    return {
        "n": len(files), "n_ok": len(ok), "n_bad": len(bad),
        "bytes": sum(f.size for f in files),
        "animals": animals,
        "parents": sorted({f.parent for f in files}),
    }


def same_volume(a, b):
    """Whether two paths sit on the same Windows volume."""
    da = os.path.splitdrive(os.path.abspath(a))[0].upper()
    db = os.path.splitdrive(os.path.abspath(b))[0].upper()
    return bool(da) and da == db


_LINK_CACHE = {}


def links_supported(folder):
    """Whether this folder's filesystem can make hardlinks - by trying one.

    Measured, not inferred from the drive letter or the filesystem name. The
    slide drive here is a 4.7 TB exFAT volume, which refuses both hardlinks and
    symlinks with a bare "Incorrect function"; NTFS allows hardlinks but wants a
    privilege for symlinks. Guessing from either would have been wrong, and the
    failure only shows up once the user has committed to an import.
    """
    key = os.path.splitdrive(os.path.abspath(folder))[0].upper() or folder
    if key in _LINK_CACHE:
        return _LINK_CACHE[key]
    ok = False
    probe = os.path.join(folder, ".lsapp_linkprobe")
    link = probe + ".lnkprobe"
    try:
        os.makedirs(folder, exist_ok=True)
        with open(probe, "wb") as fh:
            fh.write(b"probe")
        os.link(probe, link)
        ok = True
    except OSError:
        ok = False
    finally:
        for p in (link, probe):
            try:
                os.remove(p)
            except OSError:
                pass
    _LINK_CACHE[key] = ok
    return ok


# How a selection becomes the dataset, in order of preference.
USE_FOLDER = "use_folder"      # point source_dir at it; move nothing
SUBSET = "subset"              # same, plus an allowlist of the chosen names
LINK = "link"                  # hardlink into out_root/slides
COPY = "copy"                  # last resort, needs explicit confirmation


def plan_import(files, out_root, chose_folder=None):
    """Decide how to make this selection the dataset, without doing it.

    Returns (mode, target, note, names). `names` is the allowlist to write to
    config as `source_files`, or None to process the whole folder.

    The caller shows `note` before acting. For the copy case that text is the
    only thing between a click and moving hundreds of gigabytes.
    """
    if chose_folder:
        return (USE_FOLDER, os.path.abspath(chose_folder),
                "Nothing is moved - the folder is used where it is.", None)

    parents = sorted({f.parent for f in files})
    if len(parents) == 1:
        folder = parents[0]
        present = {n for n in os.listdir(folder) if n.lower().endswith(SLIDE_EXTS)}
        chosen = {f.name for f in files}
        if chosen >= present:
            return (USE_FOLDER, folder,
                    "Every slide in that folder was selected, so the folder is "
                    "used as it is. Nothing is moved.", None)
        # A subset of one folder is the ordinary reason to pick files rather
        # than a folder: "process these, not the rest". An allowlist says that
        # exactly, and copies nothing.
        return (SUBSET, folder,
                f"{len(chosen)} of the {len(present)} slides in that folder will "
                f"be processed. The rest stay where they are and are ignored. "
                f"Nothing is moved.", sorted(chosen))

    dest = os.path.join(out_root, "slides")
    total = sum(f.size for f in files)
    if links_supported(out_root):
        return (LINK, dest,
                f"{len(files)} files across {len(parents)} folders will be "
                f"hardlinked into {dest}. Hardlinks cost no disk space - "
                f"the {total/1e9:.1f} GB is not duplicated.", None)
    return (COPY, dest,
            f"These {len(files)} files are spread across {len(parents)} folders, "
            f"and {os.path.splitdrive(out_root)[0] or out_root} cannot make "
            f"links (exFAT and FAT volumes cannot). The only way to gather them "
            f"is to COPY {total/1e9:.1f} GB. Putting the files in one folder "
            f"first is usually the better answer.", None)


def apply_import(files, mode, target, progress=None):
    """Carry out a plan. Returns (staged_count, [(name, error), ...]).

    Hardlink first, symlink second, copy only when the mode says so. The symlink
    attempt is worth making because it succeeds under Developer Mode and costs
    nothing when it does not.
    """
    if mode in (USE_FOLDER, SUBSET):
        return 0, []

    os.makedirs(target, exist_ok=True)
    staged, errors = 0, []
    for i, f in enumerate(files):
        dst = os.path.join(target, f.name)
        if progress:
            progress(i, len(files), f.name)
        if os.path.exists(dst):
            staged += 1
            continue
        try:
            if mode == LINK:
                try:
                    os.link(f.path, dst)
                except OSError:
                    os.symlink(f.path, dst)
            else:
                shutil.copy2(f.path, dst)
            staged += 1
        except OSError as e:
            errors.append((f.name, str(e)))
    return staged, errors
