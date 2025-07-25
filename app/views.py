import os
import logging
import json
import openai
import requests # Neu hinzugefügt, falls nicht schon vorhanden

from flask import Blueprint, request, jsonify, current_app

from .decorators.security import signature_required
from .utils.whatsapp_utils import (
    process_whatsapp_message, # Beibehalten, falls es andere Funktionen hat
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

# --- API-Schlüssel initialisieren ---
openai.api_key = os.getenv("OPENAI_API_KEY") # Sicherstellen, dass dies von Render kommt

# --- Blueprint für Webhooks ---
webhook_blueprint = Blueprint("webhook", __name__)

# --- Funktion zur Verarbeitung eingehender Nachrichten ---
def handle_message():
    """
    Verarbeitet eingehende Webhook-Ereignisse von der WhatsApp API.

    Diese Funktion verarbeitet eingehende WhatsApp-Nachrichten und andere Ereignisse,
    wie z.B. Zustellungsstatus. Wenn das Ereignis eine gültige Nachricht ist, wird sie
    verarbeitet. Wenn die eingehende Payload kein erkanntes WhatsApp-Ereignis ist,
    wird ein Fehler zurückgegeben.

    Jede gesendete Nachricht löst 4 HTTP-Anfragen an deinen Webhook aus: message, sent, delivered, read.

    Rückgaben:
        response: Ein Tupel, das eine JSON-Antwort und einen HTTP-Statuscode enthält.
    """
    try:
        body = request.get_json()

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
            # Annahme: Die Nachricht ist im Textfeld des ersten Messages-Objekts
            incoming_message = body["entry"][0]["changes"][0]["value"]["messages"][0]["text"]
            logging.info(f"Eingehende Nachricht: {incoming_message}")

            # Optional: Wenn process_whatsapp_message(body) andere Aufgaben hat, rufe es hier auf
            # process_whatsapp_message(body)

            # Beispielantwort mit GPT
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": BOT_DESCRIPTION_PROMPT # Referenz auf die globale Variable
                    },
                    {"role": "user", "content": incoming_message}
                ]
            )
            reply = response["choices"][0]["message"]["content"].strip()
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
                "text": {"body": reply}
            }

            requests.post(url, headers=headers, json=data)

            return jsonify({"status": "ok"}), 200
        else:
            # Wenn die Anfrage kein WhatsApp API-Ereignis ist, Fehler zurückgeben
            return (
                jsonify({"status": "error", "message": "Kein WhatsApp API-Ereignis"}),
                404,
            )

    except json.JSONDecodeError:
        logging.error("Fehler beim Dekodieren von JSON.")
        return jsonify({"status": "error", "message": "Ungültiges JSON bereitgestellt"}), 400
    except Exception as e:
        # Dies ist der allgemeine Fehler-Handler für alle anderen Ausnahmen
        logging.error(f"Ein unerwarteter Fehler ist aufgetreten: {e}")
        # Optional: Sende eine generische Fehlermeldung an den Benutzer
        # Hier ist es schwierig, die from_number zu bekommen, wenn der Fehler früh auftritt
        # Daher geben wir nur einen Serverfehler zurück.
        return jsonify({"status": "error", "message": "Interner Serverfehler"}), 500


# --- Funktion zur Webhook-Verifizierung für WhatsApp ---
def verify():
    """
    Verarbeitet die Webhook-Verifizierungsanfrage von WhatsApp.
    """
    # Parameter aus der Webhook-Verifizierungsanfrage parsen
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    # Überprüfen, ob ein Token und Modus gesendet wurden
    if mode and token:
        # Überprüfen, ob Modus und gesendeter Token korrekt sind
        if mode == "subscribe" and token == current_app.config["VERIFY_TOKEN"]:
            # Mit 200 OK und Challenge-Token aus der Anfrage antworten
            logging.info("WEBHOOK_VERIFIED")
            return challenge, 200
        else:
            # Antwortet mit '403 Forbidden', wenn die Verifizierungs-Tokens nicht übereinstimmen
            logging.info("VERIFICATION_FAILED")
            return jsonify({"status": "error", "message": "Verifizierung fehlgeschlagen"}), 403
    else:
        # Antwortet mit '400 Bad Request', wenn Parameter fehlen
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


