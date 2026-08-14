import requests
from config import PRODUIT_API_URL, PRODUIT_API_KEY

HEADERS = {"X-API-Key": PRODUIT_API_KEY}


def lister_produits(q: str = None, categorie: str = None) -> list:
    params = {k: v for k, v in {"q": q, "categorie": categorie}.items() if v}
    response = requests.get(f"{PRODUIT_API_URL}/produit/", headers=HEADERS, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def obtenir_produit(id_ou_slug) -> dict:
    response = requests.get(f"{PRODUIT_API_URL}/produit/{id_ou_slug}", headers=HEADERS, timeout=10)
    response.raise_for_status()
    return response.json()


def creer_devis(payload: dict) -> dict:
    response = requests.post(f"{PRODUIT_API_URL}/devis/", headers=HEADERS, json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


def obtenir_devis_pdf(devis_id) -> bytes:
    response = requests.get(f"{PRODUIT_API_URL}/devis/{devis_id}/pdf", headers=HEADERS, timeout=10)
    response.raise_for_status()
    return response.content
