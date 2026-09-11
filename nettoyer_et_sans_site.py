#!/usr/bin/env python3
"""
Script en 2 étapes (dans cet ordre) :

  ÉTAPE 1 — Supprime, dans prospection.csv ET extraction_results.jsonl,
            toutes les agences dont le nom apparaît dans agences_delete.csv.
            Des sauvegardes .bak sont créées avant toute modification.

  ÉTAPE 2 — Une fois la suppression faite, compare les noms restants de
            prospection.csv à ceux présents dans pages_cache.jsonl. Une
            agence absente de pages_cache.jsonl est considérée comme
            "sans site web" (aucune page n'a été scrapée pour elle) et
            est écrite dans agences_sans_site.csv.

La comparaison des noms est normalisée (accents, casse, espaces) pour
éviter de rater des correspondances à cause d'une majuscule ou d'une
apostrophe différente — mais le nom d'origine (tel qu'il apparaît dans
le fichier) est toujours celui conservé/écrit en sortie.

Usage :
    python nettoyer_et_sans_site.py
    python nettoyer_et_sans_site.py --dry-run     # simulation, rien n'est écrit
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
RESULTS_PATH = "extraction_results.jsonl"
CACHE_PATH = "pages_cache.jsonl"
DELETE_LIST_PATH = "agences_delete.csv"
OUTPUT_NO_WEBSITE_PATH = "agences_sans_site.csv"
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


def find_nom_column(fieldnames, path_for_error):
    norm_to_actual = {normalize(h): h for h in fieldnames}
    actual = norm_to_actual.get(normalize(NOM_COLUMN_LABEL))
    if actual is None:
        sys.exit(f"❌ Colonne « {NOM_COLUMN_LABEL} » introuvable dans {path_for_error}.\n"
                  f"   Colonnes trouvées : {fieldnames}")
    return actual


def load_names_to_delete(path):
    """Renvoie un dict {nom_normalisé: nom_original} depuis agences_delete.csv."""
    if not os.path.exists(path):
        sys.exit(f"❌ {path} introuvable.")
    names = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        col = find_nom_column(reader.fieldnames, path)
        for row in reader:
            n = (row.get(col) or "").strip()
            if n:
                names[normalize(n)] = n
    return names


# --- Étape 1 : suppression --------------------------------------------

def step1_delete(names_to_delete, dry_run):
    matched = set()

    # --- prospection.csv ---
    if not os.path.exists(PROSPECTION_PATH):
        sys.exit(f"❌ {PROSPECTION_PATH} introuvable.")

    with open(PROSPECTION_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        col = find_nom_column(fieldnames, PROSPECTION_PATH)
        rows = list(reader)

    kept_rows, removed_rows = [], []
    for row in rows:
        n = (row.get(col) or "").strip()
        if normalize(n) in names_to_delete:
            removed_rows.append(n)
            matched.add(normalize(n))
        else:
            kept_rows.append(row)

    print(f"📄 {PROSPECTION_PATH} : {len(removed_rows)} ligne(s) à supprimer sur {len(rows)}")
    if not dry_run:
        shutil.copy(PROSPECTION_PATH, PROSPECTION_PATH + ".bak")
        with open(PROSPECTION_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(kept_rows)
        print(f"   ✅ Supprimé. Sauvegarde : {PROSPECTION_PATH}.bak")
    else:
        print("   (dry-run, rien écrit)")

    # --- extraction_results.jsonl ---
    removed_results = 0
    if os.path.exists(RESULTS_PATH):
        kept_lines = []
        total_lines = 0
        with open(RESULTS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total_lines += 1
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    kept_lines.append(line)
                    continue
                nom = obj.get("nom", "")
                if normalize(nom) in names_to_delete:
                    removed_results += 1
                    matched.add(normalize(nom))
                else:
                    kept_lines.append(line)

        print(f"📄 {RESULTS_PATH} : {removed_results} ligne(s) à supprimer sur {total_lines}")
        if not dry_run:
            shutil.copy(RESULTS_PATH, RESULTS_PATH + ".bak")
            with open(RESULTS_PATH, "w", encoding="utf-8") as f:
                for line in kept_lines:
                    f.write(line + "\n")
            print(f"   ✅ Supprimé. Sauvegarde : {RESULTS_PATH}.bak")
        else:
            print("   (dry-run, rien écrit)")
    else:
        print(f"ℹ️ {RESULTS_PATH} introuvable, rien à supprimer là-dedans.")

    not_found = set(names_to_delete) - matched
    if not_found:
        print(f"\n⚠️ {len(not_found)} nom(s) de {DELETE_LIST_PATH} n'ont été trouvés "
              f"NI dans {PROSPECTION_PATH} NI dans {RESULTS_PATH} (vérifie l'orthographe) :")
        for norm_name in sorted(not_found):
            print(f"    - {names_to_delete[norm_name]}")


# --- Étape 2 : agences sans site web -----------------------------------

def step2_find_no_website(dry_run):
    if not os.path.exists(CACHE_PATH):
        sys.exit(f"❌ {CACHE_PATH} introuvable.")

    cache_names = set()
    with open(CACHE_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            nom = obj.get("nom", "")
            if nom:
                cache_names.add(normalize(nom))

    with open(PROSPECTION_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        col = find_nom_column(fieldnames, PROSPECTION_PATH)
        rows = list(reader)

    sans_site = [row for row in rows if normalize(row.get(col) or "") not in cache_names]

    print(f"\n📄 {PROSPECTION_PATH} (après suppression) : {len(rows)} agence(s)")
    print(f"🌐 {len(cache_names)} agence(s) présentes dans {CACHE_PATH} (ont un site scrapé)")
    print(f"🚫 {len(sans_site)} agence(s) absentes de {CACHE_PATH} → considérées sans site web")

    if not dry_run:
        with open(OUTPUT_NO_WEBSITE_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(sans_site)
        print(f"   ✅ Écrit dans {OUTPUT_NO_WEBSITE_PATH}")
    else:
        print("   (dry-run, rien écrit)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                         help="Simule sans rien écrire ni supprimer")
    args = parser.parse_args()

    print("=== ÉTAPE 1 : suppression des agences listées ===")
    names_to_delete = load_names_to_delete(DELETE_LIST_PATH)
    print(f"📋 {len(names_to_delete)} nom(s) uniques dans {DELETE_LIST_PATH}\n")
    step1_delete(names_to_delete, args.dry_run)

    print("\n=== ÉTAPE 2 : agences sans site web ===")
    step2_find_no_website(args.dry_run)


if __name__ == "__main__":
    main()
