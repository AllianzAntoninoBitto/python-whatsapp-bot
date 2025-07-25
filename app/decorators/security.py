import json
import logging
import hmac
import hashlib
from functools import wraps # Import hinzugefügt
from flask import current_app, request, jsonify # request und jsonify hinzugefügt

def validate_signature(payload, signature):
    """
    Validate the incoming payload's signature against our expected signature.
    """ # Docstring korrekt geschlossen und Funktion beginnt hier
    if not isinstance(payload, dict):
        logging.error(f"Ungültiger payload.type: {type(payload)} = Inhalt: {payload} )")
        return False

    app_secret_bytes = bytes(current_app.config["APP_SECRET"], "latin-1")

    msg = json.dumps(payload,
                     separators=(',', ':'),
                     sort_keys=True).encode("utf-8")

    expected_signature = hmac.new(
        app_secret_bytes,
        msg=msg,
        digestmod=hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)


def signature_required(f):
    """
    Decorator to ensure that the incoming requests to our webhook are valid and signed with the correct signature.
    """
    # Diese Zeilen müssen eingerückt sein, um Teil der Funktion signature_required zu sein
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Korrigierte Zeile: Extrahieren der Signatur und Entfernen des Präfixes "sha256="
        # Die ursprüngliche Zeile war unvollständig und die Slicing-Syntax war falsch aufgeteilt
        signature = request.headers.get("X-Hub-Signature-256", "")[7:]

        if not validate_signature(request.data.decode("utf-8"), signature):
            logging.info("Signature verification failed!")
            return jsonify({"status": "error", "message": "Invalid signature"}), 403
        return f(*args, **kwargs)

    # Diese Zeile muss auf derselben Einrückungsebene wie @wraps(f) sein,
    # um das Ergebnis des Decorators zurückzugeben.
    return decorated_function
