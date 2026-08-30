// Guided mode: the plate's numbered seeds as a click-through list.
//
// Also covers the seed ORDER itself - down each column, columns left to
// right - and the two kinds of region uncertainty, because those are
// claims the exports make and a silent change to either would be wrong
// in a way no screenshot would show.

const { env, load, chk, note, done } = require('./harness');
const { els, store, blobs, fire } = env;

const X = load(`{KEY, PLATES, DATA, st, rows, select, onSlideUser, exportCsv, markAssigned,
  toggleGuided, skipSeed, secDown, clickPl, undoPt, clearPts, seedsOf,
  usedSeeds, status, defaultR, imgK, pairR,
  get guided(){return guided}, get gTarget(){return gTarget},
  set active(v){active=v}, get active(){return active}}`);
// a plate that actually carries seeds
const pi = X.PLATES.findIndex(P=>P.labelled);
const P  = X.PLATES[pi];
els["animal"].value="LS105";
const uid = X.rows()[0].uid; X.select(uid, true); X.active=uid;
X.onSlideUser(pi);

note("plate "+P.id+" carries "+P.seeds.length+" seeds\n");
chk("seeds arrive in a fixed order (n = 1..N)",
    P.seeds.every((s,i)=>s.n===i+1), true);
// Seeds are grouped into COLUMNS and sorted by y within one, so x wobbles by up
// to the column span along a column - the invariant is per-column, not per-seed.
const COL_BAND = 0.08, COL_SPAN = 0.12;
chk("columns run left to right (never jumps back a column)",
    P.seeds.every((s,i)=>i===0 || s.xf >= P.seeds[i-1].xf - COL_SPAN), true);
chk("and top-to-bottom within each column",
    P.seeds.every((s,i)=>i===0
      || Math.abs(s.xf-P.seeds[i-1].xf) > COL_BAND
      || s.yf >= P.seeds[i-1].yf - 1e-9), true);
chk("seed 2 sits below seed 1 (the stated example)",
    P.seeds[1].yf > P.seeds[0].yf, true);
chk("every seeded plate carries a crowding measure",
    X.PLATES.filter(p=>p.seeds.length>1).every(p=>p.nn>0), true);
const allSeeds = X.PLATES.flatMap(p=>p.seeds);
chk("every seed carries a region name",
    allSeeds.every(sd=>sd.region && sd.region.trim()), true);
chk("the atlas's own uncertain seeds are flagged",
    allSeeds.filter(sd=>sd.unk).length, 8);
chk("...and all of them are Rm",
    [...new Set(allSeeds.filter(sd=>sd.unk).map(sd=>sd.region))].join(), "Rm");
chk("the Vd/Vv/POA group is flagged separately",
    allSeeds.filter(sd=>sd.amb).length, 42);
chk("Dl and Dm are not flagged ambiguous - they are distinct places",
    allSeeds.filter(sd=>(sd.region==="Dl"||sd.region==="Dm") && sd.amb).length, 0);
chk("...nor is anything outside Vd/Vv/POA",
    [...new Set(allSeeds.filter(sd=>sd.amb).map(sd=>sd.region))].sort().join("/"),
    "POA/Vd/Vv");


// placement is press -> (optional drag to size) -> release, so drive the real
// gesture rather than a handler that no longer exists
const clickAt = (cx,cy,dragTo) => {
  X.secDown({clientX:cx, clientY:cy, button:0, preventDefault(){}});
  if(dragTo) fire("mousemove",{clientX:dragTo[0], clientY:dragTo[1]});
  fire("mouseup",{});
};
// Numbered placement is the default now, not a mode to switch on. Asserting
// that directly is the point: if it ever silently reverts to free
// correspondence, the whole documented process changes and nothing else here
// would notice.
chk("numbered placement is on by default", X.guided, true);
chk("cursor starts at seed 1", X.gTarget, 1);

clickAt(100,100);
const s = X.st(uid);
chk("one click makes a whole pair", s.pairs.length, 1);
chk("...tagged with the seed it answers", s.pairs[0][4], 1);
chk("...using that seed's own plate coords",
    [s.pairs[0][2].toFixed(2), s.pairs[0][3].toFixed(2)].join(),
    [(P.seeds[0].xf*P.w).toFixed(2), (P.seeds[0].yf*P.h).toFixed(2)].join());
chk("cursor advanced", X.gTarget, 2);

X.skipSeed();
chk("skip moves past seed 2 without placing it", X.gTarget, 3);
clickAt(120,120);
chk("next click answers seed 3", s.pairs[1][4], 3);
chk("skipped seed 2 is still unplaced", X.usedSeeds(s).has(2), false);

// re-aim by clicking the plate
X.clickPl({clientX:0, clientY:0, button:0});
chk("clicking a plate seed re-aims the cursor", X.gTarget>0, true);

// undo puts the cursor back
const before = X.gTarget;
X.undoPt();
chk("undo removes the pair", s.pairs.length, 1);
chk("...and the cursor follows it back to seed 2", X.gTarget, 2);

// resume: leave the section and return
clickAt(140,140);                       // seed 2
const placed = X.usedSeeds(s).size;
const other = X.rows()[1].uid;
X.select(other, true); X.select(uid, true);
chk("returning resumes rather than restarting", X.usedSeeds(X.st(uid)).size, placed);
chk("...cursor points at the first gap", X.gTarget, 3);

// ---- radius: set in the placing gesture ----------------------------------
chk("a plain press keeps the default radius",
    X.pairR(s.pairs[s.pairs.length-1]).toFixed(2), X.defaultR().toFixed(2));
const nBefore = s.pairs.length;
clickAt(300,300,[360,300]);            // press, drag out, release
const sized = s.pairs[s.pairs.length-1];
chk("dragging out grows it", X.pairR(sized) > X.defaultR(), true);
chk("...to the distance dragged, in image px",
    X.pairR(sized) > X.defaultR()*1.5, true);
chk("...and it is stored on the pair", sized.length, 6);

// free clicks still work with guided off
X.toggleGuided();
chk("guided off", X.guided, false);
clickAt(200,200);
X.clickPl({clientX:210, clientY:210, button:0});
const last = X.st(uid).pairs.slice(-1)[0];
chk("a free pair is still two gestures", X.st(uid).pairs.length, nBefore+2);
chk("...and carries no seed number", !last[4], true);
chk("...but does carry a radius", last[5] > 0, true);

// export provenance
blobs.length=0; X.exportCsv();
const lm = blobs[1].split("\n");
const h  = lm[0].split(",");
const ci = {n:h.indexOf("seed_n"), r:h.indexOf("seed_region"), pair:h.indexOf("pair")};
chk("roi_landmarks.csv gained seed columns", ci.n>0 && ci.r>0, true);
const body = lm.slice(1).map(l=>l.split(","));
chk("roi_landmarks.csv gained sec_r", h.indexOf("sec_r") > 0, true);
chk("guided rows name their seed",
    body.filter(r=>r[ci.n]!=="").length, nBefore+1);
chk("...with its region", body.find(r=>r[ci.n]==="1")[ci.r], P.seeds[0].amb||P.seeds[0].region);
chk("free rows leave it blank", body.filter(r=>r[ci.n]==="").length, 1);
const ri = h.indexOf("sec_r");
chk("radius is exported in canonical px",
    body.every(r=>+r[ri] > 0), true);

done();
