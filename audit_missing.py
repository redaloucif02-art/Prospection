#!/usr/bin/env python3
"""
Génère un état des lieux JSON : pour chaque agence de prospection.csv,
indique quels champs sont déjà remplis ("check") et lesquels manquent
("a chercher").

Colonnes EXCLUES de l'analyse (jamais mentionnées dans le résultat) :
  - Nom de l'agence (sert d'identifiant)
  - Source de l'agence
  - Source du gérant
"""

import csv
import json
import re
import sys

CSV_PATH = "prospection.csv"
OUTPUT_PATH = "audit_missing.json"

EXCLUDED_LABELS = {
    "Nom de l’agence",
    "Source de l’agence",
    "Source du gérant",
}

NOM_LABEL = "Nom de l’agence"


def normalize(s):
    s = s.strip().lower()
    s = s.replace("’", "'").replace("‘", "'")
    s = re.sub(r"\s+", " ", s)
    return s


def find_actual_header(fieldnames, label):
    norm_target = normalize(label)
    for h in fieldnames:
        if normalize(h) == norm_target:
            return h
    return None


def main():
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    nom_col = find_actual_header(fieldnames, NOM_LABEL)
    if nom_col is None:
        sys.exit(f"❌ Colonne '{NOM_LABEL}' introuvable. En-têtes présents : {fieldnames}")

    excluded_actual = set()
    for label in EXCLUDED_LABELS:
        actual = find_actual_header(fieldnames, label)
        if actual:
            excluded_actual.add(actual)

    champs_a_verifier = [h for h in fieldnames if h not in excluded_actual]

    resultat = []
    for row in rows:
        nom = row.get(nom_col, "").strip()
        if not nom:
            continue
        champs = {}
        for col in champs_a_verifier:
            val = row.get(col, "").strip()
            champs[col] = "check" if val else "a chercher"
        resultat.append({"agence": nom, "champs": champs})

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resultat, f, ensure_ascii=False, indent=2)

    total = len(resultat)
    print(f"✅ {total} agences analysées → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
