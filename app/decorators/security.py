import json
import logging
import hmac
import hashlib
from functools import wraps
from flask import current_app, request, jsonify

def validate_signature(raw_payload_string, signature):
    """
    Validate the incoming raw payload string's signature against our expected signature.
    WhatsApp signs the raw JSON string directly.
    """
    # Zuerst den rohen Payload-String in Bytes umwandeln, wie WhatsApp ihn gesendet hat
    raw_payload_bytes = raw_payload_string.encode("utf-8") # WICHTIG: Hier utf-8 verwenden

    app_secret_bytes = bytes(current_app.config["APP_SECRET"], "latin-1") # Dein App-Geheimnis in Bytes

    # Die erwartete Signatur vom rohen Payload berechnen
    expected_signature = hmac.new(
        app_secret_bytes,
        msg=raw_payload_bytes, # Hier die rohen Bytes verwenden
        digestmod=hashlib.sha256
    ).hexdigest()

    # Signaturen vergleichen
    return hmac.compare_digest(expected_signature, signature)


def signature_required(f):
    """
    Decorator to ensure that the incoming requests to our webhook are valid and signed with the correct signature.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # WhatsApp sendet die Signatur im Header als "sha256=xxx". Wir schneiden "sha256=" ab.
        received_signature = request.headers.get("X-Hub-Signature-256", "")[7:]

        # Den rohen Payload-Body als String dekodieren, um ihn an validate_signature zu übergeben.
        # request.data ist bereits bytes, wir müssen es dekodieren, um es als string zu übergeben
        raw_payload_string = request.data.decode("utf-8")

        # Die Signatur mit dem rohen Payload-String validieren
        if not validate_signature(raw_payload_string, received_signature):
            logging.info("Signature verification failed! (Calculated mismatch)")
            return jsonify({"status": "error", "message": "Invalid signature"}), 403

        # Wenn die Signatur gültig ist, die ursprüngliche Funktion ausführen.
        # Der request.data und request.json (falls Content-Type application/json ist)
        # sind immer noch für die umwickelte Funktion (handle_message) verfügbar.
        return f(*args, **kwargs)

    return decorated_function
