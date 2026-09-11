#!/usr/bin/env python3
"""
Scraping + nettoyage HTML des agences immobilières.

Variante de scraper.py pour retraiter refair_avec_site_web.csv (agences pour
qui un site web a été retrouvé manuellement après le passage
"agences_sans_site.csv") — reprend le même fonctionnement, avec son propre
fichier de progression ET son propre fichier de cache (pages_cache_refair.jsonl)
pour ne rien mélanger avec le scraping principal (prospection.csv /
pages_cache.jsonl / progress.json).

- Lit refair_avec_site_web.csv (utf-8-sig, gère le BOM)
- Pour chaque agence : homepage + pages contact/équipe/mentions-légales détectées
  (via liens de la homepage + sitemap.xml), max 5 pages
- Nettoie le HTML (retire script/style/nav/header/footer, texte visible,
  espaces compressés, coupe à 20 000 caractères)
- Écrit dans pages_cache_refair.jsonl (une ligne par agence : nom + contenu par page)
- Reprend où il s'était arrêté grâce à progress_refair.json
- Commit + push toutes les 20 agences traitées
- S'arrête proprement avant la limite de 6h de GitHub Actions (marge à 5h30)
"""

import csv
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# --- Configuration ---------------------------------------------------------

CSV_PATH = Path("refair_avec_site_web.csv")
CACHE_PATH = Path("pages_cache_refair.jsonl")
PROGRESS_PATH = Path("progress_refair.json")
MISSING_PATH = Path("sites_sans_page_refair.jsonl")

MAX_PAGES_PER_AGENCY = 5
MAX_CHARS_PER_PAGE = 20_000
COMMIT_EVERY = 20

# Nombre max de pages visitées pendant la phase de découverte des liens
# (crawl interne au site, pas juste la homepage). Plus c'est haut, plus on a
# de chances de trouver une page "cachée" (ex: notre-equipe.html référencée
# depuis une sous-page et pas depuis la homepage), mais plus ça coûte de
# requêtes par agence -> impact direct sur le temps total du run.
MAX_CRAWL_PAGES = 12
TIME_BUDGET_SECONDS = 5.5 * 3600  # s'arrête à 5h30, laisse de la marge sur les 6h

REQUEST_TIMEOUT = 10
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ProspectionBot/1.0)"
}

# Motifs à repérer, comparés après suppression des accents/tirets/espaces
# (ex: "l-Équipe", "notre_equipe", "L'ÉQUIPE" matchent tous "equipe")
CONTACT_PATTERNS = [
    "contact", "contactez", "nouscontacter", "nousjoindre",
    "coordonnees", "joignez",
]
EQUIPE_PATTERNS = [
    "equipe", "team", "staff",
    "collaborateurs", "collaborateur",
    "agents", "nosagents", "lesagents",
    "conseillers", "conseiller", "negociateurs", "negociateur",
    "direction", "equipedirigeante", "fondateur", "fondateurs",
]
APROPOS_PATTERNS = [
    "qui-sommes-nous", "quisommesnous", "apropos", "about", "aboutus",
    "notreagence", "lagence", "decouvrirlagence",
    "presentation", "notrehistoire", "histoire",
]
MENTIONS_PATTERNS = [
    "mentionslegales", "mentionlegale", "informationslegales",
    "legal", "cgv", "cgu", "credits",
]

START_TIME = time.monotonic()


# --- Utilitaires -------------------------------------------------------------

def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize(text: str) -> str:
    return strip_accents(text).lower()


def normalize_loose(text: str) -> str:
    """Normalise pour la comparaison de motifs : sans accents, sans casse,
    et sans tirets/underscores/espaces/ponctuation. Ainsi 'l-Équipe',
    'notre_equipe' et "L'ÉQUIPE" matchent tous le motif 'equipe'."""
    text = normalize(text)
    return re.sub(r"[^a-z0-9]", "", text)


def time_is_up() -> bool:
    return (time.monotonic() - START_TIME) >= TIME_BUDGET_SECONDS


def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    return {"last_processed_index": -1}


def save_progress(index: int, total: int) -> None:
    PROGRESS_PATH.write_text(
        json.dumps(
            {
                "last_processed_index": index,
                "total_agencies": total,
                "last_run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def git_commit_and_push(message: str) -> None:
    """Commit + push les fichiers de sortie. N'échoue pas le job si rien à commit."""
    try:
        subprocess.run(["git", "add", str(CACHE_PATH), str(PROGRESS_PATH), str(MISSING_PATH)], check=True)
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            print(f"git commit warning: {result.stdout} {result.stderr}", file=sys.stderr)
            return
        subprocess.run(["git", "push"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"git commit/push a échoué : {e}", file=sys.stderr)


# --- Lecture du CSV ----------------------------------------------------------

# Colonnes attendues, avec pour chacune des variantes possibles côté en-tête
# CSV. On matche en insensible à la casse/accents/espaces/apostrophes pour
# éviter les soucis d'encodage type "Nom de l'agence" vs "Nom de l’agence".
CANONICAL_COLUMNS: dict[str, list[str]] = {
    "Nom de l'agence": ["nomdelagence", "nom", "nomagence", "agence", "raisonsociale", "name"],
    "Téléphone de l'agence": ["telephonedelagence", "telephoneagence", "teldelagence", "telagence", "telephone", "tel"],
    "Email de l'agence": ["emaildelagence", "emailagence", "email", "mail"],
    "Horaires": ["horaires", "horaire"],
    "Site web": ["siteweb", "site", "website", "url"],
    "Avis": ["avis", "note", "notes", "reviews"],
    "Indépendant ou Franchise": ["independantoufranchise", "independantfranchise", "typeagence", "statut"],
    "Ville / département": ["villedepartement", "ville", "departement", "villedept"],
    "Gérant": ["gerant", "manager", "dirigeant"],
    "Tel du gérant": ["teldugerant", "telephonedugerant", "telgerant"],
    "Email du gérant": ["emaildugerant", "mailgerant", "emailgerant"],
    "Source de l'agence": ["sourcedelagence", "sourceagence"],
    "Source du gérant": ["sourcedugerant", "sourcegerant"],
    "Date de vérification": ["datedeverification", "dateverification", "date"],
}

# Colonnes indispensables pour que le scraping fonctionne
REQUIRED_COLUMNS = ["Nom de l'agence", "Site web"]


def _match_columns(fieldnames: list[str]) -> dict[str, str | None]:
    """Associe chaque colonne canonique au nom de colonne réel du CSV (ou None
    si introuvable)."""
    normalized_fields = {normalize_loose(f): f for f in fieldnames}
    mapping: dict[str, str | None] = {}
    for canonical, candidates in CANONICAL_COLUMNS.items():
        real_col = None
        for candidate in candidates:
            if candidate in normalized_fields:
                real_col = normalized_fields[candidate]
                break
        mapping[canonical] = real_col
    return mapping


def load_agencies() -> list[dict]:
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        column_map = _match_columns(fieldnames)

        missing_required = [c for c in REQUIRED_COLUMNS if not column_map.get(c)]
        missing_optional = [
            c for c in CANONICAL_COLUMNS if c not in REQUIRED_COLUMNS and not column_map.get(c)
        ]
        if missing_required or missing_optional:
            print(f"Colonnes détectées dans le CSV : {fieldnames}", file=sys.stderr)
        if missing_required:
            print(f"ATTENTION : colonnes obligatoires introuvables : {missing_required} "
                  "(nom et/ou URL vides -> agences ignorées ou '(sans nom)').", file=sys.stderr)
        if missing_optional:
            print(f"Info : colonnes optionnelles introuvables (ignorées) : {missing_optional}", file=sys.stderr)

        rows = []
        for row in reader:
            entry = {}
            for canonical, real_col in column_map.items():
                entry[canonical] = (row.get(real_col, "") if real_col else "").strip()
            rows.append(entry)
        return rows


# --- Découverte des pages à scraper ------------------------------------------

def fetch(url: str) -> requests.Response | None:
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp
    except requests.RequestException:
        pass
    return None


def _same_domain(url: str, domain: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return netloc.replace("www.", "") == domain.replace("www.", "")


def find_from_sitemap(homepage_url: str, patterns: list[str]) -> str | None:
    parsed = urlparse(homepage_url)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
    resp = fetch(sitemap_url)
    if not resp:
        return None
    try:
        soup = BeautifulSoup(resp.content, "xml")
    except Exception:
        return None
    for loc in soup.find_all("loc"):
        url = loc.get_text(strip=True)
        if any(p in normalize_loose(url) for p in patterns):
            return url
    return None


def crawl_site_links(homepage_url: str) -> tuple[dict[str, str], dict[str, str]]:
    """Explore le site (BFS, liens internes uniquement) jusqu'à
    MAX_CRAWL_PAGES pages visitées. Retourne :
    - all_links : {url_absolue: texte_du_lien} pour tous les liens internes
      trouvés sur les pages visitées (y compris ceux menant à des pages non
      visitées, faute de budget) ;
    - fetched_html : {url_absolue: html} pour les pages effectivement
      téléchargées pendant le crawl, pour éviter de les re-télécharger plus
      tard dans process_agency.
    """
    domain = urlparse(homepage_url).netloc
    visited: set[str] = set()
    queue: list[str] = [homepage_url]
    all_links: dict[str, str] = {}
    fetched_html: dict[str, str] = {}

    while queue and len(visited) < MAX_CRAWL_PAGES:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        resp = fetch(url)
        if not resp:
            continue
        fetched_html[url] = resp.text

        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            full_url = urljoin(url, href).split("#")[0]
            if not _same_domain(full_url, domain):
                continue
            if urlparse(full_url).path.lower().endswith(".php"):
                continue
            # on garde le premier texte de lien rencontré pour chaque URL
            all_links.setdefault(full_url, a.get_text(" ", strip=True))
            if full_url not in visited and full_url not in queue:
                queue.append(full_url)

    return all_links, fetched_html


def match_link(all_links: dict[str, str], patterns: list[str], exclude: set[str]) -> str | None:
    for url, link_text in all_links.items():
        if url in exclude:
            continue
        norm_href = normalize_loose(url)
        norm_text = normalize_loose(link_text)
        if any(p in norm_href or p in norm_text for p in patterns):
            return url
    return None


def discover_pages(homepage_url: str) -> tuple[list[str], dict[str, str]]:
    """Retourne (urls, fetched_html) :
    - urls : jusqu'à MAX_PAGES_PER_AGENCY URLs contact/équipe/mentions-légales
      (la homepage n'est pas incluse, elle sert uniquement de point de départ) ;
    - fetched_html : pages déjà téléchargées pendant le crawl (réutilisées par
      process_agency pour éviter une double requête).
    Le matching se fait maintenant sur TOUS les liens internes trouvés en
    explorant plusieurs pages du site (pas juste la homepage), ce qui permet
    de récupérer des pages référencées seulement depuis une sous-page
    (ex: menu "L'agence" -> "Notre équipe" absent de la homepage elle-même).
    """
    all_links, fetched_html = crawl_site_links(homepage_url)

    pages: list[str] = []
    seen: set[str] = {homepage_url}
    for patterns in (CONTACT_PATTERNS, EQUIPE_PATTERNS, APROPOS_PATTERNS, MENTIONS_PATTERNS):
        found = match_link(all_links, patterns, seen)
        if not found:
            found = find_from_sitemap(homepage_url, patterns)
        if found and found not in seen:
            pages.append(found)
            seen.add(found)
        if len(pages) >= MAX_PAGES_PER_AGENCY:
            break

    return pages[:MAX_PAGES_PER_AGENCY], fetched_html


# --- Nettoyage HTML ------------------------------------------------------------

def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_CHARS_PER_PAGE]


def page_label(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path or urlparse(url).netloc


# --- Boucle principale ---------------------------------------------------------

def process_agency(agency: dict) -> tuple[dict | None, str | None]:
    name = agency.get("Nom de l'agence", "").strip()
    homepage_url = agency.get("Site web", "").strip()
    if not homepage_url:
        print(f"  -> pas de site web, ignorée")
        return None, "pas de site web"

    pages_content = {}
    urls, fetched_html = discover_pages(homepage_url)
    for url in urls:
        html = fetched_html.get(url)
        if html is None:
            resp = fetch(url)
            if not resp:
                print(f"     échec : {url}")
                continue
            html = resp.text
        cleaned = clean_html(html)
        if cleaned:
            label = page_label(url)
            pages_content[label] = cleaned
            print(f"     ok [{label}] {len(cleaned)} caractères — {url}")

    if not pages_content:
        print(f"  -> aucune page récupérée")
        return None, "aucune page récupérée (homepage injoignable ou aucun lien pertinent trouvé)"

    return {"nom": name, "site_web": homepage_url, "pages": pages_content}, None


def main() -> None:
    agencies = load_agencies()
    progress = load_progress()
    start_index = progress["last_processed_index"] + 1
    total = len(agencies)

    print(f"Reprise à l'index {start_index} / {total}")

    cache_file = CACHE_PATH.open("a", encoding="utf-8")
    missing_file = MISSING_PATH.open("a", encoding="utf-8")
    processed_since_commit = 0

    try:
        for i in range(start_index, total):
            if time_is_up():
                print("Budget temps atteint (5h30), arrêt propre.")
                break

            agency = agencies[i]
            name = agency.get("Nom de l'agence", "").strip() or "(sans nom)"
            print(f"[{i + 1}/{total}] {name}")
            result, reason = process_agency(agency)
            if result:
                cache_file.write(json.dumps(result, ensure_ascii=False) + "\n")
                cache_file.flush()
            else:
                missing_file.write(json.dumps(
                    {
                        "nom": name,
                        "site_web": agency.get("Site web", "").strip(),
                        "raison": reason,
                    },
                    ensure_ascii=False,
                ) + "\n")
                missing_file.flush()

            save_progress(i, total)
            processed_since_commit += 1

            if processed_since_commit >= COMMIT_EVERY:
                git_commit_and_push(f"Progression scraping (refair) : agence {i + 1}/{total}")
                processed_since_commit = 0

    finally:
        cache_file.close()
        missing_file.close()
        if processed_since_commit > 0:
            git_commit_and_push("Progression scraping (refair) : checkpoint final du run")

    if start_index >= total:
        print("Toutes les agences ont déjà été traitées.")
    else:
        print("Run terminé (fin de liste ou budget temps atteint).")


if __name__ == "__main__":
    main()
