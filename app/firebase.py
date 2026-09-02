"""Thin wrapper around the Firebase Admin SDK, used ONLY to send FCM push
notifications. This never touches Firestore/Cloud Functions, so it needs
nothing beyond a free Firebase project + a downloaded service-account key.

If FIREBASE_SERVICE_ACCOUNT_PATH is not configured, push sends are silently
skipped (logged to console) so the rest of the app still works during local
development without any Firebase setup at all.
"""

import logging

from app.config import get_settings

logger = logging.getLogger("firebase")
settings = get_settings()

_app = None


def _get_app():
    global _app
    if _app is not None:
        return _app
    if not settings.firebase_service_account_path:
        return None

    import firebase_admin
    from firebase_admin import credentials

    cred = credentials.Certificate(settings.firebase_service_account_path)
    _app = firebase_admin.initialize_app(cred)
    return _app


def send_push(tokens: list[str], title: str, body: str, data: dict[str, str] | None = None) -> None:
    tokens = [t for t in tokens if t]
    if not tokens:
        return

    app = _get_app()
    if app is None:
        logger.info("[push:disabled] would send to %s tokens: %s - %s", len(tokens), title, body)
        return

    from firebase_admin import messaging

    message = messaging.MulticastMessage(
        notification=messaging.Notification(title=title, body=body),
        data=data or {},
        tokens=tokens,
    )
    response = messaging.send_each_for_multicast(message)
    logger.info("push sent: %s success, %s failure", response.success_count, response.failure_count)
