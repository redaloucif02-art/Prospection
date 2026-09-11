#!/usr/bin/env python3
"""Inspecte pages_cache.jsonl pour une agence donnée (ou la 1re ligne)
et affiche le type des pages + la longueur du texte de chacune.
Usage : python inspect_cache.py [--nom "LG IMMO"]"""
import json, sys, argparse

parser = argparse.ArgumentParser()
parser.add_argument("--file", default="pages_cache.jsonl")
parser.add_argument("--nom", default=None, help="Sous-chaîne à chercher dans le nom")
args = parser.parse_args()

with open(args.file, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        nom = obj.get("nom", "")
        if args.nom and args.nom.lower() not in nom.lower():
            continue
        pages = obj.get("pages", [])
        print(f"=== {nom} ===")
        print(f"  type de 'pages' : {type(pages).__name__}")

        if isinstance(pages, dict):
            print(f"  {len(pages)} clé(s) dans le dict")
            for i, (url, text) in enumerate(pages.items(), 1):
                if isinstance(text, dict):
                    t = text.get("text", "")
                    u = text.get("url", url)
                else:
                    t = text if isinstance(text, str) else ""
                    u = url
                preview = t[:80].replace("\n", " ") if t else ""
                print(f"   Page {i} url={u!r} len(text)={len(t)}  preview={preview!r}")
        elif isinstance(pages, list):
            print(f"  {len(pages)} élément(s) dans la liste")
            for i, p in enumerate(pages, 1):
                if isinstance(p, dict):
                    print(f"   Page {i} (dict) url={p.get('url','')!r} len(text)={len(p.get('text',''))}")
                else:
                    print(f"   Page {i} (str) valeur={p!r}  <-- pas d'objet dict, donc pas de texte")
        else:
            print(f"  ⚠️ type inattendu : {pages!r}")

        if not args.nom:
            break
            
