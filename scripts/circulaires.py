#!/usr/bin/env python3
"""Récupère les circulaires de la semaine (Metro, Super C, Maxi, IGA) via Flipp
et écrit data/circulaires.json pour l'appli Panier.

Lancé chaque matin par GitHub Actions (.github/workflows/circulaires.yml).
Aucune dépendance : bibliothèque standard Python seulement.
"""
import json, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

CODE_POSTAL = "J3P1A1"          # Sorel-Tracy
MAGASINS = ["Metro", "Super C", "Maxi", "IGA"]
BASE = "https://backflipp.wishabi.com/flipp"
SORTIE = Path(__file__).resolve().parent.parent / "data" / "circulaires.json"
LB_PAR_KG = 2.20462


def lire(url, essais=3):
    for n in range(essais):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Panier/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # réseau capricieux : on réessaie
            if n == essais - 1:
                raise
            time.sleep(2 * (n + 1))


def nombre(txt):
    """'6,35' ou '6.35' -> 6.35"""
    if txt is None:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", str(txt))
    return float(m.group(0).replace(",", ".")) if m else None


# Formats : 650 g, 1,75 L, 18 kg, 12X355 ML, 12/341 ml, 2/707-725 g, 300/375 g
RX_FORMAT = re.compile(
    r"(?:(\d+)\s*[x×/]\s*)?(\d+(?:[.,]\d+)?)(?:\s*[-à]\s*\d+(?:[.,]\d+)?)?\s*(kg|g|ml|l)\b",
    re.I)


def format_produit(texte):
    """Retourne (quantité totale en g ou ml, 'g' ou 'ml', texte) pour le premier format trouvé.
    « 12/341 ml » = 12 x 341 ml; « 300/375 g » = choix entre 300 g et 375 g (on prend 300)."""
    if not texte:
        return None
    m = RX_FORMAT.search(texte)
    if not m:
        return None
    q = float(m.group(2).replace(",", "."))
    mult = 1
    if m.group(1):
        a = int(m.group(1))
        sep = texte[m.start():m.start(2)]
        if "/" in sep and not (a <= 48 and q >= a * 3):
            q, mult = float(a), 1          # 300/375 g : on garde le plus petit
        else:
            mult = a
    u = m.group(3).lower()
    if u == "kg":
        q, u = q * 1000, "g"
    elif u == "l":
        q, u = q * 1000, "ml"
    if q <= 0:
        return None
    return round(q * mult, 1), u, m.group(0).strip()


def normaliser(it, magasin, circulaire):
    prix = nombre(it.get("current_price") or it.get("price"))
    avant = (it.get("pre_price_text") or "").strip()
    apres = (it.get("price_text") or "").strip()
    desc = (it.get("description") or "").strip()

    # Prix multiple : « 2/ 5,00$ » -> 2,50$ chacun
    qte_mult = None
    m = re.match(r"^(\d+)\s*/", avant)
    if m and prix:
        qte_mult = int(m.group(1))
    prix_unite = round(prix / qte_mult, 2) if (prix and qte_mult) else prix

    # Unité de vente
    bas = apres.lower().replace(" ", "")
    if bas.startswith("/lb") or bas.startswith("lalb") or bas.startswith("lb"):
        unite = "lb"
    elif bas.startswith("/kg") or bas.startswith("lekg"):
        unite = "kg"
    elif "100g" in bas[:8]:
        unite = "100g"
    else:
        unite = "unité"

    # Prix régulier
    regulier = nombre(it.get("original_price"))
    if not regulier:
        m = re.search(r"r[ée]g\.?\s*:?\s*(\d+(?:[.,]\d+)?)", desc, re.I)
        if m:
            regulier = nombre(m.group(1))
    if regulier and qte_mult and regulier > prix_unite * 1.5:
        regulier = round(regulier / qte_mult, 2)

    # Le prix régulier est souvent donné au kg alors que le spécial est à la lb ou aux 100 g
    base_prix = prix_unite
    if regulier and prix_unite:
        r = regulier / prix_unite
        if unite == "100g" and r > 4:
            base_prix = prix_unite * 10
        elif unite == "lb" and r > 1.9:
            base_prix = prix_unite * LB_PAR_KG

    rabais = None
    if regulier and base_prix and regulier > base_prix:
        rabais = round(100 * (regulier - base_prix) / regulier)
    elif it.get("percent_off"):
        rabais = round(float(it["percent_off"]))
    elif it.get("discount"):
        rabais = round(float(it["discount"]))
    if rabais is not None and not (0 < rabais <= 75):
        rabais = None   # trop beau pour être vrai : probablement des unités différentes

    # Prix comparable : $/kg (poids) ou $/L (volume), sinon par unité
    comparable, base = None, None
    if prix_unite:
        if unite == "lb":
            comparable, base = prix_unite * LB_PAR_KG, "kg"
        elif unite == "kg":
            comparable, base = prix_unite, "kg"
        elif unite == "100g":
            comparable, base = prix_unite * 10, "kg"
        else:
            f = format_produit(it.get("name", "")) or format_produit(desc)
            if f:
                q, u, _ = f
                comparable = prix_unite / q * 1000
                base = "kg" if u == "g" else "L"
    fmt = format_produit(it.get("name", "")) or format_produit(desc)

    affichage = ""
    if prix:
        p = f"{prix:.2f}".replace(".", ",") + "$"
        affichage = (avant + " " + p if avant else p) + (" " + apres if apres else "")

    return {
        "id": it["id"],
        "magasin": magasin,
        "circulaire": circulaire,
        "nom": (it.get("name") or "").strip(),
        "marque": (it.get("brand") or "").strip() or None,
        "description": desc or None,
        "prix": prix_unite,
        "prix_affiche": affichage.strip() or None,
        "unite": unite,
        "regulier": regulier,
        "rabais": rabais,
        "format": fmt[2] if fmt else None,
        "prix_comparable": round(comparable, 2) if comparable else None,
        "base_comparable": base,
        "image": (it.get("cutout_image_url") or "").replace("http://", "https://") or None,
        "debut": (it.get("valid_from") or "")[:10],
        "fin": (it.get("valid_to") or "")[:10],
        "en_magasin_seulement": bool(it.get("in_store_only")),
    }


def main():
    liste = lire(f"{BASE}/flyers?locale=fr&postal_code={CODE_POSTAL}")
    circulaires = [f for f in liste["flyers"] if f.get("merchant") in MAGASINS]
    if not circulaires:
        sys.exit("Aucune circulaire trouvée : on garde l'ancien fichier.")

    bruts = []
    for f in circulaires:
        d = lire(f"{BASE}/flyers/{f['id']}?locale=fr")
        for it in d.get("items", []):
            bruts.append((it, f["merchant"], f.get("name") or ""))

    def detail(t):
        it, mag, circ = t
        try:
            x = lire(f"{BASE}/items/{it['id']}?locale=fr")["item"]
            x.setdefault("cutout_image_url", it.get("cutout_image_url"))
            x.setdefault("discount", it.get("discount"))
        except Exception:
            x = it
        return normaliser(x, mag, circ)

    with ThreadPoolExecutor(max_workers=8) as ex:
        produits = list(ex.map(detail, bruts))

    # Retirer bannières sans prix ni nom utile, et doublons
    vus, propres = set(), []
    for p in produits:
        if not p["nom"] or (not p["prix"] and not p["rabais"]):
            continue
        cle = (p["magasin"], p["nom"].lower(), p["prix"])
        if cle in vus:
            continue
        vus.add(cle)
        propres.append(p)

    sortie = {
        "mis_a_jour": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "code_postal": CODE_POSTAL,
        "circulaires": [
            {"id": f["id"], "magasin": f["merchant"], "nom": f.get("name"),
             "debut": f["valid_from"][:10], "fin": f["valid_to"][:10]}
            for f in circulaires],
        "produits": propres,
    }
    # Ne réécrire le fichier que si le contenu a changé (évite un envoi inutile chaque jour)
    if SORTIE.exists():
        try:
            ancien = json.loads(SORTIE.read_text(encoding="utf-8"))
            if ancien.get("produits") == sortie["produits"] and ancien.get("circulaires") == sortie["circulaires"]:
                print("Aucun changement dans les circulaires.")
                return
        except Exception:
            pass
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(sortie, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    par = {}
    for p in propres:
        par[p["magasin"]] = par.get(p["magasin"], 0) + 1
    print(f"{len(propres)} produits : {par}")


if __name__ == "__main__":
    main()
