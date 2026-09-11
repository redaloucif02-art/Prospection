#!/usr/bin/env python3
"""Compte les caractères de pages_cache.jsonl : total, et détail par agence
(somme des textes de toutes ses pages)."""

import json

CACHE_PATH = "pages_cache.jsonl"


def normalize_pages(pages_raw):
    if isinstance(pages_raw, dict):
        out = []
        for url, text in pages_raw.items():
            if isinstance(text, dict):
                out.append(text.get("text", ""))
            else:
                out.append(text if isinstance(text, str) else "")
        return out
    out = []
    for p in pages_raw or []:
        if isinstance(p, dict):
            out.append(p.get("text", "") or "")
        elif isinstance(p, str):
            out.append("")
    return out


def main():
    total_chars_texte = 0   # uniquement le contenu des pages (champ "text")
    total_chars_fichier = 0  # le fichier brut, JSON compris
    nb_agences = 0
    par_agence = []

    with open(CACHE_PATH, encoding="utf-8") as f:
        for line in f:
            total_chars_fichier += len(line)
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            nom = obj.get("nom", "(sans nom)")
            textes = normalize_pages(obj.get("pages", []))
            nb_chars = sum(len(t) for t in textes)
            total_chars_texte += nb_chars
            nb_agences += 1
            par_agence.append((nom, nb_chars))

    print(f"📄 Fichier               : {CACHE_PATH}")
    print(f"🏢 Nombre d'agences      : {nb_agences}")
    print(f"🔤 Caractères (fichier brut, JSON compris) : {total_chars_fichier:,}".replace(",", " "))
    print(f"🔤 Caractères (texte des pages uniquement)  : {total_chars_texte:,}".replace(",", " "))

    if par_agence:
        par_agence.sort(key=lambda x: x[1], reverse=True)
        print("\nTop 10 des agences avec le plus de texte :")
        for nom, nb in par_agence[:10]:
            print(f"    {nb:>8,} caractères — {nom}".replace(",", " "))


if __name__ == "__main__":
    main()
