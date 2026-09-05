"""Tests af golfturneringen: API'et (Python) og beregningerne (JavaScript, køres med node)."""
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROD = Path(__file__).resolve().parent.parent


@pytest.fixture()
def golf(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="golf_test_")
    monkeypatch.setenv("GOLF_DATA_DIR", tmp)
    monkeypatch.setenv("GOLF_PIN", "1234")
    sys.modules.pop("golf.server", None)
    server = importlib.import_module("golf.server")
    yield server
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def client(golf):
    with TestClient(golf.app) as c:
        yield c


def test_forside_og_state(client):
    assert client.get("/").status_code == 200
    assert "Stableford" in client.get("/").text
    st = client.get("/api/state").json()
    assert len(st["settings"]["rounds"]) == 3
    assert st["settings"]["rounds"][0]["date"] == "2026-09-18"
    assert st["settings"]["rounds"][0]["course"] == "Samsø Golfklub"
    r0 = st["settings"]["rounds"][0]
    assert r0["tees"][0]["name"] == "56" and r0["tees"][0]["cr"] == 70.8 and r0["tees"][0]["slope"] == 131
    assert r0["tees"][1]["name"] == "49" and r0["tees"][1]["cr"] == 66.9 and r0["tees"][1]["slope"] == 122
    assert sum(r0["tees"][1]["lengths"]) == 4885
    # Fra baneguiden: par 72 med 36 ud og 36 ind, handicapnøgle 1 på hul 5, 18 på hul 15
    assert r0["par"] == [4, 4, 5, 3, 4, 4, 4, 3, 5, 5, 3, 4, 4, 5, 3, 4, 4, 4]
    assert r0["si"] == [13, 9, 3, 15, 1, 11, 7, 17, 5, 2, 16, 6, 12, 8, 18, 10, 4, 14]
    assert sorted(r0["si"]) == list(range(1, 19))
    assert r0["tees"][0]["lengths"][0] == 320 and sum(r0["tees"][0]["lengths"]) == 5615
    assert "Lokalregler" in st["settings"]["rules"]
    assert st["pinRequired"] is True
    assert client.get("/api/state", params={"since": st["version"]}).json()["unchanged"] is True


def test_tilmeld_score_og_persistens(client, golf):
    r = client.post("/api/players", json={"name": "  Erik   Nielsen ", "hcp": 12.44})
    assert r.status_code == 201
    p = r.json()["player"]
    assert p["name"] == "Erik Nielsen" and p["hcp"] == 12.4 and p["absent"] == [False, False, False]
    assert p["tee"] == ""
    assert client.post("/api/players", json={"name": "Lise", "hcp": 30, "tee": "49"}).json()["player"]["tee"] == "49"

    assert client.post("/api/players", json={"name": "erik nielsen", "hcp": 5}).status_code == 409
    assert client.post("/api/players", json={"name": "X", "hcp": 60}).status_code == 422

    assert client.put(f"/api/scores/0/{p['id']}/1", json={"strokes": 5}).status_code == 200
    assert client.put(f"/api/scores/0/{p['id']}/2", json={"strokes": 0}).status_code == 200
    assert client.put(f"/api/scores/0/{p['id']}/19", json={"strokes": 5}).status_code == 404
    assert client.put(f"/api/scores/3/{p['id']}/1", json={"strokes": 5}).status_code == 404
    kort = client.get("/api/state").json()["scores"]["0"][p["id"]]
    assert kort[:2] == [5, 0] and kort[2] is None

    # Ryddes alle huller, forsvinder kortet
    client.put(f"/api/scores/0/{p['id']}/1", json={"strokes": None})
    client.put(f"/api/scores/0/{p['id']}/2", json={"strokes": None})
    assert p["id"] not in client.get("/api/state").json()["scores"]["0"]

    # Ret spiller
    r = client.put(f"/api/players/{p['id']}", json={"hcp": 11.2, "absent": [False, True, False], "tee": "61"})
    assert r.json()["player"]["hcp"] == 11.2 and r.json()["player"]["absent"][1] is True and r.json()["player"]["tee"] == "61"

    # Data ligger på disk og overlever en genstart
    data = json.loads((golf.DATA_FIL).read_text(encoding="utf-8"))
    assert data["players"][0]["name"] == "Erik Nielsen"
    nyt = golf.Lager(golf.DATA_FIL)
    assert nyt.state["players"][0]["hcp"] == 11.2


def test_pin_beskytter_farlige_handlinger(client):
    p = client.post("/api/players", json={"name": "Anna", "hcp": 20}).json()["player"]
    assert client.delete(f"/api/players/{p['id']}").status_code == 401
    assert client.delete(f"/api/players/{p['id']}", headers={"X-Golf-Pin": "0000"}).status_code == 401
    assert client.post("/api/rounds/0/closed").status_code == 401

    # Luk runden: ingen kan taste mere
    assert client.post("/api/rounds/0/closed", headers={"X-Golf-Pin": "1234"}).json()["closed"] is True
    assert client.put(f"/api/scores/0/{p['id']}/1", json={"strokes": 4}).status_code == 409
    client.post("/api/rounds/0/closed", params={"value": 0}, headers={"X-Golf-Pin": "1234"})
    assert client.put(f"/api/scores/0/{p['id']}/1", json={"strokes": 4}).status_code == 200

    assert client.delete(f"/api/players/{p['id']}", headers={"X-Golf-Pin": "1234"}).status_code == 200
    st = client.get("/api/state").json()
    assert st["players"] == [] and st["scores"]["0"] == {}


def test_opsaetning_valideres(client):
    st = client.get("/api/state").json()["settings"]
    st["name"] = "Bornholm Open"
    st["rounds"][0]["course"] = "Rø Golfbaner"
    st["rounds"][0]["tees"] = [{"name": "Gul", "cr": 71.3, "slope": 128}, {"name": "Rød", "cr": 72.0, "slope": 124}]
    r = client.put("/api/settings", json=st, headers={"X-Golf-Pin": "1234"})
    assert r.status_code == 200, r.text
    ny = client.get("/api/state").json()["settings"]
    assert ny["name"] == "Bornholm Open" and ny["rounds"][0]["tees"][1]["slope"] == 124

    st["rounds"][0]["tees"][1]["name"] = "gul"  # samme navn to gange
    assert client.put("/api/settings", json=st, headers={"X-Golf-Pin": "1234"}).status_code == 422
    st["rounds"][0]["tees"] = []
    assert client.put("/api/settings", json=st, headers={"X-Golf-Pin": "1234"}).status_code == 422
    st["rounds"][0]["tees"] = [{"name": "Gul", "cr": 71.3, "slope": 128, "lengths": [300] * 17}]
    assert client.put("/api/settings", json=st, headers={"X-Golf-Pin": "1234"}).status_code == 422
    st["rounds"][0]["tees"] = [{"name": "Gul", "cr": 71.3, "slope": 128, "lengths": [300] * 18}]
    st["rules"] = "## Test\nEn regel."
    assert client.put("/api/settings", json=st, headers={"X-Golf-Pin": "1234"}).status_code == 200
    assert client.get("/api/state").json()["settings"]["rules"] == "## Test\nEn regel."

    st["rounds"][1]["si"][1] = 7  # nøgle brugt to gange
    assert client.put("/api/settings", json=st, headers={"X-Golf-Pin": "1234"}).status_code == 422
    st["rounds"][1]["si"][1] = 3
    st["rounds"][2]["par"][3] = 9
    assert client.put("/api/settings", json=st, headers={"X-Golf-Pin": "1234"}).status_code == 422


JS_TEST = r"""
const assert = require("assert");
const S = require(process.argv[2]);
const course = {
  tees: [{name: "Std", cr: 72.0, slope: 113}],
  par: [4,4,3,5,4,4,3,5,4,4,5,3,4,4,5,3,4,4],
  si:  [7,3,15,11,1,13,17,9,5,8,12,18,2,14,10,16,4,6],
};
const withTee = (cr, slope) => ({...course, tees: [{name: "Std", cr, slope}]});

// Samsø Golfklub, herrer: tee 56 CR 70,8 / slope 131 og tee 49 CR 66,9 / slope 122 – tal fra klubbens
// konverteringstabel (DGU course handicap table)
const samsoe = {...course, tees: [{name: "56", cr: 70.8, slope: 131}, {name: "49", cr: 66.9, slope: 122}]};
for (const [hcp, ph] of [[-5.0, -7], [-4.6, -7], [-4.5, -6], [-0.3, -2], [-0.2, -1], [0.6, -1], [0.7, 0], [1.4, 0], [1.5, 1],
    [11.9, 13], [12.6, 13], [12.7, 14], [16.1, 17], [16.2, 18], [23.8, 26], [23.9, 27], [30.0, 34], [30.7, 34], [30.8, 35],
    [53.3, 61], [54.0, 61]]) {
  assert.strictEqual(S.playingHandicap(hcp, samsoe, 100, "56"), ph, "hcp " + hcp);
  assert.strictEqual(S.playingHandicap(hcp, samsoe, 100), ph, "hcp " + hcp + " (første tee)");
}
// Tee 49 (herrer) mod tabellen
for (const [hcp, ph] of [[-5.0, -10], [-4.1, -10], [-4.0, -9], [0.5, -5], [0.6, -4], [4.2, -1], [4.3, 0], [5.1, 0], [5.2, 1],
    [11.7, 8], [12.5, 8], [12.6, 9], [24.6, 21], [24.7, 22], [37.6, 35], [37.7, 36], [53.4, 53], [54.0, 53]]) {
  assert.strictEqual(S.playingHandicap(hcp, samsoe, 100, "49"), ph, "tee 49 hcp " + hcp);
}
// Ukendt tee falder tilbage til rundens første
assert.strictEqual(S.playingHandicap(12.4, samsoe, 100, "99"), 13);
assert.strictEqual(S.scorecard({id: "x", name: "X", hcp: 12.4, tee: "49"}, samsoe, null, 100).playingHcp, 8);
assert.strictEqual(S.scorecard({id: "x", name: "X", hcp: 12.4, tee: "49"}, samsoe, null, 100).tee, "49");
// Gammelt format (cr/slope direkte på runden) virker stadig
assert.strictEqual(S.playingHandicap(12.4, {par: course.par, si: course.si, cr: 70.8, slope: 131}, 100), 13);

// Spillehandicap (WHS)
assert.strictEqual(S.playingHandicap(12.4, course, 100), 12);
assert.strictEqual(S.playingHandicap(12.4, withTee(73.1, 130), 100), 15); // 12.4*130/113+1.1 = 15.37
assert.strictEqual(S.playingHandicap(20.0, withTee(73.1, 130), 95), 23);  // (23.0+1.1)*0.95 = 22.9
assert.strictEqual(S.playingHandicap(-2.0, course, 100), -2);
assert.strictEqual(S.roundHalfAway(2.5), 3);
assert.strictEqual(S.roundHalfAway(-2.5), -3);

// Slag pr. hul
assert.strictEqual(S.strokesOnHole(12, 12), 1);
assert.strictEqual(S.strokesOnHole(12, 13), 0);
assert.strictEqual(S.strokesOnHole(20, 2), 2);
assert.strictEqual(S.strokesOnHole(20, 3), 1);
assert.strictEqual(S.strokesOnHole(36, 18), 2);
assert.strictEqual(S.strokesOnHole(-2, 18), -1);
assert.strictEqual(S.strokesOnHole(-2, 17), -1);
assert.strictEqual(S.strokesOnHole(-2, 16), 0);

// Stableford
assert.strictEqual(S.stablefordPoints(4, 4, 0), 2);
assert.strictEqual(S.stablefordPoints(5, 4, 1), 2);
assert.strictEqual(S.stablefordPoints(3, 4, 0), 3);
assert.strictEqual(S.stablefordPoints(7, 4, 0), 0);
assert.strictEqual(S.stablefordPoints(0, 4, 1), 0);   // streget
assert.strictEqual(S.stablefordPoints(null, 4, 1), null);

// Scorekort: par hele vejen med hcp 18 giver 3 point pr. hul
const p18 = {id: "a", name: "A", hcp: 18};
const cardA = S.scorecard(p18, course, course.par.slice(), 100);
assert.strictEqual(cardA.playingHcp, 18);
assert.strictEqual(cardA.total, 54);
assert.strictEqual(cardA.front, 27);
assert.strictEqual(cardA.played, 18);
const half = course.par.slice(0, 9).concat(Array(9).fill(null));
assert.strictEqual(S.scorecard(p18, course, half, 100).played, 9);

// Turneringspoint: 18 deltagere -> vinder 20, nr. 2 17, sidst 1
assert.strictEqual(S.tournamentPoints(1, 18), 20);
assert.strictEqual(S.tournamentPoints(2, 18), 17);
assert.strictEqual(S.tournamentPoints(18, 18), 1);

// Runde: lighed afgøres af laveste hcp; runden er først færdig når alle har 18 huller
const players = [
  {id: "a", name: "Anna", hcp: 10.0, absent: [false,false,false]},
  {id: "b", name: "Bent", hcp: 14.0, absent: [false,false,false]},
  {id: "c", name: "Carl", hcp: 5.0, absent: [false,false,false]},
  {id: "d", name: "Dorte", hcp: 30.0, absent: [true,false,false]},  // spiller ikke runde 0
];
const par = course.par.slice();
const scores = {a: par, b: par, c: par.map((p, i) => i === 0 ? p + 1 : p)};
let st = S.roundStandings(players, course, scores, 0, 100, false);
assert.strictEqual(st.complete, true);
assert.strictEqual(st.participants, 3);
assert.deepStrictEqual(st.rows.map(r => r.name), ["Bent", "Anna", "Carl"]); // Bent 14 hcp: 36+14=50, Anna 46, Carl 5+36-1=40
assert.deepStrictEqual(st.rows.map(r => r.tournamentPoints), [5, 2, 1]);
assert.strictEqual(st.winner.name, "Bent");

// Lighed: samme point, laveste hcp vinder
const tie = {a: par, c: par.map((p, i) => i < 5 ? p - 1 : p)}; // Carl: 5 hcp -> 41 +5 = 46 = Anna 46
st = S.roundStandings(players.slice(0, 3), course, tie, 0, 100, false);
assert.strictEqual(st.complete, false); // Bent mangler
assert.deepStrictEqual(st.rows.map(r => [r.name, r.total]), [["Carl", 46], ["Anna", 46], ["Bent", 0]]);
assert.strictEqual(st.rows[0].tournamentPoints, null);

// Lukket runde: kun spillere med score tæller
st = S.roundStandings(players.slice(0, 3), course, tie, 0, 100, true);
assert.strictEqual(st.complete, true);
assert.strictEqual(st.participants, 2);
assert.deepStrictEqual(st.rows.map(r => r.tournamentPoints), [4, 1]);

// Samlet stilling
const r0 = S.roundStandings(players, course, scores, 0, 100, false);
const r1 = S.roundStandings(players, course, {a: par, b: par, c: par, d: par}, 1, 100, false);
const r2 = S.roundStandings(players, course, {}, 2, 100, false);
const overall = S.overallStandings(players, [r0, r1, r2]);
// r1: Dorte 30 hcp 66, Bent 50, Anna 46, Carl 41 -> 6,3,2,1
assert.deepStrictEqual(overall.map(r => [r.name, r.points]), [["Bent", 8], ["Dorte", 6], ["Anna", 4], ["Carl", 2]]);
console.log("js ok");
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node er ikke installeret")
def test_js_beregninger(tmp_path):
    script = tmp_path / "t.js"
    script.write_text(JS_TEST, encoding="utf-8")
    res = subprocess.run(
        ["node", str(script), str(ROD / "golf" / "static" / "scoring.js")], capture_output=True, text=True
    )
    assert res.returncode == 0, res.stderr
    assert "js ok" in res.stdout
