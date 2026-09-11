#!/usr/bin/env python3
"""
ÉTAPE 3 (séparée et manuelle) : applique le contenu de
extraction_results.jsonl (produit par extract_info.py) à prospection.csv.

C'est la SEULE étape qui modifie prospection.csv. Elle log, ligne par ligne
et champ par champ, ce qui change (ancienne valeur -> nouvelle valeur), pour
que tu puisses vérifier avant/après commit.

Usage :
    python merge_results.py             # applique et écrit prospection.csv
    python merge_results.py --dry-run   # affiche seulement ce qui changerait
"""

import csv
import json
import os
import sys
import re
import argparse
from datetime import date

CSV_PATH = "prospection.csv"
RESULTS_PATH = "extraction_results.jsonl"

CANONICAL = {
    "nom": "Nom de l’agence",
    "tel_agence": "Téléphone de l’agence",
    "email_agence": "Email de l’agence",
    "horaires": "Horaires",
    "ville": "Ville / département",
    "gerant": "Gérant",
    "tel_gerant": "Tel du gérant",
    "email_gerant": "Email du gérant",
    "source_gerant": "Source du gérant",
    "date": "Date de vérification",
}


def normalize(s):
    s = s.strip().lower()
    s = s.replace("’", "'").replace("‘", "'")
    s = re.sub(r"\s+", " ", s)
    return s


def build_header_map(fieldnames):
    norm_to_actual = {normalize(h): h for h in fieldnames}
    header_map = {}
    missing = []
    for key, label in CANONICAL.items():
        actual = norm_to_actual.get(normalize(label))
        if actual is None:
            missing.append(label)
        else:
            header_map[key] = actual
    if missing:
        print("❌ Colonnes attendues introuvables dans le CSV :")
        for m in missing:
            print(f"   - {m}")
        sys.exit(1)
    return header_map


def load_results():
    if not os.path.exists(RESULTS_PATH):
        sys.exit(f"❌ {RESULTS_PATH} introuvable — lance d'abord extract_info.py")
    results = {}
    with open(RESULTS_PATH, encoding="utf-8") as f:
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
                results[nom] = obj  # la dernière occurrence gagne si relancé
    return results


def apply_result(row, result, hm):
    """Retourne la liste des changements (label, ancien, nouveau) appliqués à row."""
    changes = []

    def update_simple(col, key, label):
        val = str(result.get(key, "")).strip()
        if val:
            old = row.get(hm[col], "")
            if old != val:
                changes.append((label, old, val))
                row[hm[col]] = val

    update_simple("ville", "adresse", "Adresse")
    update_simple("tel_agence", "telephone_agence", "Tél. agence")
    update_simple("email_agence", "email_agence", "Email agence")
    update_simple("horaires", "horaires", "Horaires")

    source_parts = []
    for col, key, label in [
        ("gerant", "gerant", "Gérant"),
        ("tel_gerant", "tel_gerant", "Tél. gérant"),
        ("email_gerant", "email_gerant", "Email gérant"),
    ]:
        obj = result.get(key, {}) if isinstance(result.get(key), dict) else {}
        val = str(obj.get("valeur", "")).strip()
        if val:
            old = row.get(hm[col], "")
            if old != val:
                changes.append((label, old, val))
                row[hm[col]] = val
            url = obj.get("url_source", "")
            if url:
                source_parts.append(f"{label}: {url}")

    if source_parts:
        row[hm["source_gerant"]] = " | ".join(source_parts)

    if changes:
        row[hm["date"]] = date.today().isoformat()

    return changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                         help="N'écrit rien, affiche seulement les changements qui seraient appliqués")
    args = parser.parse_args()

    results = load_results()
    print(f"📝 {len(results)} agences dans {RESULTS_PATH}\n")

    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    hm = build_header_map(fieldnames)

    total_rows_changed = 0
    total_no_match = 0

    for row in rows:
        nom = row.get(hm["nom"], "").strip()
        if not nom or nom not in results:
            continue
        changes = apply_result(row, results[nom], hm)
        if changes:
            total_rows_changed += 1
            print(f"✏️  {nom}")
            for label, old, new in changes:
                old_disp = old if old else "(vide)"
                print(f"    {label}: {old_disp!r} -> {new!r}")
        else:
            total_no_match += 1

    print(f"\n📊 {total_rows_changed} ligne(s) modifiée(s), "
          f"{total_no_match} agence(s) déjà à jour (aucun changement).")

    if args.dry_run:
        print("\n🔍 Mode --dry-run : rien n'a été écrit dans prospection.csv.")
        return

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✅ {CSV_PATH} mis à jour.")


if __name__ == "__main__":
    main()
