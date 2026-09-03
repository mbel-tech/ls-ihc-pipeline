// Both channels in one page, the view filters, and per-row export.
//
// pERK and PCNA are separate physical sections that share only the tool,
// so the thing under test is that nothing crosses between them: each row
// carries its own marker and subset, and hiding the excluded is a view
// rather than a deletion.

const { env, load, chk, note, done } = require('./harness');
const { els, store, blobs, fire } = env;

const X = load(`{KEY, DATA, MARKERS, st, rows, inScope, render, onMarker, select,
  exportCsv, toggleExcl, hasRgb, status, scopeLabel, counts, onSlideUser,
  set active(v){active=v}, get active(){return active}}`);
console.log("MARKERS:", JSON.stringify(X.MARKERS));
console.log("marker options:", els["marker"].innerHTML.replace(/<[^>]*>/g,"|").replace(/\|+/g,"|"));
note("");
const perk=X.DATA.filter(d=>d.m==="AF568"), pcna=X.DATA.filter(d=>d.m==="AF488");
chk("both channels in one page", X.DATA.length, perk.length+pcna.length);
chk("pERK rows", perk.length, 454);
chk("PCNA rows", pcna.length, 788);
chk("no uid collides across channels",
    new Set(X.DATA.map(d=>d.uid)).size, X.DATA.length);
chk("every row has a composite", X.DATA.filter(d=>d.rgb).length, X.DATA.length);
chk("each row carries its own subset",
    [...new Set(X.DATA.map(d=>d.m+"/"+d.sub))].sort().join(" "),
    "AF488/all AF568/roi_worklist");

// ---- the channel filter -------------------------------------------------
els["animal"].value="LS105";
els["marker"].value="AF568"; X.render();
const nPerk=X.rows().length;
chk("filter -> pERK only", X.rows().every(d=>d.m==="AF568"), true);
els["marker"].value="AF488"; X.onMarker();
const nPcna=X.rows().length;
chk("filter -> PCNA only", X.rows().every(d=>d.m==="AF488"), true);
els["marker"].value="both"; X.onMarker();
chk("filter -> both", X.rows().length, nPerk+nPcna);
chk("scope label follows the filter", els["scope"].innerHTML.includes("both channels"), true);

// ---- hide excluded ------------------------------------------------------
els["marker"].value="AF568"; X.onMarker();
const list=X.rows(); const victim=list[0].uid;
X.active=victim; X.toggleExcl();
X.counts();
const exclCount=els["nexcl"].textContent;
chk("excluded still counted while visible", exclCount, 1);
chk("still in the strip", X.rows().some(d=>d.uid===victim), true);
els["hideExcl"].checked=true; X.render(); X.counts();
chk("hide excluded removes it from the strip", X.rows().some(d=>d.uid===victim), false);
chk("...but the count still reports it", els["nexcl"].textContent, exclCount);
chk("...and it keeps its flag", !!JSON.parse(store[X.KEY])[victim].excl, true);
els["hideExcl"].checked=false; X.render();
chk("unticking brings it back", X.rows().some(d=>d.uid===victim), true);

// ---- selecting a section the filter hides --------------------------------
//
// This was a silent misassignment, not a crash the operator could see.
// select() looked the uid up in rows() - the strip AFTER the filters - took
// list[-1] as undefined and threw on `d.uid`, but only AFTER assigning
// `active = uid`. So the big view kept showing the previous section while
// `active` pointed at the hidden one, and the next plate assignment landed on
// a section that was not on screen: "this section will not take a plate".
els["hideExcl"].checked=true; X.render();
chk("the victim really is filtered out", X.rows().some(d=>d.uid===victim), false);
let threw = "";
try { X.select(victim); } catch (e) { threw = e.message; }
chk("selecting a hidden section does not throw", threw, "");
chk("...and active is the section asked for", X.active, victim);
chk("...and the info line says the filter is hiding it",
    /hidden by the current filter/.test(els["secInfo"].innerHTML), true);

// The assignment must land on the section that is actually selected.
els["slider"].value = 3;
X.onSlideUser(3);
chk("a plate assigned now lands on that same section",
    JSON.parse(store[X.KEY])[victim].plate, 3);

// A uid the page has never heard of changes nothing at all.
const keepActive = X.active;
X.select("NOT_A_SECTION");
chk("an unknown uid leaves the selection alone", X.active, keepActive);
els["hideExcl"].checked=false; X.render();

// ---- export carries each row's own channel -------------------------------
// Only sections carrying a decision are exported (assigned || fav || excl), so
// make one on each channel first - that is the point being tested.
els["marker"].value="AF488"; X.onMarker();
const pcnaUid=X.rows()[0].uid; X.active=pcnaUid; X.toggleExcl();
els["marker"].value="AF568"; X.onMarker();
blobs.length=0; X.exportCsv();
const plates=blobs[0].split("\n");
const hdr=plates[0].split(",");
const mi=hdr.indexOf("marker"), si=hdr.indexOf("subset"), xi=hdr.indexOf("excluded");
const body=plates.slice(1).map(l=>l.split(","));
chk("export covers the decided sections on both channels", body.length, 2);
chk("export markers are per row",
    [...new Set(body.map(r=>r[mi]))].sort().join("+"), "AF488+AF568");
chk("export subsets are per row",
    [...new Set(body.map(r=>r[mi]+"/"+r[si]))].sort().join(" "),
    "AF488/all AF568/roi_worklist");
chk("the excluded section is exported with excluded=1",
    body.find(r=>r[0]===victim)[xi], 1);

done();
