// Review mode: the provenance table, the derived paths, and what gets exported.
//
// What this covers is the part a screenshot would not catch. The three image
// states and the mask overlay are pixels and were checked in a real browser;
// these are the decisions underneath them:
//
//   * the pooled table decodes back to the strings it came from - the whole
//     column is an integer index on the wire, and a decode that silently
//     returned the index would still render as *something*;
//   * the three image paths are DERIVED, not carried, so the rule lives in two
//     places (04p writes them, revSrc rebuilds them) and has to agree;
//   * a decision lands on the section's own entry, survives a reload, and does
//     not leak into the ROI exports - the store is shared with ROI work;
//   * the export maps three UI verbs onto the columns 04a reads, and quotes the
//     operator's free-text reason, which routinely contains commas.

const { env, load, chk, note, done } = require("./harness");
const { store } = env;

const X = load(`{KEY, PROV, PROWS, P_BY, st, save, revSrc, revAct, revPick,
  revImg, cycleRevImg, exportReview, csvq, esc,
  get revImgMode(){return revImgMode}, set revImgMode(v){revImgMode=v},
  get revSel(){return revSel}}`);

// ---- the table ------------------------------------------------------------

if (!X.PROWS.length) {
  note("no section_provenance.csv - run 04p_section_provenance.py; skipping");
  done();
  return;
}

chk("every scanned section is carried", X.PROWS.length, X.PROV.r.length);
chk("pooled columns are declared", X.PROV.p.status !== undefined, true);

// A pooled value must come back as its string, not as the index it travelled as.
const statuses = new Set(X.PROWS.map(p => p.status));
chk("status decodes to strings, not indices",
    [...statuses].every(s => typeof s === "string" && /[a-z]/.test(s)), true);
chk("...and only to declared ones",
    [...statuses].every(s => X.PROV.p.status.includes(s)), true);

const reasons = X.PROWS.filter(p => p.decision_reason).map(p => p.decision_reason);
chk("free-text reasons decode too",
    reasons.length > 0 && typeof reasons[0] === "string", true);

// ---- derived paths --------------------------------------------------------
//
// 04p wrote overview_img/section_img/mask_img and this rebuilds them from
// has_*. If the naming rule drifts in either place, every picture in the mode
// 404s at once - and an <img> that fails is silent.

const withAll = X.PROWS.find(p => p.has_overview && p.has_section && p.has_mask);
if (withAll) {
  const mk = withAll.marker === "AF568" ? "_AF568" : "";
  chk("overview path", X.revSrc(withAll, "overview"),
      `../overviews/${withAll.animal}/${withAll.marker}/${withAll.scene_uid}_RGB.png`);
  chk("section path", X.revSrc(withAll, "section"),
      `sections${mk}/${withAll.scene_uid}.png`);
  chk("mask path", X.revSrc(withAll, "mask"),
      `../artifacts/${withAll.scene_uid}_artifact.png`);
}

const noSection = X.PROWS.find(p => !p.has_section);
if (noSection) {
  chk("a section with no reformatted image yields no path",
      X.revSrc(noSection, "section"), "");
  chk("...but still has an overview", !!X.revSrc(noSection, "overview"), true);
}

// ---- the image cycle ------------------------------------------------------
//
// With no mask there is only one picture to show, so cycling has to stay put -
// otherwise two of the three states are indistinguishable and the button looks
// broken.

const noMask = X.PROWS.find(p => !p.has_mask);
if (noMask) {
  X.revPick(noMask.scene_uid);
  X.revImgMode = 0;
  X.cycleRevImg();
  chk("no mask - the cycle stays on unmasked", X.revImgMode, 1);
  X.cycleRevImg();
  chk("...and stays there", X.revImgMode, 1);
}

const masked = X.PROWS.find(p => p.has_mask);
X.revPick(masked.scene_uid);
X.revImgMode = 0;
const seen = [];
for (let i = 0; i < 4; i++) { seen.push(X.revImgMode); X.cycleRevImg(); }
chk("with a mask it cycles through all three", seen.join(""), "0120");

// ---- decisions ------------------------------------------------------------

const target = X.PROWS.find(p => p.status === "excluded");
X.revPick(target.scene_uid);
env.els.revWhy.value = "tissue is fine, the focus call was wrong";
X.revAct("restore");

chk("the decision lands on the section's own entry",
    X.st(target.scene_uid).rev.act, "restore");
chk("...with the reason", X.st(target.scene_uid).rev.why,
    "tissue is fine, the focus call was wrong");
// The status at the time is kept: a decision made when a section was excluded
// means something different once it is not, and the export carries it.
chk("...and the status it was taken against",
    X.st(target.scene_uid).rev.status, "excluded");

const onDisk = JSON.parse(store[X.KEY] || "{}")[target.scene_uid];
chk("it is written through, not held in memory", onDisk.rev.act, "restore");

// ---- export ---------------------------------------------------------------

const mk = X.PROWS.find(p => p.has_mask && p.scene_uid !== target.scene_uid);
X.revPick(mk.scene_uid);
env.els.revWhy.value = "mask is eating the pial rim, not an artifact";
X.revAct("unmask");

// dl() builds a Blob, and the harness records the text of every one - so the
// export is read back exactly as it would land on disk, commas and all.
const before = env.blobs.length;
X.exportReview();
chk("the export produced a file", env.blobs.length > before, true);

const csv = env.blobs[env.blobs.length - 1];
const lines = csv.split("\n");
chk("header is the shape 04a reads", lines[0],
    "scene_uid,marker,extra_rotation,flip,excluded,decision,mask_rejected,reason,prior_status");

const byUid = {};
for (const l of lines.slice(1)) byUid[l.split(",")[0]] = l;
const restored = byUid[target.scene_uid], unmasked = byUid[mk.scene_uid];

chk("a reinstatement is decision=restored",
    restored.split(",")[5], "restored");
chk("...and is not excluded", restored.split(",")[4], "0");
chk("...and rejects no mask", restored.split(",")[6], "0");
chk("a mask rejection sets mask_rejected", unmasked.split(",")[6], "1");
chk("...and takes no decision on exclusion", unmasked.split(",")[5], "");
// dl() joins on commas and quotes nothing, so anything operator-typed has to
// arrive already quoted or it splits into extra columns and every field after
// the reason shifts by one.
chk("the reason is quoted, so the row does not split",
    unmasked.includes('"mask is eating the pial rim, not an artifact"'), true);
chk("...and the row still has nine fields",
    unmasked.replace(/"[^"]*"/g, "Q").split(",").length, 9);

chk("csvq leaves a plain value alone", X.csvq("no commas here"), "no commas here");
chk("csvq doubles an embedded quote", X.csvq('a "quoted" bit'), '"a ""quoted"" bit"');
chk("esc neutralises markup", X.esc("<b>&</b>"), "&lt;b&gt;&amp;&lt;/b&gt;");

done();
