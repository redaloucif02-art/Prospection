#!/usr/bin/env python3
"""
Vérifie pages_cache.jsonl :
- nombre total de lignes
- nombre de lignes JSON invalides
- doublons par site_web (clé la plus fiable, normalisée)
- doublons par nom d'agence (juste pour info, moins fiable : deux agences
  différentes peuvent porter le même nom commercial)

Usage :
    python3 check_duplicates.py pages_cache.jsonl
"""

import json
import sys
from collections import defaultdict
from urllib.parse import urlparse


def normalize_url(url: str) -> str:
    """Normalise une URL pour comparer les doublons sans se faire avoir par
    http vs https, www. vs pas, ou un slash final."""
    url = url.strip().lower()
    parsed = urlparse(url if "://" in url else f"http://{url}")
    netloc = parsed.netloc.removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{netloc}{path}"


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "pages_cache.jsonl"

    total_lines = 0
    invalid_lines = 0
    by_site: dict[str, list[int]] = defaultdict(list)
    by_name: dict[str, list[int]] = defaultdict(list)

    with open(path, encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            total_lines += 1
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                invalid_lines += 1
                print(f"  ligne {line_number} : JSON invalide ({e})")
                continue

            site = (entry.get("site_web") or "").strip()
            nom = (entry.get("nom") or "").strip()

            if site:
                by_site[normalize_url(site)].append(line_number)
            if nom:
                by_name[nom.lower()].append(line_number)

    dup_sites = {k: v for k, v in by_site.items() if len(v) > 1}
    dup_names = {k: v for k, v in by_name.items() if len(v) > 1}

    print(f"Total de lignes lues       : {total_lines}")
    print(f"Lignes JSON invalides      : {invalid_lines}")
    print(f"Sites web uniques          : {len(by_site)}")
    print(f"Sites web en doublon       : {len(dup_sites)}")
    print(f"Noms d'agence en doublon   : {len(dup_names)} (indicatif seulement)")

    if dup_sites:
        print("\n--- Doublons par site_web ---")
        for site, lines in sorted(dup_sites.items()):
            print(f"  {site} -> lignes {lines}")

    if dup_names:
        print("\n--- Doublons par nom (peut être un faux positif, à vérifier) ---")
        for nom, lines in sorted(dup_names.items()):
            print(f"  {nom} -> lignes {lines}")

    if not dup_sites and not dup_names:
        print("\nAucun doublon détecté.")


if __name__ == "__main__":
    main()
