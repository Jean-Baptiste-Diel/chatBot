import os
import re
import threading
import time
from pathlib import Path
from google import genai
from google.genai import types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.3"))
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "1500"))

client = genai.Client(api_key=GEMINI_API_KEY)

_PROMPT_PATH = Path(__file__).resolve().parent / "prompt.txt"

RETRYABLE_CODES = (429, 503)
MAX_TENTATIVES = 3

HISTORIQUE_MAX_TOURS = 20
_historique: dict[str, list] = {}
_lock = threading.Lock()

_INTENT_PATTERN = re.compile(r"\[INTENT:(\w+)\]\s*$")

_LIBELLES_CHAMPS = {
    "nom_complet": "le nom complet de la personne",
    "email": "l'adresse email",
    "telephone": "le numero de telephone",
    "adresse": "l'adresse d'installation",
    "quantite": "la quantite (juste le nombre, en chiffres)",
}


def _charger_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _ajouter_historique(phone_number: str, role: str, texte: str) -> None:
    with _lock:
        tours = _historique.setdefault(phone_number, [])
        tours.append(types.Content(role=role, parts=[types.Part(text=texte)]))
        if len(tours) > HISTORIQUE_MAX_TOURS:
            del tours[: len(tours) - HISTORIQUE_MAX_TOURS]


def reinitialiser_historique(phone_number: str) -> None:
    with _lock:
        _historique.pop(phone_number, None)


def enregistrer_echange(phone_number: str, message_utilisateur: str, reponse_bot: str) -> None:
    _ajouter_historique(phone_number, "user", message_utilisateur)
    _ajouter_historique(phone_number, "model", reponse_bot)


def generate_reply(phone_number: str, user_message: str) -> tuple[str, str | None]:
    with _lock:
        contents = list(_historique.get(phone_number, [])) + [
            types.Content(role="user", parts=[types.Part(text=user_message)])
        ]
    for tentative in range(1, MAX_TENTATIVES + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=_charger_prompt(),
                    temperature=GEMINI_TEMPERATURE,
                    max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
                ),
            )
            texte_brut = response.text
            intent = None
            match = _INTENT_PATTERN.search(texte_brut)
            if match:
                intent = match.group(1)
                texte_brut = _INTENT_PATTERN.sub("", texte_brut).strip()

            enregistrer_echange(phone_number, user_message, texte_brut)
            return texte_brut, intent
        except Exception as e:
            code = getattr(e, "code", None)
            if code not in RETRYABLE_CODES or tentative == MAX_TENTATIVES:
                raise
            time.sleep(2 ** (tentative - 1))


def extraire_champ(nom_champ: str, message: str) -> str:
    consigne = _LIBELLES_CHAMPS.get(nom_champ, nom_champ)
    prompt = (
        f"Extrait uniquement {consigne} depuis ce message, sans aucun texte "
        f"autour, juste la valeur brute :\n\n{message}"
    )
    for tentative in range(1, MAX_TENTATIVES + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0, max_output_tokens=60),
            )
            valeur = (response.text or "").strip()
            return valeur if valeur else message
        except Exception as e:
            code = getattr(e, "code", None)
            if code not in RETRYABLE_CODES or tentative == MAX_TENTATIVES:
                return message
            time.sleep(2 ** (tentative - 1))
    return message
