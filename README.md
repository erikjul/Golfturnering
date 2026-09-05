# Golfturnering – løbende Stableford-stilling

Lille webapp til en turnering over tre runder (fredag 18., lørdag 19. og søndag 20. september 2026).
Alle, der har adressen, kan åbne den på telefonen, tilmelde sig og taste slag hul for hul.

## Sådan virker den

* **Tilmelding:** navn og DGU-handicap (HCP-index), og valg af tee hvis runden har flere. Appen
  omregner til spillehandicap efter WHS: HCP-index × slope ÷ 113 + (course rating − par), ganget
  med handicaptildelingen (100 % som standard, 95 % kan vælges) og rundet til hele slag. Med 100 %
  giver det præcis de samme tal som klubbens konverteringstabel (testet mod DGU's tabel for
  Samsø Golfklub, tee 56 og 49, herrer). Slagene fordeles efter banens handicapnøgle.
* **Scorekort:** tryk på et hul og vælg antal slag på taltastaturet. Stablefordpointene regnes ud
  med det samme, og tastaturet springer selv videre til næste hul. *Streg* = hullet opgivet (0 point).
* **Stilling:** ranglisten for runden opdateres hvert par sekunder hos alle. Pile viser, hvem der er
  rykket op og ned siden sidst. Ved lige Stablefordpoint står den med laveste HCP-index øverst.
* **Runden er færdig,** når alle tilmeldte (som ikke er sat til *spiller ikke*) har tastet 18 huller.
  Så vises rundens vinder og turneringspointene: vinderen får *antal deltagere + 2*, nr. 2 får
  *antal deltagere − 1*, og så videre ned til 1 point til sidstepladsen. Med 18 deltagere får
  vinderen altså 20, nr. 2 får 17 og nr. 18 får 1.
* **Samlet:** turneringspoint lagt sammen over de tre runder. Ved lighed tæller flest
  Stablefordpoint i alt, derefter laveste HCP-index.
* **Banen:** huloversigt med par, handicapnøgle og længder pr. tee samt klubbens lokalregler og
  ordensregler (teksten kan rettes under Opsætning).
* **Opsætning (tandhjulet):** turneringens navn, bane, ét eller flere tees med course rating og
  slope, par og handicapnøgle pr. hul for hver runde (*Kopiér bane til alle runder* sparer tid),
  *Luk runden nu* hvis nogen aldrig får tastet færdig, og sletning af spillere. Sæt en PIN i `.env`
  (`GOLF_PIN`), så kun du kan gøre de ting – tilmelding og scoreindtastning kræver aldrig PIN.

Standardopsætningen er **Samsø Golfklub, 18 hullers bane** med par, handicapnøgle og længder pr. hul
fra klubbens baneguide og lokalreglerne fra samme. To tees for herrer er sat op fra klubbens
konverteringstabel: **tee 56 (course rating 70,8, slope 131)** og **tee 49 (course rating 66,9,
slope 122)**. Spillerne vælger tee ved tilmelding (tee 56 er forvalgt) og kan ændre det med *Ret*.
Skal nogen spille fra tee 61 (herrer: course rating 73,2, slope 137) eller fra dametees, tilføjer du
dem under Opsætning; længderne udfyldes automatisk. Husk *Kopiér bane til alle runder*.

| Hul | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Par | 4 | 4 | 5 | 3 | 4 | 4 | 4 | 3 | 5 | 5 | 3 | 4 | 4 | 5 | 3 | 4 | 4 | 4 |
| Nøgle | 13 | 9 | 3 | 15 | 1 | 11 | 7 | 17 | 5 | 2 | 16 | 6 | 12 | 8 | 18 | 10 | 4 | 14 |
| Tee 56 (m) | 320 | 350 | 445 | 140 | 345 | 320 | 320 | 150 | 435 | 435 | 130 | 325 | 330 | 435 | 145 | 345 | 360 | 285 |
| Tee 49 (m) | 265 | 310 | 395 | 120 | 305 | 280 | 275 | 125 | 385 | 385 | 115 | 280 | 275 | 390 | 120 | 300 | 315 | 245 |

## Prøv den på din egen pc

```bash
git clone https://github.com/erikjul/golfturnering.git
cd golfturnering
python3 -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn golf.server:app --host 0.0.0.0 --port 8010
```

Åbn <http://localhost:8010>. På Windows kan du i stedet dobbeltklikke på `start.bat`. Data
gemmes i `golf/data/golf.json`. Andre på samme wi-fi kan bruge `http://<din-ip>:8010`, men skal
spillerne kunne taste ude på banen, skal appen ligge på en server på internettet – se næste afsnit.

Åbner du `golf/static/index.html` direkte i en browser uden server, kører appen i prøveversion, hvor
alt kun gemmes i den browser. Det er fint til at kigge, men ikke til selve turneringen.

## Sæt den på en server (alle kan nå den fra telefonen)

Serveren deles med andre apps: én fælles Caddy fra repoet
[server-proxy](https://github.com/erikjul/server-proxy) sørger for HTTPS og sender trafikken videre
efter adresse. En lille server hos Hetzner (CX22, Ubuntu 24.04) er rigelig.

1. Opret serveren, log ind med `ssh root@<ip>`, og installér Docker:

   ```bash
   apt update && apt upgrade -y
   apt install -y ca-certificates curl git ufw
   curl -fsSL https://get.docker.com | sh
   ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
   ```

2. Sæt den fælles Caddy op (spring over, hvis den allerede kører på serveren). Uden domæne bruges
   serverens IP med bindestreger og et præfiks pr. app, fx `GOLF_DOMAENE=golf.65-108-1-2.sslip.io`:

   ```bash
   cd /opt
   git clone https://github.com/erikjul/server-proxy.git
   cd server-proxy
   cp .env.example .env && nano .env
   docker network create web
   docker compose up -d
   ```

3. Start golfappen:

   ```bash
   cd /opt
   git clone https://github.com/erikjul/golfturnering.git
   cd golfturnering
   cp .env.example .env && nano .env      # sæt GOLF_PIN
   docker compose up -d --build
   ```

   Efter et halvt minut svarer `https://<GOLF_DOMAENE>`. Send adressen til spillerne – de kan lægge
   den på hjemmeskærmen på telefonen, så den opfører sig som en app.

Opdatering: `git pull && docker compose up -d --build` i `/opt/golfturnering`. Data ligger i
Docker-volumen `golfturnering_golf_data` og overlever opdateringer. En kopi af data hentes med
`docker compose cp golf:/data/golf.json .`.

## Tests

```bash
pytest
```

Beregningerne (spillehandicap, Stableford, turneringspoint) ligger i `golf/static/scoring.js` og testes
med node; API'et testes med FastAPI's testklient.
