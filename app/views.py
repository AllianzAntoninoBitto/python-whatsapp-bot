import os
import logging
import json
from openai import OpenAI # Geändert: Importiere OpenAI-Client
import requests # Stelle sicher, dass dies oben steht, falls nicht schon

from flask import Blueprint, request, jsonify, current_app

from .decorators.security import signature_required
from .utils.whatsapp_utils import (
    process_whatsapp_message,
    is_valid_whatsapp_message,
)

# --- Globale Konfiguration / Prompt für den Bot ---
BOT_DESCRIPTION_PROMPT = """Du bist ein virtueller Berater der Allianz Versicherung Bitto in Emmendingen. Du antwortest freundlich, professionell und duzt den Nutzer - es sei denn, du wirst zuerst gesiezt. In dem Fall wechselst du respektvoll ins 'Sie'.
Deine Hauptsprache ist Deutsch. Wenn der Kunde in einer anderen Sprache schreibt, zum Beispiel Englisch, Türkisch oder Französisch, antwortest du in der selben Sprache, stets seriös.
Deine Informationen stammen ausschließlich aus:
- den bereitgestellten Allianz-Dokumenten
- offiziellen Webseiten der Allianz

Du gibst keine Inhalte weiter, die darüber hinausgehen. Wenn dir Informationen fehlen, sag das ehrlich. Du erfindest keine Fakten.

Du nennst **niemals konkrete Beitragshöhen**, außer wenn diese **explizit altersabhängig und klar aus den Dokumenten/Webseiten hervorgehen**.

Wenn eine Anfrage komplex ist oder nicht automatisch beantwortet werden kann, antworte zum Beispiel so:
"Das ist eine individuelle Frage. Ich leite das gern an eine*n Berater*in weiter - du wirst dann so schnell wie möglich kontaktiert."

Deine Aufgabe ist: verständlich, freundlich und verlässlich auf Allianz bezogene Fragen zu antworten - wie ein sympathischer, kompetenter Kundenberater."""

# --- OpenAI-Client initialisieren ---
# API-Schlüssel wird automatisch aus OPENAI_API_KEY Umgebungsvariable gelesen
client = OpenAI() # Dies ersetzt openai.api_key = os.getenv("OPENAI_API_KEY")

# --- Blueprint für Webhooks ---
webhook_blueprint = Blueprint("webhook", __name__)

# --- Funktion zur Verarbeitung eingehender Nachrichten ---
def handle_message():
    """
    Verarbeitet eingehende Webhook-Ereignisse von der WhatsApp API.
    """
    try:
        # Versuche, den JSON-Body zu erhalten.
        # request.get_json() kann None zurückgeben, wenn der Content-Type nicht 'application/json' ist
        # oder der Body leer ist.
        body = request.get_json(silent=True) # silent=True verhindert Fehler, wenn Body nicht JSON ist

        # Wenn kein Body vorhanden ist oder er leer ist, ist es oft ein Status-Update oder ein ungültiger Request.
        if not body:
            logging.info("Leerer oder ungültiger JSON-Body empfangen. Möglicherweise ein Status-Update ohne Inhalt oder ein ungültiger Request.")
            return jsonify({"status": "ok", "message": "No valid JSON body"}), 200

        # Überprüfen, ob es sich um ein WhatsApp-Statusupdate handelt
        if (
            body.get("entry", [{}])[0]
            .get("changes", [{}])[0]
            .get("value", {})
            .get("statuses")
        ):
            logging.info("WhatsApp-Statusupdate empfangen.")
            return jsonify({"status": "ok"}), 200

        # Überprüfen, ob es sich um eine gültige WhatsApp-Nachricht handelt
        if is_valid_whatsapp_message(body):
            # Extrahieren der eingehenden Nachricht
            # Sicherstellen, dass der Pfad zur Nachricht korrekt ist
            try:
                incoming_message = body["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"]
            except KeyError:
                logging.error("Fehler: Konnte Nachrichtentext nicht aus Payload extrahieren.")
                return jsonify({"status": "error", "message": "Nachrichtentext nicht gefunden"}), 400

            logging.info(f"Eingehende Nachricht: {incoming_message}")

            # OpenAI ChatCompletion mit neuem Client-Objekt
            response = client.chat.completions.create( # Geändert: client.chat.completions.create
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": BOT_DESCRIPTION_PROMPT
                    },
                    {"role": "user", "content": incoming_message}
                ]
            )
            # Extrahieren der Antwort aus dem neuen Objekt-Struktur
            reply = response.choices[0].message.content.strip() # Geändert: response.choices[0].message.content
            logging.info(f"Antwort des Bots: {reply}")

            # WhatsApp-Antwort vorbereiten und senden
            phone_number_id = body["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]
            from_number = body["entry"][0]["changes"][0]["value"]["messages"][0]["from"]

            url = f"https://graph.facebook.com/v17.0/{phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}",
                "Content-Type": "application/json"
            }
            data = {
                "messaging_product": "whatsapp",
                "to": from_number,
                "type": "text",
                "text": {
                    "body": reply
                }
            }

            response = requests.post(url, headers=headers, json=data)

            if response.status_code != 200:
                logging.error(f"Fehler beim Senden an WhatsApp: {response.status_code} - {response.text}")
            else:
                logging.info("Antwort erfolgreich an WhatsApp gesendet.")

            return jsonify({"status": "ok"}), 200
        else:
            # Wenn die Anfrage kein WhatsApp API-Ereignis ist, Fehler zurückgeben
            logging.info("Request ist kein gültiges WhatsApp API-Ereignis.")
            return (
                jsonify({"status": "error", "message": "Kein gültiges WhatsApp API-Ereignis"}),
                404,
            )

    except json.JSONDecodeError:
        logging.error("Fehler beim Dekodieren von JSON des Webhook-Payloads.")
        return jsonify({"status": "error", "message": "Ungültiges JSON bereitgestellt"}), 400
    except KeyError as ke:
        logging.error(f"Fehler: Fehlender Schlüssel im Payload - {ke}")
        return jsonify({"status": "error", "message": f"Fehlender Datenpunkt im Payload: {ke}"}), 400
    except Exception as e:
        # Dies ist der allgemeine Fehler-Handler für alle anderen Ausnahmen
        logging.error(f"Ein unerwarteter Fehler ist aufgetreten: {e}")
        return jsonify({"status": "error", "message": "Interner Serverfehler"}), 500


# --- Funktion zur Webhook-Verifizierung für WhatsApp ---
def verify():
    """
    Verarbeitet die Webhook-Verifizierungsanfrage von WhatsApp.
    """
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == current_app.config["VERIFY_TOKEN"]:
            logging.info("WEBHOOK_VERIFIED")
            return challenge, 200
        else:
            logging.info("VERIFICATION_FAILED")
            return jsonify({"status": "error", "message": "Verifizierung fehlgeschlagen"}), 403
    else:
        logging.info("FEHLENDE_PARAMETER")
        return jsonify({"status": "error", "message": "Fehlende Parameter"}), 400


# --- Routen-Definitionen für den Webhook ---
@webhook_blueprint.route("/webhook", methods=["GET"])
def webhook_get():
    """Route für GET-Anfragen zur Webhook-Verifizierung."""
    return verify()

@webhook_blueprint.route("/webhook", methods=["POST"])
@signature_required
def webhook_post():
    """Route für POST-Anfragen zur Nachrichtenverarbeitung."""
    return handle_message()
