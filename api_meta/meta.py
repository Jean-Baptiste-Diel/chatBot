import os
import requests

WHATSAPP_API_VERSION = "v21.0"
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")


def _post(payload: dict) -> dict:
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, json=payload, timeout=10)
    return response.json()


def send_text_message(to: str, body: str) -> dict:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    return _post(payload)


def send_list_message(to: str, body_text: str, button_text: str, rows: list, section_title: str = "Nos produits") -> dict:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body_text},
            "action": {
                "button": button_text,
                "sections": [{"title": section_title, "rows": rows}],
            },
        },
    }
    return _post(payload)


def _upload_media(file_bytes: bytes, filename: str, mime_type: str) -> str:
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    files = {"file": (filename, file_bytes, mime_type)}
    data = {"messaging_product": "whatsapp", "type": mime_type}
    response = requests.post(url, headers=headers, files=files, data=data, timeout=15)
    response.raise_for_status()
    return response.json()["id"]


def send_document(to: str, file_bytes: bytes, filename: str = "devis.pdf") -> dict:
    media_id = _upload_media(file_bytes, filename, "application/pdf")
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {"id": media_id, "filename": filename},
    }
    return _post(payload)


def send_typing_indicator(message_id: str) -> dict:
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    }
    return _post(payload)
