#!/usr/bin/env python3
"""
Supprime de prospection.csv toutes les agences présentes dans
sites_sans_page_refair.jsonl (agences pour qui, même après le passage
"refair" avec un site web retrouvé, aucune page exploitable n'a pu être
récupérée).

Une sauvegarde prospection.csv.bak est créée avant toute modification.

Usage :
    python supprimer_sans_page.py
    python supprimer_sans_page.py --dry-run   # simulation, rien n'est écrit
"""

import argparse
import csv
import json
import os
import re
import shutil
import sys
import unicodedata

PROSPECTION_PATH = "prospection.csv"
SANS_PAGE_PATH = "sites_sans_page_refair.jsonl"
NOM_COLUMN_LABEL = "Nom de l’agence"


def normalize(s):
    """Normalise un nom d'agence pour comparaison : accents, casse,
    apostrophes et espaces multiples ignorés."""
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("’", "'").replace("‘", "'")
    s = re.sub(r"\s+", " ", s)
    return s


def find_nom_column(fieldnames):
    norm_to_actual = {normalize(h): h for h in fieldnames}
    actual = norm_to_actual.get(normalize(NOM_COLUMN_LABEL))
    if actual is None:
        sys.exit(f"❌ Colonne « {NOM_COLUMN_LABEL} » introuvable dans {PROSPECTION_PATH}.\n"
                  f"   Colonnes trouvées : {fieldnames}")
    return actual


def load_names_to_delete():
    """Renvoie un dict {nom_normalisé: nom_original} depuis sites_sans_page_refair.jsonl."""
    if not os.path.exists(SANS_PAGE_PATH):
        sys.exit(f"❌ {SANS_PAGE_PATH} introuvable.")
    names = {}
    with open(SANS_PAGE_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            nom = (obj.get("nom") or "").strip()
            if nom:
                names[normalize(nom)] = nom
    return names


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                         help="N'écrit rien, affiche seulement ce qui serait supprimé")
    args = parser.parse_args()

    names_to_delete = load_names_to_delete()
    print(f"📋 {len(names_to_delete)} nom(s) uniques dans {SANS_PAGE_PATH}\n")

    if not os.path.exists(PROSPECTION_PATH):
        sys.exit(f"❌ {PROSPECTION_PATH} introuvable.")

    with open(PROSPECTION_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        col = find_nom_column(fieldnames)
        rows = list(reader)

    kept_rows, removed_names = [], []
    matched = set()
    for row in rows:
        n = (row.get(col) or "").strip()
        if normalize(n) in names_to_delete:
            removed_names.append(n)
            matched.add(normalize(n))
        else:
            kept_rows.append(row)

    print(f"📄 {PROSPECTION_PATH} : {len(removed_names)} ligne(s) à supprimer sur {len(rows)}")
    for n in removed_names:
        print(f"    - {n}")

    if args.dry_run:
        print("\n🔍 Mode --dry-run : rien n'a été écrit.")
    else:
        shutil.copy(PROSPECTION_PATH, PROSPECTION_PATH + ".bak")
        with open(PROSPECTION_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(kept_rows)
        print(f"\n✅ {PROSPECTION_PATH} mis à jour. Sauvegarde : {PROSPECTION_PATH}.bak")

    not_found = set(names_to_delete) - matched
    if not_found:
        print(f"\n⚠️ {len(not_found)} nom(s) de {SANS_PAGE_PATH} introuvables dans "
              f"{PROSPECTION_PATH} (déjà supprimés ou orthographe différente) :")
        for norm_name in sorted(not_found):
            print(f"    - {names_to_delete[norm_name]}")


if __name__ == "__main__":
    main()
