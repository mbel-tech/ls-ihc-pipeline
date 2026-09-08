"""Which stages apply to which acquisition layout.

Two stages exist only because LS imaged each marker as a separate scan:

  02_pair_passes        pairs the two passes onto the same physical sections.
  04i_propagate_to_perk carries the curated pass's discs onto the other one.

A `multiplex` study has ONE scan per section, so there is nothing to pair and
nothing to propagate. Neither stage is deleted: LS keeps working, and the code
that built that dataset stays readable.

Restricting them matters more than it looks. Run against a multiplex study,
02_pair_passes finds no second marker and writes an empty pairing - which reads
downstream as "these sections have no partner" rather than "this stage did not
apply". A stage that quietly produces nothing is indistinguishable from a stage
that ran and found nothing, and only one of those is a problem.

The data lives here rather than on `Stage` because `app/stages.py` and
`tests/test_stages.py` both carry uncommitted work; `Stage.layouts` reads from
this module once they are free. `run_all.sh` is a separate consumer of the same
fact and is not blocked.
"""

import ls_channels as CH

# Stage script name -> the layouts it applies to. Anything absent applies to
# both: the default has to be "applies", so that adding a stage cannot make it
# silently vanish from every study by omission.
RESTRICTED = {
    "02_pair_passes.py": (CH.LAYOUT_PAIRED,),
    "04i_propagate_to_perk.py": (CH.LAYOUT_PAIRED,),
}


def layouts_for(script):
    """The layouts `script` applies to. Both, unless it is restricted."""
    return RESTRICTED.get(script, CH.LAYOUTS)


def applies(script, layout):
    """True when `script` should run for a study of this layout."""
    return layout in layouts_for(script)


def skipped(layout):
    """The scripts a study of this layout does NOT run, sorted."""
    return sorted(s for s in RESTRICTED if not applies(s, layout))
