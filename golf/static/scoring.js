/*
 * Beregninger til golfturneringen: spillehandicap, Stableford og turneringspoint.
 * Filen bruges både i browseren (window.Scoring) og i tests med node (module.exports).
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Scoring = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /** Afrunding hvor ,5 rundes væk fra nul (som i WHS), også for negative tal. */
  function roundHalfAway(x) {
    const r = x < 0 ? -Math.round(-x) : Math.round(x);
    return r === 0 ? 0 : r; // aldrig -0
  }

  /** Banehandicap efter WHS: HCP-index × slope/113 + (CR − par). */
  function courseHandicap(hcpIndex, slope, cr, par) {
    return hcpIndex * (slope / 113) + (cr - par);
  }

  /** Det tee (navn, CR, slope) en spiller bruger på en runde. Findes spillerens tee ikke på runden,
   * bruges rundens første tee. */
  function teeFor(course, teeName) {
    const tees = course.tees && course.tees.length ? course.tees : [{ name: "", cr: course.cr, slope: course.slope }];
    const want = (teeName || "").trim().toLowerCase();
    return tees.find((t) => t.name.trim().toLowerCase() === want) || tees[0];
  }

  /** Spillehandicap = banehandicap × handicaptildeling (fx 100 eller 95 %), rundet til hele slag.
   * Svarer til DGU's course handicap table, når tildelingen er 100 %. */
  function playingHandicap(hcpIndex, course, allowancePct, teeName) {
    const par = course.par.reduce((a, b) => a + b, 0);
    const tee = teeFor(course, teeName);
    const ch = courseHandicap(hcpIndex, tee.slope, tee.cr, par);
    const pct = allowancePct == null ? 100 : allowancePct;
    return roundHalfAway((ch * pct) / 100);
  }

  /**
   * Antal tildelte slag på et hul ud fra spillehandicap og hullets handicapnøgle (1–18).
   * Positivt handicap: ét slag på alle huller pr. hele 18, plus ét ekstra på de nøgler der er
   * mindre end eller lig resten. Plushandicap (negativt): der trækkes slag fra på de letteste huller
   * (højeste nøgle) først.
   */
  function strokesOnHole(playingHcp, strokeIndex) {
    if (playingHcp >= 0) {
      const base = Math.floor(playingHcp / 18);
      const rest = playingHcp % 18;
      return base + (strokeIndex <= rest ? 1 : 0);
    }
    const n = -playingHcp;
    const base = Math.floor(n / 18);
    const rest = n % 18;
    return 0 - (base + (strokeIndex > 18 - rest ? 1 : 0));
  }

  /**
   * Stablefordpoint på et hul. strokes = null: ikke spillet endnu (null). strokes = 0: streget (0 point).
   * Ellers 2 + (par + tildelte slag − slag), dog mindst 0.
   */
  function stablefordPoints(strokes, par, received) {
    if (strokes == null) return null;
    if (strokes <= 0) return 0;
    return Math.max(0, 2 + par + received - strokes);
  }

  /** Det HCP-index spilleren har bekræftet til runden, eller null hvis spilleren ikke deltager. */
  function hcpForRound(player, roundIdx) {
    const m = player.hcpByRound;
    if (!m) return null;
    const v = m[String(roundIdx)];
    return v == null ? null : v;
  }

  /** Spilleren med rundens bekræftede HCP-index som hcp, eller null hvis ikke bekræftet. */
  function playerForRound(player, roundIdx) {
    const h = hcpForRound(player, roundIdx);
    return h == null ? null : { ...player, hcp: h };
  }

  /** Hul for hul-opgørelse for én spiller på én runde. */
  function scorecard(player, course, strokesList, allowancePct) {
    const ph = playingHandicap(player.hcp, course, allowancePct, player.tee);
    const tee = teeFor(course, player.tee);
    const holes = [];
    let total = 0, front = 0, back = 0, played = 0;
    for (let i = 0; i < 18; i++) {
      const strokes = strokesList ? strokesList[i] : null;
      const received = strokesOnHole(ph, course.si[i]);
      const pts = stablefordPoints(strokes == null ? null : strokes, course.par[i], received);
      holes.push({ hole: i + 1, par: course.par[i], si: course.si[i], received, strokes, points: pts });
      if (pts != null) {
        played++;
        total += pts;
        if (i < 9) front += pts; else back += pts;
      }
    }
    return { playingHcp: ph, tee: tee.name, holes, total, front, back, played };
  }

  /**
   * Sortering af en rundes deltagere: flest Stablefordpoint først; ved lighed vinder det laveste
   * HCP-index; derefter bedste bagni og til sidst navn (så rækkefølgen altid er entydig).
   */
  function compareRows(a, b) {
    return (
      b.total - a.total ||
      a.hcp - b.hcp ||
      b.back - a.back ||
      a.name.localeCompare(b.name, "da")
    );
  }

  /**
   * Stilling på en runde. Returnerer rækker sorteret, om runden er færdig, og turneringspoint
   * hvis den er.
   *
   * players: [{id, name, hcp, hcpByRound: {"0": 17.5, ...}}], scores: {playerId: [18 × (int|null)]}
   * Kun spillere, der har bekræftet deres HCP-index til runden, deltager; de øvrige på listen får
   * hverken placering eller point og tæller ikke med i deltagerantallet. Runden er færdig, når alle
   * deltagere har 18 huller, eller når den er lukket manuelt. Ved manuel lukning tæller kun
   * deltagere, der har indtastet mindst ét hul.
   */
  function roundStandings(players, course, scores, roundIdx, allowancePct, closed) {
    let rows = players
      .map((p) => playerForRound(p, roundIdx))
      .filter(Boolean)
      .map((p) => {
        const card = scorecard(p, course, scores[p.id], allowancePct);
        return { id: p.id, name: p.name, hcp: p.hcp, ...card };
      });
    if (closed) rows = rows.filter((r) => r.played > 0);
    rows.sort(compareRows);
    const complete = rows.length > 0 && (closed || rows.every((r) => r.played === 18));
    const n = rows.length;
    rows.forEach((r, i) => {
      r.rank = i + 1;
      r.tournamentPoints = complete ? tournamentPoints(i + 1, n) : null;
    });
    return { rows, complete, participants: n, winner: complete ? rows[0] : null };
  }

  /** Turneringspoint: vinderen får deltagere + 2, nr. 2 får deltagere − 1, ... sidstepladsen får 1. */
  function tournamentPoints(rank, participants) {
    if (rank === 1) return participants + 2;
    return participants - rank + 1;
  }

  /** Samlet stilling: sum af turneringspoint over de færdige runder; lighed afgøres af samlede
   * Stablefordpoint og derefter laveste HCP-index. Spillere, der ikke deltog på en runde, får 0
   * Stablefordpoint og 0 turneringspoint for den runde. */
  function overallStandings(players, roundResults) {
    const rows = players.map((p) => {
      const perRound = roundResults.map((rr) => {
        const row = rr.rows.find((r) => r.id === p.id);
        if (!row) return { participated: false, points: 0, stableford: 0, rank: null, played: 0 };
        return {
          participated: true,
          points: row.tournamentPoints,
          stableford: row.total,
          rank: row.rank,
          played: row.played,
        };
      });
      const points = perRound.reduce((s, r) => s + (r.points || 0), 0);
      const stableford = perRound.reduce((s, r) => s + (r.stableford || 0), 0);
      return { id: p.id, name: p.name, hcp: p.hcp, perRound, points, stableford };
    });
    rows.sort(
      (a, b) =>
        b.points - a.points || b.stableford - a.stableford || a.hcp - b.hcp || a.name.localeCompare(b.name, "da")
    );
    rows.forEach((r, i) => (r.rank = i + 1));
    return rows;
  }

  return {
    roundHalfAway,
    courseHandicap,
    teeFor,
    hcpForRound,
    playerForRound,
    playingHandicap,
    strokesOnHole,
    stablefordPoints,
    scorecard,
    compareRows,
    roundStandings,
    tournamentPoints,
    overallStandings,
  };
});
