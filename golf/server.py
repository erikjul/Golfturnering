"""
Golfturnering – lille webapp til løbende Stableford-stilling over tre runder.

Alle med adressen kan tilmelde sig, taste slag hul for hul og følge ranglisten.
Alt gemmes i én JSON-fil (GOLF_DATA_DIR/golf.json). Selve regnearbejdet (Stableford,
spillehandicap og turneringspoint) sker i browseren, se static/scoring.js.

Kør lokalt:  python -m uvicorn golf.server:app --host 0.0.0.0 --port 8010
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

HER = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("GOLF_DATA_DIR", HER / "data"))
DATA_FIL = DATA_DIR / "golf.json"
BACKUP_DIR = DATA_DIR / "backup"
BACKUP_ANTAL = 48  # én kopi pr. time, de seneste to døgn
PIN = os.environ.get("GOLF_PIN", "").strip()
FRYS_EFTER_SEK = 15 * 60  # rettelser uden PIN tillades et kvarter efter, at runden er færdig

ANTAL_RUNDER = 3

# Standardbane: Samsø Golfklub, 18 hullers bane. Par, handicapnøgle (index) og længder pr. hul er
# fra klubbens baneguide; CR 70,8 og slope 131 for tee 56 (herrer) er fra DGU's course handicap
# table, ligesom CR 66,9 og slope 122 for tee 49 (herrer). Tee 61 (herrer: CR 73,2, slope 137) kan
# tilføjes under Opsætning; længderne udfyldes så automatisk.
STANDARD_COURSE = "Samsø Golfklub"
STANDARD_PAR = [4, 4, 5, 3, 4, 4, 4, 3, 5, 5, 3, 4, 4, 5, 3, 4, 4, 4]
STANDARD_SI = [13, 9, 3, 15, 1, 11, 7, 17, 5, 2, 16, 6, 12, 8, 18, 10, 4, 14]
SAMSOE_LAENGDER = {
    "49": [265, 310, 395, 120, 305, 280, 275, 125, 385, 385, 115, 280, 275, 390, 120, 300, 315, 245],
    "56": [320, 350, 445, 140, 345, 320, 320, 150, 435, 435, 130, 325, 330, 435, 145, 345, 360, 285],
    "61": [336, 380, 485, 173, 345, 346, 320, 172, 438, 452, 149, 359, 330, 512, 172, 416, 370, 340],
}
STANDARD_TEES = [
    {"name": "56", "cr": 70.8, "slope": 131, "lengths": list(SAMSOE_LAENGDER["56"])},
    {"name": "49", "cr": 66.9, "slope": 122, "lengths": list(SAMSOE_LAENGDER["49"])},
]
STANDARD_REGLER = """## Lokalregler (Samsø Golfklub)
Banemarkeringer: hvide = out of bounds, røde = strafområde, blå = areal under reparation, grøn top = spilleforbud.
1. Out of bounds defineres som linjen mellem de banenære punkter af hvide pæle i jordhøjde.
2. Alle veje og stier på banen, også kunstigt overfladebelagte, behandles som integrerede genstande.
3. Alle pæle på banen behandles som ikke-flytbare forhindringer: lempelse uden straf efter Regel 16.1. Lempelse må ikke tages efter Regel 15.2.
4. Provisorisk bold ved bold i strafområde på hul 5, 7, 11, 14 og 17: Ved du ikke, om bolden er i strafområdet, kan du spille en provisorisk bold efter Regel 18.3. Findes den oprindelige bold i strafområdet inden for 3 minutter, vælger du enten at spille den, som den ligger (den provisoriske bold opgives, og slag med den tæller ikke), eller at fortsætte med den provisoriske bold. Findes den ikke, eller er det så godt som sikkert, at den er i strafområdet, er den provisoriske bold i spil. Straf for overtrædelse: den generelle straf.
5. Elhegn og installationer omkring fårefolde er ikke-flytbare forhindringer. Generer de sving eller stance, kan der tages lempelse uden straf efter Regel 16.1a.
6. Fåreindhegninger er områder med spilleforbud (unormalt baneforhold). Lempelse uden straf skal tages efter Regel 16.1f. Straf for overtrædelse: hulspil tab af hul, slagspil 2 strafslag.
## Ordensregler
Afstandspæle i siden af fairway: gule 150 m, røde 100 m, blå 50 m til forkant af green.
Bolde slået out of bounds må ikke afhentes på nabojord.
Hul 1 og 18: slå ikke ud, før forangående bold er på green.
Hul 13: slå ikke ud, før du har hørt klokken.
Hul 4 og 8: slå ikke ud, hvis der er færdsel på vejen.
Hul 7, tee 56: slå ikke ud, hvis der er spillere på hul 18 på tee 61 eller 56.
Max 4-bold. En runde bør højst tage 4 timer og 30 minutter. Luk hurtigere spillere igennem.
Ret nedslagsmærker på green, læg tørv på plads, og læg hele riven ned i bunkeren.
Drikkevand foran hul 1 og 10. Toiletter ved hul 10 og 13. Hjertestarter ved klubhusets dør. Shoppen: 86 59 22 18."""
RUNDER = [
    ("2026-09-18", "Fredag"),
    ("2026-09-19", "Lørdag"),
    ("2026-09-20", "Søndag"),
]

# Deltagerlisten (navn, DGU-nr, HCP-index pr. 15/8 2026, ranglistepoint før turneringen).
# Indekset er kun en startværdi: spilleren bekræfter sit aktuelle indeks inden hver runde, og først
# da tæller vedkommende med på runden. Ranglistepointene er stillingen efter Horsens 15/8; rundernes
# point lægges til løbende.
STANDARD_SPILLERE = [
    ("Claus Ladevig", "27-4183", 17.3, 64),
    ("Lars Tørslev", "27-498", 10.0, 59),
    ("Henrik Sørensen", "27-47", 22.4, 55),
    ("Søren Palmelund", "27-4666", 10.8, 51),
    ("Lars Scheuer", "95-20200053", 16.4, 51),
    ("Dennis Nymark", "89-4100", 5.9, 49),
    ("Erik Jul Nielsen", "95-20180097", 17.5, 46),
    ("Michael Søndergaard", "27-4809", 31.9, 43),
    ("Tony Juul Andersen", "184-2033", 17.8, 41),
    ("Finn Maach", "27-6353", 22.3, 36),
    ("Christian Alsing", "44-1097", 8.3, 31),
    ("Henrik Jensen", "96-5504", 36.9, 23),
    ("Jess Bæk", "117-1047", 11.6, 23),
    ("Claus Krøyer", "95-20190302", 26.4, 17),
    ("Lars Feldskou", "95-20200434", 21.0, 16),
    ("Henrik Laursen", "153-215", 25.4, 15),
    ("Rico Soos", "95-25186", 14.4, 13),
    ("Jon Jarlgaard", "27-4560", 20.2, 13),
    ("Thomas Pedersen", "86-161", 5.4, 10),
    ("Kalle Nielsen", "27-2016", 22.3, 6),
]


def ny_spiller(navn: str, hcp: float, dgu: str = "", tee: str = "", carry: int = 0) -> dict[str, Any]:
    return {
        "id": "p" + secrets.token_hex(4),
        "name": navn,
        "dgu": dgu,
        "hcp": hcp,  # senest kendte HCP-index (startværdi for næste bekræftelse)
        "hcpByRound": {},  # runde -> bekræftet HCP-index; kun bekræftede spillere deltager på runden
        "carry": carry,  # ranglistepoint medbragt fra tidligere runder
        "device": "",  # den telefon (tilfældigt id), der ejer navnet; tom = ikke låst
        "tee": tee,
        "created": time.time(),
    }


def standard_spillere() -> list[dict[str, Any]]:
    return [ny_spiller(n, h, d, carry=c) for n, d, h, c in STANDARD_SPILLERE]


def standard_state() -> dict[str, Any]:
    return {
        "version": 1,
        "settings": {
            "name": "SlamChamp 2026",
            "allowance": 100,
            "rules": STANDARD_REGLER,
            "rounds": [
                {
                    "date": d,
                    "label": lab,
                    "course": STANDARD_COURSE,
                    "tees": [dict(t) for t in STANDARD_TEES],
                    "par": list(STANDARD_PAR),
                    "si": list(STANDARD_SI),
                    "closed": False,
                    "completedAt": None,  # tidspunkt hvor alle deltagere havde 18 huller
                }
                for d, lab in RUNDER
            ],
        },
        "players": standard_spillere(),
        "seeded": True,
        "scores": {str(i): {} for i in range(ANTAL_RUNDER)},
    }


class Lager:
    """Hele turneringens tilstand i hukommelsen, skrevet atomisk til disk ved hver ændring."""

    def __init__(self, fil: Path):
        self.fil = fil
        self.lock = threading.Lock()
        self.state = self._laes()

    def _laes(self) -> dict[str, Any]:
        if self.fil.exists():
            with open(self.fil, encoding="utf-8") as f:
                state = json.load(f)
            grund = standard_state()
            # Manglende felter (fx efter en opdatering af programmet) udfyldes med standardværdier
            state.setdefault("version", 1)
            state.setdefault("players", [])
            state.setdefault("scores", grund["scores"])
            for i in range(ANTAL_RUNDER):
                state["scores"].setdefault(str(i), {})
            s = state.setdefault("settings", grund["settings"])
            s.setdefault("name", grund["settings"]["name"])
            if s["name"] == "Golfturnering 2026":  # det gamle standardnavn
                s["name"] = "SlamChamp 2026"
            s.setdefault("allowance", 100)
            s.setdefault("rules", STANDARD_REGLER)
            runder = s.setdefault("rounds", [])
            while len(runder) < ANTAL_RUNDER:
                runder.append(grund["settings"]["rounds"][len(runder)])
            for r, g in zip(runder, grund["settings"]["rounds"]):
                if "tees" not in r:  # ældre format med ét tee pr. runde
                    r["tees"] = [{"name": r.pop("tee", "") or "Standard", "cr": r.pop("cr", 72.0), "slope": r.pop("slope", 113)}]
                for k, v in g.items():
                    r.setdefault(k, v)
            medbragt = {n.casefold(): c for n, _d, _h, c in STANDARD_SPILLERE}
            for p in state["players"]:
                p.setdefault("tee", "")
                p.setdefault("dgu", "")
                p.setdefault("hcpByRound", {})
                p.setdefault("carry", medbragt.get(p["name"].casefold(), 0))
                p.setdefault("device", "")
                p.pop("absent", None)
            for r in runder:
                r.setdefault("completedAt", None)
            if not state.get("seeded"):  # deltagerlisten lægges ind én gang; kendte navne genbruges
                kendte = {p["name"].casefold() for p in state["players"]}
                state["players"] += [p for p in standard_spillere() if p["name"].casefold() not in kendte]
                state["seeded"] = True
            return state
        return standard_state()

    def gem(self) -> None:
        self.state["version"] += 1
        self.fil.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.fil.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.fil)
        self._sikkerhedskopi()

    def _sikkerhedskopi(self) -> None:
        """Én kopi pr. time i backup-mappen (overskrives inden for timen); de seneste 48 beholdes."""
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            navn = BACKUP_DIR / time.strftime("golf-%Y%m%d-%H.json")
            tmp = navn.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=1)
            os.replace(tmp, navn)
            for gammel in sorted(BACKUP_DIR.glob("golf-*.json"))[:-BACKUP_ANTAL]:
                gammel.unlink()
        except OSError:
            pass  # en fejlende kopi må aldrig stoppe selve gemningen


lager = Lager(DATA_FIL)
app = FastAPI(title="Golfturnering", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HER / "static"), name="static")


# ---------- hjælpere ----------


def kraev_pin(pin: str | None) -> None:
    if PIN and not (pin and secrets.compare_digest(pin, PIN)):
        raise HTTPException(401, "Forkert eller manglende PIN")


def find_spiller(pid: str) -> dict[str, Any]:
    for p in lager.state["players"]:
        if p["id"] == pid:
            return p
    raise HTTPException(404, "Spilleren findes ikke")


def tjek_runde(r: int) -> None:
    if not 0 <= r < ANTAL_RUNDER:
        raise HTTPException(404, "Runden findes ikke")


def offentlig(p: dict[str, Any]) -> dict[str, Any]:
    """Spilleren uden telefonens id (det bliver aldrig sendt ud)."""
    return {k: v for k, v in p.items() if k != "device"}


def har_pin(pin: str | None) -> bool:
    return bool(PIN) and bool(pin) and secrets.compare_digest(pin, PIN)


def kraev_ejer(p: dict[str, Any], device: str | None, pin: str | None) -> None:
    """Navnet må kun bruges fra den telefon, der ejer det. PIN (arrangøren) går altid igennem."""
    if har_pin(pin):
        return
    if p.get("device") and p["device"] != (device or ""):
        raise HTTPException(403, f"{p['name']} bruges fra en anden telefon. Bed arrangøren frigive navnet.")


def bind_device(p: dict[str, Any], device: str | None) -> None:
    if device and not p.get("device"):
        p["device"] = device[:64]


def runde_faerdig(r: int) -> bool:
    """Alle, der har bekræftet til runden, har 18 huller (og mindst én deltager)."""
    scores = lager.state["scores"][str(r)]
    deltagere = [p for p in lager.state["players"] if str(r) in p["hcpByRound"]]
    return bool(deltagere) and all(
        len(scores.get(p["id"], [])) == 18 and all(x is not None for x in scores[p["id"]]) for p in deltagere
    )


def runde_frosset(r: int) -> bool:
    """Færdig i mere end et kvarter: rettelser kræver PIN."""
    rd = lager.state["settings"]["rounds"][r]
    return bool(rd.get("completedAt")) and time.time() - rd["completedAt"] > FRYS_EFTER_SEK and runde_faerdig(r)


def opdater_faerdig(r: int) -> None:
    rd = lager.state["settings"]["rounds"][r]
    if runde_faerdig(r):
        if not rd.get("completedAt"):
            rd["completedAt"] = time.time()
    else:
        rd["completedAt"] = None


def kraev_ikke_frosset(r: int, pin: str | None) -> None:
    if runde_frosset(r) and not har_pin(pin):
        raise HTTPException(409, "Runden er færdig og låst. Rettelser kræver arrangørens PIN.")


def rens_navn(navn: str) -> str:
    navn = re.sub(r"\s+", " ", navn or "").strip()
    if not 1 <= len(navn) <= 60:
        raise HTTPException(422, "Navnet skal være mellem 1 og 60 tegn")
    return navn


def tjek_hcp(hcp: float) -> float:
    if not -10 <= hcp <= 54:
        raise HTTPException(422, "HCP-index skal ligge mellem -10 og 54")
    return round(float(hcp), 1)


# ---------- modeller ----------


class NySpiller(BaseModel):
    name: str
    hcp: float
    tee: str = ""
    dgu: str = ""


class RetSpiller(BaseModel):
    name: str | None = None
    hcp: float | None = None
    tee: str | None = None
    dgu: str | None = None


class Bekraeftelse(BaseModel):
    hcp: float
    tee: str | None = None


class Medbragt(BaseModel):
    carry: int = Field(ge=0, le=10000)


class Slag(BaseModel):
    # None = ryd hullet, 0 = streget (hullet opgivet), ellers antal slag
    strokes: int | None = Field(default=None, ge=0, le=30)


class Tee(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    cr: float = Field(ge=40, le=90)
    slope: int = Field(ge=55, le=155)
    lengths: list[int] | None = None  # meter pr. hul, valgfrit


class Runde(BaseModel):
    date: str
    label: str
    course: str = ""
    tees: list[Tee] = Field(min_length=1, max_length=8)
    par: list[int]
    si: list[int]
    closed: bool = False
    completedAt: float | None = None  # sættes kun af serveren; værdien fra klienten ignoreres


class Opsaetning(BaseModel):
    name: str
    allowance: int = Field(ge=50, le=100)
    rounds: list[Runde]
    rules: str = Field(default="", max_length=20000)


# ---------- sider ----------


@app.get("/", include_in_schema=False)
def forside() -> FileResponse:
    return FileResponse(HER / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/sundhed")
def sundhed() -> dict[str, str]:
    return {"status": "ok"}


# ---------- api ----------


@app.get("/api/state")
def hent_state(since: int = 0, x_golf_device: str | None = Header(default=None)) -> JSONResponse:
    with lager.lock:
        if since and since == lager.state["version"]:
            return JSONResponse({"unchanged": True, "version": since, "pinRequired": bool(PIN)})
        body = json.loads(json.dumps(lager.state))
    # Telefonens id sendes aldrig ud; klienten får kun at vide, om navnet er låst, og om det er dens eget
    for p in body["players"]:
        dev = p.pop("device", "")
        p["locked"] = bool(dev)
        p["mine"] = bool(dev) and dev == (x_golf_device or "")
    body["pinRequired"] = bool(PIN)
    body["serverTime"] = time.time()
    body["freezeAfter"] = FRYS_EFTER_SEK
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@app.post("/api/players", status_code=201)
def opret_spiller(data: NySpiller, x_golf_device: str | None = Header(default=None)) -> dict[str, Any]:
    navn = rens_navn(data.name)
    hcp = tjek_hcp(data.hcp)
    with lager.lock:
        if any(p["name"].casefold() == navn.casefold() for p in lager.state["players"]):
            raise HTTPException(409, "Der er allerede en spiller med det navn")
        spiller = ny_spiller(navn, hcp, data.dgu.strip()[:20], data.tee.strip()[:30], carry=0)
        bind_device(spiller, x_golf_device)
        lager.state["players"].append(spiller)
        lager.gem()
        return {"player": offentlig(spiller), "version": lager.state["version"]}


@app.put("/api/players/{pid}")
def ret_spiller(pid: str, data: RetSpiller, x_golf_device: str | None = Header(default=None), x_golf_pin: str | None = Header(default=None)) -> dict[str, Any]:
    with lager.lock:
        p = find_spiller(pid)
        kraev_ejer(p, x_golf_device, x_golf_pin)
        if data.name is not None:
            navn = rens_navn(data.name)
            if any(q["id"] != pid and q["name"].casefold() == navn.casefold() for q in lager.state["players"]):
                raise HTTPException(409, "Der er allerede en spiller med det navn")
            p["name"] = navn
        if data.hcp is not None:
            p["hcp"] = tjek_hcp(data.hcp)
        if data.tee is not None:
            p["tee"] = data.tee.strip()[:30]
        if data.dgu is not None:
            p["dgu"] = data.dgu.strip()[:20]
        lager.gem()
        return {"player": offentlig(p), "version": lager.state["version"]}


@app.put("/api/players/{pid}/confirm/{r}")
def bekraeft(pid: str, r: int, data: Bekraeftelse, x_golf_pin: str | None = Header(default=None), x_golf_device: str | None = Header(default=None)) -> dict[str, Any]:
    """Spilleren bekræfter sit aktuelle HCP-index (og tee) til runden og deltager dermed på den.
    Første bekræftelse låser navnet til telefonen. Er der allerede tastet scorer på runden, kræver
    en ændring af indekset PIN."""
    tjek_runde(r)
    hcp = tjek_hcp(data.hcp)
    with lager.lock:
        p = find_spiller(pid)
        kraev_ejer(p, x_golf_device, x_golf_pin)
        if lager.state["settings"]["rounds"][r]["closed"]:
            raise HTTPException(409, "Runden er lukket")
        kraev_ikke_frosset(r, x_golf_pin)
        gammel = p["hcpByRound"].get(str(r))
        har_scorer = pid in lager.state["scores"][str(r)]
        if har_scorer and gammel is not None and gammel != hcp:
            kraev_pin(x_golf_pin)
            if not PIN:
                raise HTTPException(409, "Handicap kan ikke ændres, når der er tastet scorer på runden")
        p["hcpByRound"][str(r)] = hcp
        p["hcp"] = hcp
        if data.tee is not None:
            p["tee"] = data.tee.strip()[:30]
        if not har_pin(x_golf_pin):
            bind_device(p, x_golf_device)
        opdater_faerdig(r)
        lager.gem()
        return {"player": offentlig(p), "version": lager.state["version"]}


@app.delete("/api/players/{pid}/device")
def frigiv_navn(pid: str, x_golf_pin: str | None = Header(default=None)) -> dict[str, Any]:
    """Frigiver navnet, så det kan bruges fra en anden telefon. Kræver PIN."""
    kraev_pin(x_golf_pin)
    with lager.lock:
        p = find_spiller(pid)
        p["device"] = ""
        lager.gem()
        return {"ok": True, "version": lager.state["version"]}


@app.put("/api/players/{pid}/carry")
def ret_medbragt(pid: str, data: Medbragt, x_golf_pin: str | None = Header(default=None)) -> dict[str, Any]:
    """Retter de ranglistepoint, spilleren har med sig fra tidligere runder. Kræver PIN."""
    kraev_pin(x_golf_pin)
    with lager.lock:
        p = find_spiller(pid)
        p["carry"] = data.carry
        lager.gem()
        return {"player": offentlig(p), "version": lager.state["version"]}


@app.delete("/api/players/{pid}/confirm/{r}")
def fortryd_bekraeftelse(pid: str, r: int, x_golf_pin: str | None = Header(default=None), x_golf_device: str | None = Header(default=None)) -> dict[str, Any]:
    """Trækker deltagelsen på runden tilbage. Med scorer på runden kræves PIN, og scorerne slettes."""
    tjek_runde(r)
    with lager.lock:
        p = find_spiller(pid)
        kraev_ejer(p, x_golf_device, x_golf_pin)
        kraev_ikke_frosset(r, x_golf_pin)
        if pid in lager.state["scores"][str(r)]:
            kraev_pin(x_golf_pin)
            if not PIN:
                raise HTTPException(409, "Der er tastet scorer på runden")
            del lager.state["scores"][str(r)][pid]
        p["hcpByRound"].pop(str(r), None)
        opdater_faerdig(r)
        lager.gem()
        return {"player": offentlig(p), "version": lager.state["version"]}


@app.delete("/api/players/{pid}")
def slet_spiller(pid: str, x_golf_pin: str | None = Header(default=None)) -> dict[str, Any]:
    kraev_pin(x_golf_pin)
    with lager.lock:
        find_spiller(pid)
        lager.state["players"] = [p for p in lager.state["players"] if p["id"] != pid]
        for runde in lager.state["scores"].values():
            runde.pop(pid, None)
        for i in range(ANTAL_RUNDER):
            opdater_faerdig(i)
        lager.gem()
        return {"ok": True, "version": lager.state["version"]}


@app.put("/api/scores/{r}/{pid}/{hul}")
def gem_slag(r: int, pid: str, hul: int, data: Slag, x_golf_device: str | None = Header(default=None), x_golf_pin: str | None = Header(default=None)) -> dict[str, Any]:
    tjek_runde(r)
    if not 1 <= hul <= 18:
        raise HTTPException(404, "Hullet findes ikke")
    with lager.lock:
        p = find_spiller(pid)
        kraev_ejer(p, x_golf_device, x_golf_pin)
        if lager.state["settings"]["rounds"][r]["closed"]:
            raise HTTPException(409, "Runden er lukket, så der kan ikke tastes flere scorer")
        if str(r) not in p["hcpByRound"]:
            raise HTTPException(409, "Bekræft dit HCP-index til runden, før du taster scorer")
        kraev_ikke_frosset(r, x_golf_pin)
        kort = lager.state["scores"][str(r)].setdefault(pid, [None] * 18)
        kort[hul - 1] = data.strokes
        if all(s is None for s in kort):
            del lager.state["scores"][str(r)][pid]
        opdater_faerdig(r)
        lager.gem()
        return {"ok": True, "version": lager.state["version"]}


@app.put("/api/settings")
def gem_opsaetning(data: Opsaetning, x_golf_pin: str | None = Header(default=None)) -> dict[str, Any]:
    kraev_pin(x_golf_pin)
    if len(data.rounds) != ANTAL_RUNDER:
        raise HTTPException(422, f"Der skal være {ANTAL_RUNDER} runder")
    for rd in data.rounds:
        if len(rd.par) != 18 or any(not 3 <= p <= 6 for p in rd.par):
            raise HTTPException(422, "Par skal angives for 18 huller (3–6)")
        if sorted(rd.si) != list(range(1, 19)):
            raise HTTPException(422, "Handicapnøglerne skal være tallene 1–18, hver brugt én gang")
        navne = [t.name.strip().casefold() for t in rd.tees]
        if len(set(navne)) != len(navne):
            raise HTTPException(422, "To tees på samme runde kan ikke have samme navn")
        for t in rd.tees:
            if t.lengths is not None and (len(t.lengths) != 18 or any(not 0 <= x <= 999 for x in t.lengths)):
                raise HTTPException(422, f"Længder for tee {t.name} skal være 18 tal i meter")
    with lager.lock:
        gamle = lager.state["settings"]["rounds"]
        nye = [rd.model_dump() for rd in data.rounds]
        for ny, gammel in zip(nye, gamle):
            ny["completedAt"] = gammel.get("completedAt")
        lager.state["settings"] = {
            "name": rens_navn(data.name),
            "allowance": data.allowance,
            "rules": data.rules,
            "rounds": nye,
        }
        lager.gem()
        return {"ok": True, "version": lager.state["version"]}


@app.post("/api/rounds/{r}/closed")
def luk_runde(r: int, request: Request, x_golf_pin: str | None = Header(default=None)) -> dict[str, Any]:
    tjek_runde(r)
    kraev_pin(x_golf_pin)
    closed = request.query_params.get("value", "1") not in ("0", "false")
    with lager.lock:
        lager.state["settings"]["rounds"][r]["closed"] = closed
        lager.gem()
        return {"ok": True, "closed": closed, "version": lager.state["version"]}


@app.post("/api/reset")
def nulstil(x_golf_pin: str | None = Header(default=None)) -> dict[str, Any]:
    """Sletter alle scorer og bekræftelser og lægger deltagerlisten ind igen. Baneopsætningen
    beholdes. Kræver PIN, hvis en er sat."""
    kraev_pin(x_golf_pin)
    with lager.lock:
        lager.state["players"] = standard_spillere()
        lager.state["seeded"] = True
        lager.state["scores"] = {str(i): {} for i in range(ANTAL_RUNDER)}
        for rd in lager.state["settings"]["rounds"]:
            rd["closed"] = False
            rd["completedAt"] = None
        lager.gem()
        return {"ok": True, "version": lager.state["version"]}
