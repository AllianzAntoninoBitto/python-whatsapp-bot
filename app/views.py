import os
openai_api_key = os.getenv("OPENAI_API_KEY")
import logging
import json
import openai
openai.api_key = openai_api_key
from flask import Blueprint, request, jsonify, current_app

from .decorators.security import signature_required
from .utils.whatsapp_utils import (
    process_whatsapp_message,
    is_valid_whatsapp_message,
)

webhook_blueprint = Blueprint("webhook", __name__)


def handle_message():
    """
    Handle incoming webhook events from the WhatsApp API.

    This function processes incoming WhatsApp messages and other events,
    such as delivery statuses. If the event is a valid message, it gets
    processed. If the incoming payload is not a recognized WhatsApp event,
    an error is returned.

    Every message send will trigger 4 HTTP requests to your webhook: message, sent, delivered, read.

    Returns:
        response: A tuple containing a JSON response and an HTTP status code.
    """
    body = request.get_json()
    incoming_message = "Was auch immer hier aus WhatsApp verarbeitet wird"

    # Beispielantwort mit GPT
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": (
                        BOT_DESCRIPTION_PROMPT = "Du bist ein virtueller Berater der Allianz Versicherung. Du antwortest freundlich, professionell und duzt den Nutzer - es sei denn, du wirst zuerst gesiezt. In dem Fall wechselst du respektvoll ins 'Sie'.

Deine Hauptsprache ist Deutsch. Wenn der Kunde in einer anderen Sprache schreibt, zum Beispiel Englisch, Türkisch oder Französisch, antwortest du in der selben Sprache, stets seriös.
Deine Informationen stammen ausschließlich aus:
- den bereitgestellten Allianz-Dokumenten
- offiziellen Webseiten der Allianz

Du gibst keine Inhalte weiter, die darüber hinausgehen. Wenn dir Informationen fehlen, sag das ehrlich. Du erfindest keine Fakten.

Du nennst **niemals konkrete Beitragshöhen**, außer wenn diese **explizit altersabhängig und klar aus den Dokumenten/Webseiten hervorgehen**.

Wenn eine Anfrage komplex ist oder nicht automatisch beantwortet werden kann, antworte zum Beispiel so:

"Das ist eine individuelle Frage. Ich leite das gern an eine*n Berater*in weiter - du wirst dann so schnell wie möglich kontaktiert."

Deine Aufgabe ist: verständlich, freundlich und verlässlich auf Allianz bezogene Fragen zu antworten - wie ein sympathischer, kompetenter Kundenberater."
                    )
                },
                {"role": "user", "content": incoming_message}
            ]
        )
        reply = response["choices"][0]["message"]["content"].strip()
        logging.info(f"Eingehende Nachricht: {incoming_message}")
logging.info(f"Antwort des Bots: {reply}")
       # WhatsApp-Antwort vorbereiten
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

        import requests
        requests.post(url, headers=headers, json=data)  
    except Exception as e:
        reply = "Entschuldige bitte, da ist ein Fehler aufgetreten. Einer unserer Mitarbeiter wird sich persönlich bei dir melden."
    # logging.info(f"request body: {body}")

    # Check if it's a WhatsApp status update
    if (
        body.get("entry", [{}])[0]
        .get("changes", [{}])[0]
        .get("value", {})
        .get("statuses")
    ):
        logging.info("Received a WhatsApp status update.")
        return jsonify({"status": "ok"}), 200

    try:
        if is_valid_whatsapp_message(body):
            process_whatsapp_message(body)
            return jsonify({"status": "ok"}), 200
        else:
            # if the request is not a WhatsApp API event, return an error
            return (
                jsonify({"status": "error", "message": "Not a WhatsApp API event"}),
                404,
            )
    except json.JSONDecodeError:
        logging.error("Failed to decode JSON")
        return jsonify({"status": "error", "message": "Invalid JSON provided"}), 400


# Required webhook verifictaion for WhatsApp
def verify():
    # Parse params from the webhook verification request
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    # Check if a token and mode were sent
    if mode and token:
        # Check the mode and token sent are correct
        if mode == "subscribe" and token == current_app.config["VERIFY_TOKEN"]:
            # Respond with 200 OK and challenge token from the request
            logging.info("WEBHOOK_VERIFIED")
            return challenge, 200
        else:
            # Responds with '403 Forbidden' if verify tokens do not match
            logging.info("VERIFICATION_FAILED")
            return jsonify({"status": "error", "message": "Verification failed"}), 403
    else:
        # Responds with '400 Bad Request' if verify tokens do not match
        logging.info("MISSING_PARAMETER")
        return jsonify({"status": "error", "message": "Missing parameters"}), 400


@webhook_blueprint.route("/webhook", methods=["GET"])
def webhook_get():
    return verify()

@webhook_blueprint.route("/webhook", methods=["POST"])
@signature_required
def webhook_post():
    return handle_message()


