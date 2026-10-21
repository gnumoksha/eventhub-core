from urllib.parse import quote

import resend
from identity.domain.models.account.events import AccountVerificationRequested, PasswordResetRequested
from libs.events import listener
from shared.infra.authentication.token_encryption import decrypt_authentication_token
from shared.infra.logger import logger
from shared.settings import settings


async def _send_email(recipient: str, subject: str, body: str, idempotency_key: str) -> None:
    if not settings.RESEND_API_KEY:
        if settings.is_dev_like():
            logger.info("Resend is not configured; local authentication email body follows: %s", body)
            return
        raise RuntimeError("RESEND_API_KEY must be configured to deliver authentication emails")

    logger.info("_send_email: sending email")

    resend.api_key = settings.RESEND_API_KEY.get_secret_value()

    params: resend.Emails.SendParams = {
        "from": settings.NOTIFICATIONS_FROM_EMAIL,
        "to": [recipient],
        "subject": subject,
        "text": body,
    }

    options: resend.Emails.SendOptions = {
        "idempotency_key": idempotency_key,
    }

    await resend.Emails.send_async(params, options)

    logger.info("_send_email: email has been sent")


@listener(AccountVerificationRequested)
async def send_verification_email(event: AccountVerificationRequested) -> None:
    token = decrypt_authentication_token(event.encrypted_token)
    url = f"{settings.PUBLIC_URL.rstrip('/')}/verify-email?token={quote(token)}"
    await _send_email(
        event.email,
        "Verify your Eventhub email",
        f"Verify your email address by opening this link within 24 hours:\n\n{url}\n",
        f"send_verification_email/{event.metadata.id}",
    )


@listener(PasswordResetRequested)
async def send_password_reset_email(event: PasswordResetRequested) -> None:
    token = decrypt_authentication_token(event.encrypted_token)
    url = f"{settings.PUBLIC_URL.rstrip('/')}/reset-password?token={quote(token)}"
    await _send_email(
        event.email,
        "Reset your Eventhub password",
        f"Reset your password by opening this link within one hour:\n\n{url}\n",
        f"send_password_reset_email/{event.metadata.id}",
    )
