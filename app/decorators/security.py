import json
import logging
import hmac
import hashlib
from flask import current_app


def validate_signature(payload, signature):
    """
    Validate the incoming payload's signature against our expected signature
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

    @wraps(f)
    def decorated_function(*args, **kwargs):
        signature = request.headers.get("X-Hub-Signature-256", "")[
            7:
        ]  # Removing 'sha256='
        if not validate_signature(request.data.decode("utf-8"), signature):
            logging.info("Signature verification failed!")
            return jsonify({"status": "error", "message": "Invalid signature"}), 403
        return f(*args, **kwargs)

    return decorated_function
