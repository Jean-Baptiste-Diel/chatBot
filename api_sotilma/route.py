import re
import threading
import unicodedata

import produit


def _sans_accents(texte: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


CHAMPS_ORDRE = ["nom_complet", "email", "telephone", "adresse", "quantite"]

QUESTIONS = {
    "nom_complet": "Quel est votre nom complet ?",
    "email": "Quelle est votre adresse email ?",
    "telephone": "Quel est votre numéro de téléphone ?",
    "adresse": "Quelle est votre adresse d'installation ?",
    "quantite": "Combien d'unités souhaitez-vous ?",
}

_devis_en_cours: dict[str, dict] = {}
_produit_en_cours: dict[str, dict] = {}
_lock = threading.Lock()


def obtenir_etat(phone_number: str) -> dict:
    with _lock:
        return dict(_devis_en_cours.get(phone_number, {}))


def mettre_a_jour_etat(phone_number: str, champ: str, valeur) -> None:
    with _lock:
        _devis_en_cours.setdefault(phone_number, {})[champ] = valeur


def reinitialiser_etat(phone_number: str) -> None:
    with _lock:
        _devis_en_cours.pop(phone_number, None)
        _produit_en_cours.pop(phone_number, None)


def devis_en_cours(phone_number: str) -> bool:
    with _lock:
        return phone_number in _produit_en_cours


def demarrer_devis(phone_number: str, slug: str) -> str:
    produit_choisi = produit.obtenir_produit(slug)
    reinitialiser_etat(phone_number)
    with _lock:
        _produit_en_cours[phone_number] = produit_choisi
    mettre_a_jour_etat(phone_number, "produit_id", produit_choisi["id"])
    return (
        f"Vous avez choisi : {produit_choisi['title']} ({produit_choisi['prix_str']}).\n"
        f"{QUESTIONS['nom_complet']}"
    )


def champ_attendu(phone_number: str) -> str | None:
    etat = obtenir_etat(phone_number)
    for champ in CHAMPS_ORDRE:
        if champ not in etat:
            return champ
    with _lock:
        produit_choisi = _produit_en_cours.get(phone_number, {})
    if produit_choisi.get("options") and "options" not in etat:
        return "options"
    return None


def _question_options(produit_choisi: dict) -> str:
    options = list(produit_choisi.get("options", {}).items())
    lignes = [f"{i}. {nom} (+{prix} FCFA)" for i, (nom, prix) in enumerate(options, start=1)]
    return (
        "Ce produit a des options. Répondez avec les numéros qui vous intéressent "
        "(exemple : 1,3), ou \"aucune\" :\n" + "\n".join(lignes)
    )


def _parser_options(reponse: str, produit_choisi: dict) -> list:
    reponse_norm = reponse.lower()
    if "aucun" in reponse_norm:
        return []
    cles = list(produit_choisi.get("options", {}))
    numeros = re.findall(r"\d+", reponse)
    if numeros:
        selection = []
        for n in numeros:
            index = int(n) - 1
            if 0 <= index < len(cles):
                selection.append(cles[index])
        if selection:
            return selection
    return [
        cle for cle in cles
        if cle.replace("_", " ") in reponse_norm or cle in reponse_norm
    ]


def _valider_champ(champ: str, valeur: str) -> bool:
    valeur = (valeur or "").strip()
    if champ == "email":
        return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", valeur))
    if champ == "telephone":
        return len(re.sub(r"\D", "", valeur)) >= 8
    if champ == "quantite":
        return valeur.isdigit()
    return bool(valeur)


def traiter_reponse(phone_number: str, champ: str, valeur) -> tuple[str, bytes | None]:
    if champ != "options" and not _valider_champ(champ, str(valeur)):
        return f"Je n'ai pas bien compris votre réponse. {QUESTIONS[champ]}", None

    mettre_a_jour_etat(phone_number, champ, valeur)

    champ_suivant = champ_attendu(phone_number)
    if champ_suivant is None:
        return _finaliser_devis(phone_number)
    if champ_suivant == "options":
        with _lock:
            produit_choisi = _produit_en_cours[phone_number]
        return _question_options(produit_choisi), None
    return QUESTIONS[champ_suivant], None


def _finaliser_devis(phone_number: str) -> tuple[str, bytes | None]:
    etat = obtenir_etat(phone_number)
    with _lock:
        produit_choisi = _produit_en_cours[phone_number]
    options = _parser_options(etat.get("options", ""), produit_choisi) if "options" in etat else []

    payload = {
        "nom_complet": etat["nom_complet"],
        "email": etat.get("email", ""),
        "telephone": etat["telephone"],
        "adresse": etat["adresse"],
        "produit_id": etat["produit_id"],
        "quantite": int(etat["quantite"]),
        "options": options,
        "source": "whatsapp",
    }
    try:
        devis = produit.creer_devis(payload)
        pdf = produit.obtenir_devis_pdf(devis["id"])
    except Exception:
        reinitialiser_etat(phone_number)
        return (
            "Désolé, une erreur est survenue lors de la création de votre devis. "
            "On reprend : quel est votre nom complet ?"
        ), None

    texte = (
        f"Votre devis est prêt ! Total : {devis['total']} FCFA "
        f"(avance {devis['avance']} FCFA, solde {devis['solde']} FCFA). "
        "Voici votre récapitulatif en PDF."
    )
    reinitialiser_etat(phone_number)
    return texte, pdf


CATEGORIES_CONNUES = ("camera", "vanne", "pack", "irrigation", "distribution", "pompe", "arroseur")
MARQUEURS_DEMANDE_EXPLICITE = ("prix", "combien", "coute", "tarif", "catalogue", "montre", "voir")


def _produit_correspond(p: dict, mot_cle: str) -> bool:
    champs = (p.get("categorie", ""), p.get("title", ""), p.get("card_explanation", ""))
    return any(mot_cle in _sans_accents(champ.lower()) for champ in champs)


def rechercher_produits(msg: str) -> list:
    if not msg:
        return []
    norm = _sans_accents(msg.lower())
    produits = produit.lister_produits()

    for p in produits:
        slug_mots = _sans_accents(p.get("slug", "").replace("-", " "))
        if slug_mots and slug_mots in norm:
            return [p]

    if not any(m in norm for m in MARQUEURS_DEMANDE_EXPLICITE):
        return []

    for cat in CATEGORIES_CONNUES:
        if cat in norm:
            correspondants = [p for p in produits if _produit_correspond(p, cat)]
            if correspondants:
                return correspondants

    return []


def formater_reponse_produit(p: dict) -> str:
    return f"{p['title']} : {p['prix_str']}\n{p.get('card_explanation', '')}"


_derniere_liste: dict[str, list] = {}
_lock_liste = threading.Lock()


def memoriser_derniere_liste(phone_number: str, produits: list) -> None:
    with _lock_liste:
        _derniere_liste[phone_number] = produits


def resoudre_selection_numero(phone_number: str, msg: str) -> str | None:
    msg = (msg or "").strip()
    if not msg.isdigit():
        return None
    with _lock_liste:
        produits = _derniere_liste.get(phone_number)
        if not produits:
            return None
        index = int(msg) - 1
        if 0 <= index < len(produits):
            slug = produits[index]["slug"]
            _derniere_liste.pop(phone_number, None)
            return slug
    return None


def formater_liste_produits(produits: list) -> str:
    lignes = [f"{i}. {p['title']} : {p['prix_str']}" for i, p in enumerate(produits, start=1)]
    return (
        "Voici ce qu'on propose :\n" + "\n".join(lignes) +
        "\n\nRépondez avec le numéro qui vous intéresse."
    )


def construire_lignes_produits(produits: list) -> tuple[list, bool]:
    tronque = len(produits) > 10
    rows = []
    for p in produits[:10]:
        rows.append({
            "id": p["slug"],
            "title": _tronquer(p.get("title", ""), 24),
            "description": _tronquer(p.get("row_description", ""), 72),
        })
    return rows, tronque


def _tronquer(texte: str, max_len: int) -> str:
    if not texte:
        return ""
    if len(texte) <= max_len:
        return texte
    return texte[:max_len - 1].rsplit(" ", 1)[0] + "…"
