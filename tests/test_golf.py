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
    assert st["settings"]["name"] == "SlamChamp 2026"
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
    # Deltagerlisten ligger klar fra start; ingen har bekræftet endnu
    assert len(st["players"]) == 20
    erik = next(p for p in st["players"] if p["name"] == "Erik Jul Nielsen")
    assert erik["dgu"] == "95-20180097" and erik["hcp"] == 17.5 and erik["hcpByRound"] == {} and erik["carry"] == 46
    assert next(p for p in st["players"] if p["name"] == "Claus Ladevig")["carry"] == 64
    assert sum(p["carry"] for p in st["players"]) == 662
    assert st["pinRequired"] is True
    assert client.get("/api/state", params={"since": st["version"]}).json()["unchanged"] is True


def test_tilmeld_bekraeft_score_og_persistens(client, golf):
    r = client.post("/api/players", json={"name": "  Erik   Nielsen ", "hcp": 12.44, "dgu": "27-1"})
    assert r.status_code == 201
    p = r.json()["player"]
    assert p["name"] == "Erik Nielsen" and p["hcp"] == 12.4 and p["dgu"] == "27-1" and p["hcpByRound"] == {}
    assert p["tee"] == ""
    assert client.post("/api/players", json={"name": "Lise", "hcp": 30, "tee": "49"}).json()["player"]["tee"] == "49"

    assert client.post("/api/players", json={"name": "erik nielsen", "hcp": 5}).status_code == 409
    assert client.post("/api/players", json={"name": "X", "hcp": 60}).status_code == 422

    # Uden bekræftelse til runden kan der ikke tastes
    assert client.put(f"/api/scores/0/{p['id']}/1", json={"strokes": 5}).status_code == 409
    r = client.put(f"/api/players/{p['id']}/confirm/0", json={"hcp": 12.6, "tee": "56"})
    assert r.status_code == 200 and r.json()["player"]["hcpByRound"] == {"0": 12.6} and r.json()["player"]["hcp"] == 12.6
    assert client.put(f"/api/players/{p['id']}/confirm/3", json={"hcp": 12.6}).status_code == 404
    # Runde 1 er stadig ubekræftet
    assert client.put(f"/api/scores/1/{p['id']}/1", json={"strokes": 5}).status_code == 409

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

    # Ret spiller (navn, tee, DGU-nr); indekset pr. runde rettes via confirm
    r = client.put(f"/api/players/{p['id']}", json={"hcp": 11.2, "tee": "61", "dgu": "27-2"})
    assert r.json()["player"]["hcp"] == 11.2 and r.json()["player"]["tee"] == "61" and r.json()["player"]["dgu"] == "27-2"
    assert r.json()["player"]["hcpByRound"] == {"0": 12.6}

    # Uden scorer kan bekræftelsen ændres og trækkes tilbage frit
    assert client.put(f"/api/players/{p['id']}/confirm/0", json={"hcp": 12.0}).status_code == 200
    assert client.delete(f"/api/players/{p['id']}/confirm/0").status_code == 200
    assert client.get("/api/state").json()["players"][-2]["hcpByRound"] == {}

    # Med scorer på runden kræver en ændring af indekset PIN, og tilbagetrækning sletter scorerne
    client.put(f"/api/players/{p['id']}/confirm/0", json={"hcp": 12.0})
    client.put(f"/api/scores/0/{p['id']}/1", json={"strokes": 4})
    assert client.put(f"/api/players/{p['id']}/confirm/0", json={"hcp": 13.0}).status_code == 401
    assert client.put(f"/api/players/{p['id']}/confirm/0", json={"hcp": 12.0}).status_code == 200  # uændret er ok
    assert client.put(f"/api/players/{p['id']}/confirm/0", json={"hcp": 13.0}, headers={"X-Golf-Pin": "1234"}).status_code == 200
    assert client.delete(f"/api/players/{p['id']}/confirm/0").status_code == 401
    assert client.delete(f"/api/players/{p['id']}/confirm/0", headers={"X-Golf-Pin": "1234"}).status_code == 200
    st = client.get("/api/state").json()
    assert p["id"] not in st["scores"]["0"]

    # Data ligger på disk og overlever en genstart
    data = json.loads((golf.DATA_FIL).read_text(encoding="utf-8"))
    assert any(q["name"] == "Erik Nielsen" for q in data["players"])
    nyt = golf.Lager(golf.DATA_FIL)
    assert next(q for q in nyt.state["players"] if q["name"] == "Erik Nielsen")["hcp"] == 13.0


def test_gammelt_format_migreres_og_deltagerliste_laegges_ind(golf):
    gammel = {
        "version": 5,
        "settings": {"name": "Test", "allowance": 100, "rounds": [{"date": "2026-09-18", "label": "Fredag", "course": "X", "tee": "Gul", "cr": 71.0, "slope": 120, "par": [4] * 18, "si": list(range(1, 19)), "closed": False}]},
        "players": [{"id": "p1", "name": "Erik Jul Nielsen", "hcp": 17.0, "absent": [False, True, False]}],
        "scores": {"0": {"p1": [4] * 18}},
    }
    golf.DATA_FIL.parent.mkdir(parents=True, exist_ok=True)
    golf.DATA_FIL.write_text(json.dumps(gammel), encoding="utf-8")
    st = golf.Lager(golf.DATA_FIL).state
    navne = [p["name"] for p in st["players"]]
    assert navne.count("Erik Jul Nielsen") == 1 and len(st["players"]) == 20  # kendt navn genbruges, 19 tilføjes
    erik = st["players"][0]
    assert erik["id"] == "p1" and "absent" not in erik and erik["hcpByRound"] == {} and erik["dgu"] == ""
    assert erik["carry"] == 46  # medbragte point slås op på navnet
    assert st["settings"]["rounds"][0]["tees"] == [{"name": "Gul", "cr": 71.0, "slope": 120}]
    assert st["seeded"] is True
    assert st["settings"]["name"] == "Test"  # et egentligt navn rører migrationen ikke


def test_pin_beskytter_farlige_handlinger(client):
    p = client.post("/api/players", json={"name": "Anna", "hcp": 20}).json()["player"]
    client.put(f"/api/players/{p['id']}/confirm/0", json={"hcp": 20})
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
    assert all(q["id"] != p["id"] for q in st["players"]) and st["scores"]["0"] == {}

    # Medbragte point kræver PIN
    erik0 = next(q for q in st["players"] if q["name"] == "Erik Jul Nielsen")
    assert client.put(f"/api/players/{erik0['id']}/carry", json={"carry": 50}).status_code == 401
    assert client.put(f"/api/players/{erik0['id']}/carry", json={"carry": 50}, headers={"X-Golf-Pin": "1234"}).json()["player"]["carry"] == 50
    assert client.put(f"/api/players/{erik0['id']}/carry", json={"carry": -1}, headers={"X-Golf-Pin": "1234"}).status_code == 422

    # Nulstil: scorer og bekræftelser væk, deltagerlisten tilbage
    erik = next(q for q in st["players"] if q["name"] == "Erik Jul Nielsen")
    client.put(f"/api/players/{erik['id']}/confirm/1", json={"hcp": 17.0})
    client.put(f"/api/scores/1/{erik['id']}/1", json={"strokes": 4})
    assert client.post("/api/reset").status_code == 401
    assert client.post("/api/reset", headers={"X-Golf-Pin": "1234"}).status_code == 200
    st = client.get("/api/state").json()
    assert len(st["players"]) == 20 and all(q["hcpByRound"] == {} for q in st["players"]) and st["scores"]["1"] == {}


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


def test_navn_laases_til_telefon(client, golf):
    st = client.get("/api/state").json()
    p = next(q for q in st["players"] if q["name"] == "Erik Jul Nielsen")
    assert p["locked"] is False and "device" not in p
    A = {"X-Golf-Device": "tlf-a"}
    B = {"X-Golf-Device": "tlf-b"}

    # Første bekræftelse låser navnet til telefon A
    r = client.put(f"/api/players/{p['id']}/confirm/0", json={"hcp": 17.5}, headers=A)
    assert r.status_code == 200 and "device" not in r.json()["player"]
    mig = next(q for q in client.get("/api/state", headers=A).json()["players"] if q["id"] == p["id"])
    assert mig["locked"] is True and mig["mine"] is True
    andre = next(q for q in client.get("/api/state", headers=B).json()["players"] if q["id"] == p["id"])
    assert andre["locked"] is True and andre["mine"] is False

    # Telefon B afvises, telefon A virker, PIN går igennem fra enhver telefon
    assert client.put(f"/api/scores/0/{p['id']}/1", json={"strokes": 5}, headers=B).status_code == 403
    assert client.put(f"/api/players/{p['id']}/confirm/0", json={"hcp": 17.5}, headers=B).status_code == 403
    assert client.put(f"/api/players/{p['id']}", json={"tee": "49"}, headers=B).status_code == 403
    assert client.delete(f"/api/players/{p['id']}/confirm/0", headers=B).status_code == 403
    assert client.put(f"/api/scores/0/{p['id']}/1", json={"strokes": 5}, headers=A).status_code == 200
    assert client.put(f"/api/scores/0/{p['id']}/2", json={"strokes": 5}, headers={**B, "X-Golf-Pin": "1234"}).status_code == 200

    # Frigiv kræver PIN; derefter kan telefon B overtage, og A er lukket ude
    assert client.delete(f"/api/players/{p['id']}/device").status_code == 401
    assert client.delete(f"/api/players/{p['id']}/device", headers={"X-Golf-Pin": "1234"}).status_code == 200
    assert client.put(f"/api/players/{p['id']}/confirm/0", json={"hcp": 17.5}, headers=B).status_code == 200
    assert client.put(f"/api/scores/0/{p['id']}/3", json={"strokes": 5}, headers=A).status_code == 403
    assert client.put(f"/api/scores/0/{p['id']}/3", json={"strokes": 5}, headers=B).status_code == 200

    # En ny spiller låses til den telefon, der opretter den
    ny = client.post("/api/players", json={"name": "Ny Spiller", "hcp": 20}, headers=A).json()["player"]
    assert "device" not in ny
    assert client.put(f"/api/players/{ny['id']}/confirm/0", json={"hcp": 20}, headers=B).status_code == 403
    assert client.put(f"/api/players/{ny['id']}/confirm/0", json={"hcp": 20}, headers=A).status_code == 200


def test_sikkerhedskopi_pr_time(client, golf):
    client.post("/api/players", json={"name": "Backup Test", "hcp": 20})
    filer = sorted(golf.BACKUP_DIR.glob("golf-*.json"))
    assert len(filer) == 1 and "Backup Test" in filer[0].read_text(encoding="utf-8")
    client.post("/api/players", json={"name": "Backup Test 2", "hcp": 20})
    assert len(list(golf.BACKUP_DIR.glob("golf-*.json"))) == 1  # samme time: kopien overskrives


def test_faerdig_runde_fryses_efter_et_kvarter(client, golf, monkeypatch):
    st = client.get("/api/state").json()
    a, b, c = st["players"][:3]
    for p in (a, b):
        client.put(f"/api/players/{p['id']}/confirm/0", json={"hcp": p["hcp"]})
        for h in range(1, 19):
            assert client.put(f"/api/scores/0/{p['id']}/{h}", json={"strokes": 4}).status_code == 200
    rd = client.get("/api/state").json()["settings"]["rounds"][0]
    assert rd["completedAt"] is not None

    # Inden for kvarteret kan der stadig rettes uden PIN
    assert client.put(f"/api/scores/0/{a['id']}/18", json={"strokes": 5}).status_code == 200

    # Et kvarter senere er runden låst
    rigtig_tid = golf.time.time
    monkeypatch.setattr(golf.time, "time", lambda: rigtig_tid() + golf.FRYS_EFTER_SEK + 1)
    assert client.put(f"/api/scores/0/{a['id']}/18", json={"strokes": 4}).status_code == 409
    assert client.put(f"/api/players/{c['id']}/confirm/0", json={"hcp": c["hcp"]}).status_code == 409
    assert client.delete(f"/api/players/{a['id']}/confirm/0").status_code == 409
    # PIN går igennem; fjernes en score, er runden ikke længere færdig, og låsen forsvinder
    assert client.put(f"/api/scores/0/{a['id']}/18", json={"strokes": 4}, headers={"X-Golf-Pin": "1234"}).status_code == 200
    assert client.put(f"/api/scores/0/{a['id']}/18", json={"strokes": None}, headers={"X-Golf-Pin": "1234"}).status_code == 200
    assert client.get("/api/state").json()["settings"]["rounds"][0]["completedAt"] is None
    assert client.put(f"/api/scores/0/{a['id']}/18", json={"strokes": 4}).status_code == 200
    assert client.get("/api/state").json()["settings"]["rounds"][0]["completedAt"] is not None
    # Nulstil rydder også låsen
    client.post("/api/reset", headers={"X-Golf-Pin": "1234"})
    assert client.get("/api/state").json()["settings"]["rounds"][0]["completedAt"] is None


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

// Runde: kun spillere med bekræftet hcp til runden deltager; lighed afgøres af laveste hcp;
// runden er først færdig når alle deltagere har 18 huller
const all3 = (h) => ({"0": h, "1": h, "2": h});
const players = [
  {id: "a", name: "Anna", hcp: 10.0, hcpByRound: all3(10.0), carry: 0},
  {id: "b", name: "Bent", hcp: 14.0, hcpByRound: all3(14.0), carry: 0},
  {id: "c", name: "Carl", hcp: 5.0, hcpByRound: all3(5.0), carry: 0},
  {id: "d", name: "Dorte", hcp: 30.0, hcpByRound: {"1": 30.0, "2": 30.0}, carry: 0},  // ikke bekræftet til runde 0
  {id: "e", name: "Ebbe", hcp: 12.0, hcpByRound: {}, carry: 0},                       // på listen, deltager aldrig
];
// Rundens bekræftede hcp bruges, ikke det senest kendte
assert.strictEqual(S.scorecard(S.playerForRound({id: "x", name: "X", hcp: 20.0, hcpByRound: {"0": 12.4}}, 0), course, null, 100).playingHcp, 12);
assert.strictEqual(S.playerForRound({id: "x", name: "X", hcp: 20.0, hcpByRound: {}}, 0), null);
assert.strictEqual(S.hcpForRound({id: "x", name: "X", hcp: 20.0}, 0), null);
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
// r1: Dorte 30 hcp 66, Bent 50, Anna 46, Carl 41 -> 6,3,2,1. Ebbe deltog aldrig: 0 og 0.
assert.deepStrictEqual(overall.map(r => [r.name, r.points]), [["Bent", 8], ["Dorte", 6], ["Anna", 4], ["Carl", 2], ["Ebbe", 0]]);
const ebbe = overall.find(r => r.name === "Ebbe");
assert.deepStrictEqual(ebbe.perRound.map(pr => [pr.participated, pr.points, pr.stableford]), [[false, 0, 0], [false, 0, 0], [false, 0, 0]]);
const dorte = overall.find(r => r.name === "Dorte");
assert.deepStrictEqual(dorte.perRound.map(pr => [pr.participated, pr.points]), [[false, 0], [true, 6], [true, null]]);
// Medbragte ranglistepoint lægges til og afgør rækkefølgen: Ebbe har 30 med og deltager ikke,
// Carl har 5 med (2 optjent -> 7), Bent 0 med (8 optjent)
const carried = players.map(p => ({...p, carry: p.name === "Ebbe" ? 30 : p.name === "Carl" ? 5 : 0}));
const ov2 = S.overallStandings(carried, [r0, r1, r2]);
assert.deepStrictEqual(ov2.map(r => [r.name, r.carry, r.earned, r.points]), [["Ebbe", 30, 0, 30], ["Bent", 0, 8, 8], ["Carl", 5, 2, 7], ["Dorte", 0, 6, 6], ["Anna", 0, 4, 4]]);
// 18 deltagere: 20, 17, 16, ..., 1
const eighteen = Array.from({length: 18}, (_, i) => ({id: "p" + i, name: "P" + String(i).padStart(2, "0"), hcp: 10 + i, hcpByRound: {"0": 10 + i}}));
const sc18 = Object.fromEntries(eighteen.map((p, i) => [p.id, par.map((x, h) => h < i ? x + 1 : x)]));  // P00 bedst
const st18 = S.roundStandings(eighteen, course, sc18, 0, 100, false);
assert.deepStrictEqual(st18.rows.map(r => r.tournamentPoints), [20, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]);
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
