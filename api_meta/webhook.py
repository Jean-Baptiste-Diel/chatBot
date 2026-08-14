import os
import threading
from flask import Blueprint, request, jsonify
from meta import send_text_message, send_list_message, send_document, send_typing_indicator
from gemini import generate_reply, extraire_champ, enregistrer_echange
from produit import lister_produits
import route

webhook_bp = Blueprint("webhook", __name__)
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

FALLBACK_ERROR = "Désolé, je rencontre un problème technique. Réessayez dans un instant."

LISTE_PRODUITS_BUTTON = "Voir les produits"

ANNULATION_MOTS = ("annuler", "annule", "stop", "recommencer", "recommence")

_messages_traites: set[str] = set()
MESSAGES_TRAITES_MAX = 500
_dedup_lock = threading.Lock()


def _est_duplique(message_id: str) -> bool:
    if not message_id:
        return False
    with _dedup_lock:
        if message_id in _messages_traites:
            return True
        _messages_traites.add(message_id)
        if len(_messages_traites) > MESSAGES_TRAITES_MAX:
            _messages_traites.pop()
        return False


def _est_annulation(msg: str) -> bool:
    norm = (msg or "").lower().strip()
    return any(mot in norm for mot in ANNULATION_MOTS)


def _envoyer_liste_produits(to: str, body_text: str) -> None:
    produits = lister_produits()
    rows, tronque = route.construire_lignes_produits(produits)
    if tronque:
        body_text += "\n\nAperçu de nos modèles les plus demandés. Dites-moi ce qui vous intéresse pour voir le reste."
    send_list_message(to, body_text, LISTE_PRODUITS_BUTTON, rows)


@webhook_bp.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Token invalide", 403


@webhook_bp.route("/webhook", methods=["POST"])
def receive():
    body = request.get_json(silent=True) or {}
    try:
        value = body["entry"][0]["changes"][0]["value"]
        messages = value.get("messages")
        if not messages:
            return jsonify({"status": "ignored"}), 200
        message = messages[0]
        from_number = message.get("from")
        message_id = message.get("id")
        message_type = message.get("type")

        if _est_duplique(message_id):
            return jsonify({"status": "duplicate_ignored"}), 200

        text_body = ""
        list_reply_id = None
        if message_type == "text":
            text_body = message.get("text", {}).get("body", "")
        elif message_type == "interactive":
            list_reply_id = message.get("interactive", {}).get("list_reply", {}).get("id")

        if from_number and (text_body or list_reply_id):
            threading.Thread(
                target=_process_and_reply,
                args=(from_number, text_body, list_reply_id, message_id),
                daemon=True,
            ).start()
    except (IndexError, KeyError):
        pass
    return jsonify({"status": "ok"}), 200


def _process_and_reply(to: str, text_body: str, list_reply_id: str | None, message_id: str | None = None) -> None:
    if message_id:
        try:
            send_typing_indicator(message_id)
        except Exception:
            pass

    try:
        if list_reply_id:
            reply_text = route.demarrer_devis(to, list_reply_id)
            send_text_message(to, reply_text)
            enregistrer_echange(to, f"[a choisi un produit dans la liste : {list_reply_id}]", reply_text)
            return

        if route.devis_en_cours(to):
            if _est_annulation(text_body):
                route.reinitialiser_etat(to)
                reply_text = "D'accord, j'annule cette demande. N'hésitez pas à revenir si besoin."
                send_text_message(to, reply_text)
                enregistrer_echange(to, text_body, reply_text)
                return
            champ = route.champ_attendu(to)
            valeur = text_body if champ == "options" else extraire_champ(champ, text_body)
            reply_text, pdf = route.traiter_reponse(to, champ, valeur)
            send_text_message(to, reply_text)
            enregistrer_echange(to, text_body, reply_text)
            if pdf:
                send_document(to, pdf)
            return

        slug_choisi = route.resoudre_selection_numero(to, text_body)
        if slug_choisi:
            reply_text = route.demarrer_devis(to, slug_choisi)
            send_text_message(to, reply_text)
            enregistrer_echange(to, text_body, reply_text)
            return

        produits_trouves = route.rechercher_produits(text_body)
        if len(produits_trouves) == 1:
            reply = route.formater_reponse_produit(produits_trouves[0])
            enregistrer_echange(to, text_body, reply)
        elif len(produits_trouves) > 1:
            reply = route.formater_liste_produits(produits_trouves)
            route.memoriser_derniere_liste(to, produits_trouves)
            enregistrer_echange(to, text_body, reply)
        else:
            reply, intent = generate_reply(to, text_body)
            if intent == "show_catalogue":
                send_text_message(to, reply)
                _envoyer_liste_produits(to, "Voici notre catalogue :")
                return
    except Exception as e:
        print(f"[bot] erreur traitement : {type(e).__name__}: {e}")
        reply = FALLBACK_ERROR
    send_text_message(to, reply)
