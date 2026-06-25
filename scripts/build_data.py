"""Génération du fichier data/clubs-idf.json.

Source unique demandée : https://competitions.ffbb.com/ligues/idf

Principe volontairement choisi pour éviter les approximations :
- on part des 8 comités franciliens affichés sur la page IDF ;
- on récupère les fiches clubs publiques de chaque comité ;
- chaque fiche club indique ses équipes et leurs engagements ;
- on garde uniquement les championnats régionaux IDF 5x5 masculins/féminins, seniors et jeunes ;
- on géocode l'adresse officielle du club via Nominatim/OpenStreetMap, avec cache local.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUT_FILE = DATA_DIR / "clubs-idf.json"
GEOCODE_CACHE_FILE = DATA_DIR / "geocode-cache.json"

BASE_URL = "https://competitions.ffbb.com"
LEAGUE_URL = "https://competitions.ffbb.com/ligues/idf"

# Comités affichés sur la page de la ligue IDF.
# On les fixe pour éviter de dépendre d'un texte de menu qui peut bouger.
IDF_COMITES = {
    "0075": "75",
    "0077": "77",
    "0078": "78",
    "0091": "91",
    "0092": "92",
    "0093": "93",
    "0094": "94",
    "0095": "95",
}

REQUEST_HEADERS = {
    "User-Agent": "carte-idf-ffbb/1.0 (+https://github.com/elliotfx/carte-idf)",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

GEOCODER_HEADERS = {
    "User-Agent": "carte-idf-ffbb/1.0 elliotfx-carte-idf",
    "Accept-Language": "fr",
}

LEVEL_RANK = {
    "NM1": 10,
    "NF1": 10,
    "NM2": 20,
    "NF2": 20,
    "NM3": 30,
    "NF3": 30,
    "PNM": 40,
    "PNF": 40,
    "RM1": 50,
    "RF1": 50,
    "RM2": 60,
    "RF2": 60,
    "RM3": 70,
    "RF3": 70,
    "Régional": 80,
    "Départemental": 200,
    "Autre": 999,
}

LEVEL_ALIASES = [
    ("NM1", ["NATIONALE MASCULINE 1", "NM1"]),
    ("NM2", ["NATIONALE MASCULINE 2", "NM2"]),
    ("NM3", ["NATIONALE MASCULINE 3", "NM3"]),
    ("NF1", ["NATIONALE FEMININE 1", "NATIONALE FÉMININE 1", "NF1"]),
    ("NF2", ["NATIONALE FEMININE 2", "NATIONALE FÉMININE 2", "NF2"]),
    ("NF3", ["NATIONALE FEMININE 3", "NATIONALE FÉMININE 3", "NF3"]),
    ("PNM", ["PRE NATIONALE MASCULINE", "PRÉ NATIONALE MASCULINE", "PNM"]),
    ("PNF", ["PRE NATIONALE FEMININE", "PRÉ NATIONALE FÉMININE", "PNF"]),
    ("RM1", ["REGIONALE MASCULINE SENIORS - DIVISION 1", "RÉGIONALE MASCULINE SENIORS - DIVISION 1", "RM1"]),
    ("RM2", ["REGIONALE MASCULINE SENIORS - DIVISION 2", "RÉGIONALE MASCULINE SENIORS - DIVISION 2", "RM2"]),
    ("RM3", ["REGIONALE MASCULINE SENIORS - DIVISION 3", "RÉGIONALE MASCULINE SENIORS - DIVISION 3", "RM3"]),
    ("RF1", ["REGIONALE FEMININE SENIORS - DIVISION 1", "RÉGIONALE FÉMININE SENIORS - DIVISION 1", "RF1"]),
    ("RF2", ["REGIONALE FEMININE SENIORS - DIVISION 2", "RÉGIONALE FÉMININE SENIORS - DIVISION 2", "RF2"]),
    ("RF3", ["REGIONALE FEMININE SENIORS - DIVISION 3", "RÉGIONALE FÉMININE SENIORS - DIVISION 3", "RF3"]),
]


@dataclass
class Competition:
    slug: str
    nom: str
    url: str
    genre: str
    categorie: str
    niveau: str


@dataclass
class Engagement:
    equipe_nom: str
    equipe_url: str | None
    competition_nom: str
    competition_slug: str
    competition_url: str | None
    competition_code: str
    niveau: str
    level_rank: int
    genre: str
    categorie: str
    poule: str


@dataclass
class Club:
    club_id: str
    nom: str
    url: str
    comite: str
    departement: str
    adresse: str | None
    code_postal: str | None
    ville: str | None
    lat: float | None
    lon: float | None
    geocoding_status: str
    engagements: list[dict]


class FFBBBuildError(RuntimeError):
    pass


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def normalize_key(value: str) -> str:
    value = clean_text(value).lower()
    value = value.replace("é", "e").replace("è", "e").replace("ê", "e").replace("ë", "e")
    value = value.replace("à", "a").replace("ù", "u").replace("ô", "o").replace("î", "i")
    return value


def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def get_html(session: requests.Session, url: str) -> BeautifulSoup:
    response = session.get(url, timeout=40)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def absolute_url(href: str | None) -> str | None:
    if not href:
        return None
    return urljoin(BASE_URL, href)


def slug_from_competition_url(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"/ligues/idf/competitions/([^/?#]+)", url)
    return match.group(1) if match else None


def club_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"/clubs/([^/?#]+)", url)
    return match.group(1) if match else None


def detect_genre(text: str) -> str:
    key = normalize_key(text)
    if "feminin" in key or "feminine" in key:
        return "Féminin"
    if "masculin" in key or "masculine" in key:
        return "Masculin"
    return "Non renseigné"


def detect_categorie(text: str) -> str:
    key = normalize_key(text)
    if "seniors" in key or "senior" in key:
        return "Seniors"
    for cat in ["U21", "U18", "U15", "U13", "U11", "U9", "VE"]:
        if cat.lower() in key:
            return cat
    if "veteran" in key or "vétéran" in key:
        return "VE"
    return "Non renseignée"


def detect_level(name: str, code: str = "") -> str:
    combined = f"{name} {code}".upper()
    for level, aliases in LEVEL_ALIASES:
        if any(alias.upper() in combined for alias in aliases):
            return level
    if "REGIONALE" in combined or "RÉGIONALE" in combined:
        return "Régional"
    if "DEPARTEMENT" in combined or "DÉPARTEMENT" in combined:
        return "Départemental"
    return "Autre"


def split_engagement_label(text: str) -> tuple[str, str, str, str]:
    """Retourne compétition, code, phase, poule depuis un libellé de fiche club.

    Exemple :
    Régionale masculine seniors - Division 3 IDF | RM3 | Poule A 10 e 28
    """
    text = clean_text(text)
    parts = [clean_text(part) for part in text.split("|")]

    competition = parts[0] if parts else text
    code = parts[1] if len(parts) > 1 else ""
    phase = ""
    poule = ""

    for part in parts[2:]:
        if re.search(r"\bPoule\b", part, flags=re.I):
            poule = re.sub(r"\s+\d+\s*e\s+\d+.*$", "", part, flags=re.I).strip()
        elif "phase" in normalize_key(part):
            phase = part

    if not poule:
        match = re.search(r"\b(Poule\s+[A-Z0-9]+)\b", text, flags=re.I)
        if match:
            poule = clean_text(match.group(1))

    return competition, code, phase, poule or "Poule non renseignée"


def discover_regional_competitions(session: requests.Session) -> dict[str, Competition]:
    """Lit la page IDF et conserve seulement les championnats régionaux 5x5 M/F.

    Cette étape sert de référence pour filtrer les équipes des fiches clubs.
    """
    soup = get_html(session, LEAGUE_URL)
    links = soup.find_all("a", href=re.compile(r"/ligues/idf/competitions/"))

    competitions: dict[str, Competition] = {}
    forbidden = [
        "coupe",
        "trophee",
        "trophée",
        "finale",
        "barrage",
        "accession",
        "tqd",
        "tic",
        "tip",
        "matchs amicaux",
        "3x3",
        "fauteuil",
    ]

    for link in links:
        href = absolute_url(link.get("href"))
        slug = slug_from_competition_url(href)
        label = clean_text(link.get_text(" "))
        label_key = normalize_key(label)

        if not slug or not label:
            continue
        if any(word in label_key for word in forbidden):
            continue
        if "regionale" not in label_key and "pre nationale" not in label_key and "pré nationale" not in label_key:
            continue
        if "masculin" not in label_key and "feminin" not in label_key and "feminine" not in label_key:
            continue

        genre = detect_genre(label)
        categorie = detect_categorie(label)
        level = detect_level(label)

        competitions[slug] = Competition(
            slug=slug,
            nom=label,
            url=href or f"{LEAGUE_URL}/competitions/{slug}",
            genre=genre,
            categorie=categorie,
            niveau=level,
        )

    if not competitions:
        raise FFBBBuildError("Aucune compétition régionale 5x5 IDF trouvée sur la page FFBB.")

    return dict(sorted(competitions.items(), key=lambda item: item[1].nom))


def discover_club_urls(session: requests.Session) -> dict[str, dict]:
    clubs: dict[str, dict] = {}

    for comite, departement in IDF_COMITES.items():
        url = f"{LEAGUE_URL}/comites/{comite}"
        soup = get_html(session, url)
        links = soup.find_all("a", href=re.compile(rf"/ligues/idf/comites/{comite}/clubs/"))

        for link in links:
            href = absolute_url(link.get("href"))
            club_id = club_id_from_url(href)
            if not href or not club_id:
                continue

            label = clean_text(link.get_text(" "))
            if not label or "en savoir plus" in normalize_key(label):
                label = re.sub(r"\s*En savoir plus\s*", "", label, flags=re.I).strip()

            clubs[club_id] = {
                "club_id": club_id,
                "nom_hint": label,
                "url": href,
                "comite": comite,
                "departement": departement,
            }

    return dict(sorted(clubs.items(), key=lambda item: (item[1]["departement"], item[1]["nom_hint"])))


def extract_address_fields(text: str) -> tuple[str | None, str | None, str | None]:
    text = clean_text(text)
    if not text:
        return None, None, None

    code_postal = None
    ville = None
    match = re.search(r"\b(75\d{3}|77\d{3}|78\d{3}|91\d{3}|92\d{3}|93\d{3}|94\d{3}|95\d{3})\b\s+(.+)$", text)
    if match:
        code_postal = match.group(1)
        ville = clean_text(match.group(2))

    return text, code_postal, ville


def extract_club_name(soup: BeautifulSoup, fallback: str) -> str:
    h1 = soup.find("h1")
    name = clean_text(h1.get_text(" ") if h1 else "")
    return name or fallback


def extract_contact_block_text(soup: BeautifulSoup) -> str:
    body_text = clean_text(soup.get_text("\n"))
    return body_text


def extract_address_from_club_page(soup: BeautifulSoup) -> tuple[str | None, str | None, str | None]:
    text = extract_contact_block_text(soup)
    lines = [clean_text(line) for line in text.split("\n") if clean_text(line)]

    for index, line in enumerate(lines):
        if normalize_key(line) == "adresse" and index + 1 < len(lines):
            return extract_address_fields(lines[index + 1])

    # Fallback pour le texte aplati.
    match = re.search(
        r"Adresse\s+([^\n]+?\b(?:75\d{3}|77\d{3}|78\d{3}|91\d{3}|92\d{3}|93\d{3}|94\d{3}|95\d{3})\b\s+[A-ZÀ-Ÿ'\- ]+)",
        text,
        flags=re.I,
    )
    if match:
        return extract_address_fields(match.group(1))

    return None, None, None


def extract_engagements_from_club_page(
    soup: BeautifulSoup,
    competitions: dict[str, Competition],
) -> list[Engagement]:
    engagements: list[Engagement] = []
    all_comp_names = {normalize_key(c.nom): c for c in competitions.values()}

    for link in soup.find_all("a"):
        label = clean_text(link.get_text(" "))
        if not label or "|" not in label:
            continue

        label_key = normalize_key(label)
        if "championnat" in label_key and "5x5" in label_key:
            continue
        if "coupe" in label_key or "trophee" in label_key or "trophée" in label_key:
            continue

        competition_nom, code, _phase, poule = split_engagement_label(label)
        competition_key = normalize_key(competition_nom)

        matched = None
        if competition_key in all_comp_names:
            matched = all_comp_names[competition_key]
        else:
            for competition in competitions.values():
                comp_key = normalize_key(competition.nom)
                if comp_key and (competition_key.startswith(comp_key) or comp_key.startswith(competition_key)):
                    matched = competition
                    break

        if not matched:
            continue

        href = absolute_url(link.get("href"))
        level = detect_level(matched.nom, code)

        engagements.append(
            Engagement(
                equipe_nom="",
                equipe_url=href,
                competition_nom=matched.nom,
                competition_slug=matched.slug,
                competition_url=matched.url,
                competition_code=code,
                niveau=level if level != "Autre" else matched.niveau,
                level_rank=LEVEL_RANK.get(level, LEVEL_RANK.get(matched.niveau, 999)),
                genre=matched.genre,
                categorie=matched.categorie,
                poule=poule,
            )
        )

    # Certaines fiches répètent les mêmes liens. On déduplique sur compétition/poule/url.
    deduped: dict[tuple[str, str, str | None], Engagement] = {}
    for engagement in engagements:
        key = (engagement.competition_slug, engagement.poule, engagement.equipe_url)
        deduped[key] = engagement

    return list(deduped.values())


def load_geocode_cache() -> dict:
    if not GEOCODE_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(GEOCODE_CACHE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_geocode_cache(cache: dict) -> None:
    GEOCODE_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def geocode_address(address: str | None, cache: dict) -> tuple[float | None, float | None, str]:
    if not address:
        return None, None, "missing_address"

    query = f"{address}, France"
    cache_key = normalize_key(query)
    if cache_key in cache:
        item = cache[cache_key]
        return item.get("lat"), item.get("lon"), item.get("status", "cached")

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "fr",
    }

    try:
        response = requests.get(url, params=params, headers=GEOCODER_HEADERS, timeout=40)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        cache[cache_key] = {"lat": None, "lon": None, "status": f"error: {exc}"}
        return None, None, cache[cache_key]["status"]

    if not data:
        cache[cache_key] = {"lat": None, "lon": None, "status": "not_found"}
        return None, None, "not_found"

    lat = float(data[0]["lat"])
    lon = float(data[0]["lon"])
    cache[cache_key] = {"lat": lat, "lon": lon, "status": "ok"}

    # Nominatim demande des usages raisonnables. On espace les requêtes non cachées.
    time.sleep(1.1)
    return lat, lon, "ok"


def build_club(
    session: requests.Session,
    club_meta: dict,
    competitions: dict[str, Competition],
    geocode_cache: dict,
) -> Club | None:
    soup = get_html(session, club_meta["url"])
    name = extract_club_name(soup, club_meta["nom_hint"])
    engagements = extract_engagements_from_club_page(soup, competitions)

    if not engagements:
        return None

    address, postal_code, city = extract_address_from_club_page(soup)
    lat, lon, geocoding_status = geocode_address(address, geocode_cache)

    # Le nom d'équipe n'est pas toujours isolé dans la fiche club. On reprend le nom du club.
    for engagement in engagements:
        if not engagement.equipe_nom:
            engagement.equipe_nom = name

    return Club(
        club_id=club_meta["club_id"],
        nom=name,
        url=club_meta["url"],
        comite=club_meta["comite"],
        departement=club_meta["departement"],
        adresse=address,
        code_postal=postal_code,
        ville=city,
        lat=lat,
        lon=lon,
        geocoding_status=geocoding_status,
        engagements=[asdict(engagement) for engagement in engagements],
    )


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    session = get_session()
    geocode_cache = load_geocode_cache()

    print("Découverte des championnats régionaux 5x5 IDF…")
    competitions = discover_regional_competitions(session)
    print(f"{len(competitions)} championnats régionaux trouvés.")

    print("Découverte des clubs des 8 comités IDF…")
    club_urls = discover_club_urls(session)
    print(f"{len(club_urls)} fiches clubs trouvées.")

    clubs: list[Club] = []
    errors: list[dict] = []

    for index, club_meta in enumerate(club_urls.values(), start=1):
        print(f"[{index}/{len(club_urls)}] {club_meta['nom_hint'] or club_meta['club_id']}")
        try:
            club = build_club(session, club_meta, competitions, geocode_cache)
            if club:
                clubs.append(club)
                save_geocode_cache(geocode_cache)
        except Exception as exc:  # noqa: BLE001 - on journalise et on continue.
            errors.append({"club_id": club_meta["club_id"], "url": club_meta["url"], "error": str(exc)})
            print(f"  Erreur : {exc}")

    competitions_payload = [asdict(competition) for competition in competitions.values()]
    clubs_payload = [asdict(club) for club in sorted(clubs, key=lambda c: (c.departement, c.nom))]

    output = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": LEAGUE_URL,
            "scope": "Championnat régionaux 5x5 masculins et féminins de la Ligue Île-de-France, seniors et jeunes",
            "departements": list(IDF_COMITES.values()),
            "competitions_count": len(competitions_payload),
            "clubs_count": len(clubs_payload),
            "clubs_geocoded_count": sum(1 for club in clubs_payload if club.get("lat") is not None and club.get("lon") is not None),
            "errors_count": len(errors),
            "errors": errors,
        },
        "competitions": competitions_payload,
        "clubs": clubs_payload,
    }

    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    save_geocode_cache(geocode_cache)

    print(f"Fichier généré : {OUTPUT_FILE}")
    print(f"Clubs conservés : {len(clubs_payload)}")
    print(f"Erreurs : {len(errors)}")


if __name__ == "__main__":
    main()
