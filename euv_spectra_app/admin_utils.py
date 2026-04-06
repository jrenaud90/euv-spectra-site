import base64
import json
import secrets
import time
from functools import wraps

from bson import json_util
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from flask import current_app, flash, redirect, session, url_for

from euv_spectra_app.extensions import db


ADMIN_AUTHENTICATED_KEY = "pegasus_admin_authenticated"
ADMIN_AUTHENTICATED_AT_KEY = "pegasus_admin_authenticated_at"
ADMIN_CHALLENGE_KEY = "pegasus_admin_challenge"


def admin_auth_configured():
    try:
        return bool(_load_public_key_text())
    except OSError:
        return False


def _load_public_key_text():
    key_text = current_app.config.get("ADMIN_PUBLIC_KEY")
    key_path = current_app.config.get("ADMIN_PUBLIC_KEY_PATH")

    if key_text:
        return key_text.strip().encode("utf-8")

    if key_path:
        with open(key_path, "rb") as key_file:
            return key_file.read().strip()

    return None


def load_admin_public_key():
    try:
        key_bytes = _load_public_key_text()
    except OSError as exc:
        raise ValueError("Admin public key could not be read.") from exc

    if not key_bytes:
        raise ValueError("Admin public key is not configured.")

    loaders = (
        serialization.load_pem_public_key,
        serialization.load_ssh_public_key,
    )
    for loader in loaders:
        try:
            return loader(key_bytes)
        except ValueError:
            continue

    raise ValueError("Unsupported admin public key format.")


def issue_admin_challenge(force=False):
    challenge_payload = session.get(ADMIN_CHALLENGE_KEY)
    ttl_seconds = current_app.config.get("ADMIN_CHALLENGE_TTL_SECONDS", 300)
    now = int(time.time())

    if not force and challenge_payload and now - challenge_payload["issued_at"] <= ttl_seconds:
        return challenge_payload["value"]

    challenge = secrets.token_urlsafe(48)
    session[ADMIN_CHALLENGE_KEY] = {"value": challenge, "issued_at": now}
    return challenge


def verify_admin_signature(signature_b64):
    challenge_payload = session.get(ADMIN_CHALLENGE_KEY)
    if not challenge_payload:
        raise ValueError("Admin challenge is missing. Refresh and try again.")

    ttl_seconds = current_app.config.get("ADMIN_CHALLENGE_TTL_SECONDS", 300)
    now = int(time.time())
    if now - challenge_payload["issued_at"] > ttl_seconds:
        raise ValueError("Admin challenge expired. Refresh and sign a new challenge.")

    try:
        signature = base64.b64decode(signature_b64.strip(), validate=True)
    except Exception as exc:
        raise ValueError("Signature must be base64 encoded.") from exc

    message = challenge_payload["value"].encode("utf-8")
    public_key = load_admin_public_key()

    try:
        if isinstance(public_key, ed25519.Ed25519PublicKey):
            public_key.verify(signature, message)
        elif isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        else:
            raise ValueError("Unsupported public key type.")
    except InvalidSignature as exc:
        raise ValueError("Signature verification failed.") from exc


def mark_admin_authenticated():
    session[ADMIN_AUTHENTICATED_KEY] = True
    session[ADMIN_AUTHENTICATED_AT_KEY] = int(time.time())
    session.pop(ADMIN_CHALLENGE_KEY, None)


def clear_admin_session():
    session.pop(ADMIN_AUTHENTICATED_KEY, None)
    session.pop(ADMIN_AUTHENTICATED_AT_KEY, None)
    session.pop(ADMIN_CHALLENGE_KEY, None)


def is_admin_authenticated():
    if not session.get(ADMIN_AUTHENTICATED_KEY):
        return False

    authenticated_at = session.get(ADMIN_AUTHENTICATED_AT_KEY)
    if not authenticated_at:
        return False

    ttl_seconds = current_app.config.get("ADMIN_SESSION_MINUTES", 30) * 60
    if int(time.time()) - authenticated_at > ttl_seconds:
        clear_admin_session()
        return False

    return True


def admin_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not admin_auth_configured():
            flash("Admin authentication is not configured for this deployment.", "danger")
            return redirect(url_for("main.homepage"))

        if not is_admin_authenticated():
            flash("Admin authentication is required.", "warning")
            return redirect(url_for("main.admin_login"))

        return view_func(*args, **kwargs)

    return wrapped_view


def get_allowed_collection_names():
    configured = current_app.config.get("ADMIN_ALLOWED_COLLECTIONS", "")
    configured_names = [name.strip() for name in configured.split(",") if name.strip()]
    existing_names = [name for name in db.list_collection_names() if not name.startswith("system.")]

    ordered_names = []
    for name in configured_names + sorted(existing_names):
        if name not in ordered_names:
            ordered_names.append(name)
    return ordered_names


def get_collection_summaries():
    summaries = []
    for name in get_allowed_collection_names():
        collection = db.get_collection(name)
        sample = collection.find_one()
        sample_keys = []
        if sample:
            sample_keys = [key for key in sample.keys() if key != "_id"][:6]

        summaries.append(
            {
                "name": name,
                "documents": collection.count_documents({}),
                "sample_keys": sample_keys,
            }
        )

    return summaries


def parse_json_document(raw_text):
    parsed = json_util.loads(raw_text)
    if not isinstance(parsed, dict):
        raise ValueError("JSON filter must decode to an object.")
    return parsed


def parse_uploaded_documents(upload_storage):
    payload = upload_storage.read()
    upload_storage.stream.seek(0)

    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Upload must be valid UTF-8 text.") from exc

    stripped = decoded.strip()
    if not stripped:
        raise ValueError("Upload file is empty.")

    try:
        parsed = json_util.loads(stripped)
        if isinstance(parsed, list):
            if not all(isinstance(item, dict) for item in parsed):
                raise ValueError("Each uploaded document must decode to an object.")
            return parsed
        if isinstance(parsed, dict):
            if isinstance(parsed.get("documents"), list):
                if not all(isinstance(item, dict) for item in parsed["documents"]):
                    raise ValueError("Each uploaded document must decode to an object.")
                return parsed["documents"]
            return [parsed]
    except json.JSONDecodeError:
        pass

    documents = []
    for line_number, line in enumerate(stripped.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            parsed_line = json_util.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_number}.") from exc
        if not isinstance(parsed_line, dict):
            raise ValueError(f"Line {line_number} must decode to an object.")
        documents.append(parsed_line)

    if not documents:
        raise ValueError("Upload did not contain any JSON documents.")

    return documents
