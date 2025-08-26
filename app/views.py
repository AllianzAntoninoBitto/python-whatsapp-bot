import os
import logging
import json
from openai import OpenAI
import requests
from flask import Blueprint, request, jsonify, current_app
from .decorators.security import signature_required
from .utils.whatsapp_utils import (
    process_whatsapp_message,
    is_valid_whatsapp_message,
)

# --- OpenAI-Client initialisieren ---
client = OpenAI()

# --- Assistants API: Speicher für Threads (In-Memory - NUR ZUM TESTEN!) ---
user_threads = {}

# --- DEINE ASSISTANT ID HIER EINFÜGEN ---
ASSISTANT_ID = "asst_1MqcBju8sZsGXqXLfmfVQotP"

# --- Blueprint für Webhooks ---
webhook_blueprint = Blueprint("webhook", __name__)

# --- Funktion zur Verarbeitung eingehender Nachrichten ---
def handle_message():
    try:
        body = request.get_json(silent=True)
        if not body:
            logging.info("Leerer oder ungültiger JSON-Body empfangen. Möglicherweise ein Status-Update ohne Inhalt oder ein ungültiger Request.")
            return jsonify({"status": "ok", "message": "No valid JSON body"}), 200

        if (
            body.get("entry", [{}])[0]
            .get("changes", [{}])[0]
            .get("value", {})
            .get("statuses")
        ):
            logging.info("WhatsApp-Statusupdate empfangen.")
            return jsonify({"status": "ok"}), 200

        if is_valid_whatsapp_message(body):
            message_body = body["entry"][0]["changes"][0]["value"]["messages"][0]
            from_number = message_body["from"]
            message_type = message_body["type"]

            incoming_message_text = ""

            # Überprüfen des Nachrichtentyps und Extrahieren des Inhalts
            if message_type == "text":
                incoming_message_text = message_body["text"]["body"]
            elif message_type == "audio":
                audio_media_id = message_body["audio"]["id"]
                logging.info(f"Sprachnachricht empfangen mit Media ID: {audio_media_id}")
                
                # Herunterladen der Sprachnachricht von der WhatsApp API
                media_url = f"https://graph.facebook.com/v17.0/{audio_media_id}"
                headers = {
                    "Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}"
                }
                
                media_response = requests.get(media_url, headers=headers)
                
                if media_response.status_code == 200:
                    # Der Content-Type Header enthält den Medientyp und das Format, z.B. audio/ogg
                    # Der Wert ist im 'Location'-Header der Antwort, den wir für den Download benötigen
                    download_url = media_response.json().get('url')
                    
                    if download_url:
                        audio_data_response = requests.get(download_url, headers=headers)
                        
                        if audio_data_response.status_code == 200:
                            # Transkribieren der Audiodaten mit der OpenAI Whisper API
                            audio_file = audio_data_response.content
                            try:
                                # Die Whisper API erwartet den Dateinamen im 'files'-Parameter
                                # und den 'model'-Namen.
                                whisper_response = client.audio.transcriptions.create(
                                    model="whisper-1",
                                    file=("audio.ogg", audio_file),
                                    response_format="text"
                                )
                                incoming_message_text = whisper_response.text # Hier ist der transkribierte Text
                                logging.info(f"Transkribierte Sprachnachricht: {incoming_message_text}")
                            except Exception as e:
                                logging.error(f"Fehler bei der Transkription: {e}")
                                incoming_message_text = "Transkription fehlgeschlagen."
                        else:
                            logging.error(f"Fehler beim Herunterladen der Sprachdatei: {audio_data_response.status_code}")
                            incoming_message_text = "Fehler beim Herunterladen der Sprachdatei."
                    else:
                        logging.error("Download URL für Sprachnachricht nicht gefunden.")
                        incoming_message_text = "Fehler beim Abrufen der Sprachnachricht."
                else:
                    logging.error(f"Fehler beim Abrufen der Media-Informationen von WhatsApp: {media_response.status_code}")
                    incoming_message_text = "Fehler beim Verarbeiten der Sprachnachricht."
            else:
                logging.info(f"Nachrichtentyp '{message_type}' wird noch nicht unterstützt.")
                return jsonify({"status": "ok"}), 200

            if not incoming_message_text:
                logging.info("Nachricht ohne Textinhalt verarbeitet (z.B. eine leere Audionachricht).")
                return jsonify({"status": "ok"}), 200

            # --- Gedächtnis-Logik mit OpenAI Assistants API ---
            thread_id = user_threads.get(from_number)
            if not thread_id:
                logging.info(f"Neuer Thread für Benutzer {from_number} wird erstellt.")
                thread = client.beta.threads.create()
                thread_id = thread.id
                user_threads[from_number] = thread_id

            client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=incoming_message_text
            )
            logging.info(f"Nachricht zu Thread {thread_id} hinzugefügt.")

            run = client.beta.threads.runs.create_and_poll(
                thread_id=thread_id,
                assistant_id=ASSISTANT_ID
            )

            messages = client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit="1")
            
            reply_text = "Entschuldige, ich konnte keine Antwort generieren."

            for msg in messages.data:
                if msg.role == "assistant" and msg.run_id == run.id:
                    for content_block in msg.content:
                        if content_block.type == "text":
                            reply_text = content_block.text.value
                            break
                    if reply_text:
                        break

            # Korrektur für Formatierungen
            reply_text = reply_text.replace('\\n', '\n')
            reply_parts = reply_text.split('[NL]')
            
            logging.info(f"Antwort des Bots: {reply_text}")

            phone_number_id = body["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]
            
            url = f"https://graph.facebook.com/v17.0/{phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}",
                "Content-Type": "application/json"
            }
            
            for part in reply_parts:
                if part.strip():
                    data = {
                        "messaging_product": "whatsapp",
                        "to": from_number,
                        "type": "text",
                        "text": {"body": part.strip()}
                    }
                    whatsapp_send_response = requests.post(url, headers=headers, json=data)
                    logging.info(f"WhatsApp Send API Status: {whatsapp_send_response.status_code}")
                    logging.info(f"WhatsApp Send API Body: {whatsapp_send_response.text}")

            return jsonify({"status": "ok"}), 200
        else:
            logging.info("Request ist kein gültiges WhatsApp API-Ereignis.")
            return (
                jsonify({"status": "error", "message": "Kein gültiges WhatsApp API-Ereignis"}),
                404,
            )

    except json.JSONDecodeError:
        logging.error("Fehler beim Dekodieren von JSON des Webhook-Payloads.")
        return jsonify({"status": "error", "message": "Ungültiges JSON bereitgestellt"}), 400
    except KeyError as ke:
        logging.error(f"Fehler: Fehlender Schlüssel im Payload - {ke}. Vollständiger Body: {body}")
        return jsonify({"status": "error", "message": f"Fehlender Datenpunkt im Payload: {ke}"}), 400
    except Exception as e:
        logging.error(f"Ein unerwarteter Fehler ist aufgetreten: {e}")
        return jsonify({"status": "error", "message": "Interner Serverfehler"}), 500

def verify():
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

@webhook_blueprint.route("/webhook", methods=["GET"])
def webhook_get():
    return verify()

@webhook_blueprint.route("/webhook", methods=["POST"])
@signature_required
def webhook_post():
    return handle_message()
