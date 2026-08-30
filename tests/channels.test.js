// both markers in one page, the filters, per-row export
//
// Ported from the scratch suites that were used while building the curator.
// The assertions are unchanged: they are the record of bugs already found.

const { load, chk, note, fire, done, els, store } = require("./harness");

const blobs = [];
const X = load(
  '{KEY,DATA,MARKERS,st,rows,inScope,render,onMarker,select,exportCsv,toggleExcl,hasRgb,status,scopeLabel,counts,set active(v){active=v},get active(){return active}}',
  { blobs });

console.log("MARKERS:", JSON.stringify(X.MARKERS));
console.log("marker options:", els["marker"].innerHTML.replace(/<[^>]*>/g,"|").replace(/\|+/g,"|"));
console.log("");

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
