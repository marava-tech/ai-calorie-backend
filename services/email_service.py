"""Gmail SMTP OTP email sender."""
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib

logger = logging.getLogger(__name__)

_enabled = os.environ.get("EMAIL_ENABLED", "false").lower() == "true"
_from = os.environ.get("EMAIL_FROM", "")
_host = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
_port = int(os.environ.get("EMAIL_PORT", "587"))
_username = os.environ.get("EMAIL_USERNAME", "")
_password = os.environ.get("EMAIL_PASSWORD", "")


async def send_otp(to_email: str, otp: str) -> None:
    if not _enabled:
        logger.info("Email disabled — OTP for %s: %s", to_email, otp)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{otp} is your Fitness OS verification code"
    msg["From"] = _from
    msg["To"] = to_email

    text = f"Your Fitness OS OTP is: {otp}\n\nThis code expires in 5 minutes. Do not share it."
    html = f"""
<div style="font-family:sans-serif;max-width:400px;margin:0 auto;padding:32px">
  <h2 style="margin:0 0 8px;color:#00C896">Fitness OS</h2>
  <p style="color:#888;margin:0 0 24px;font-size:14px">Your verification code</p>
  <div style="background:#111;border-radius:12px;padding:24px;text-align:center">
    <span style="font-size:40px;font-weight:900;letter-spacing:12px;color:#00C896">{otp}</span>
  </div>
  <p style="color:#888;font-size:12px;margin-top:16px">Expires in 5 minutes. Do not share this code.</p>
</div>
"""
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    await aiosmtplib.send(
        msg,
        hostname=_host,
        port=_port,
        username=_username,
        password=_password,
        start_tls=True,
    )
    logger.info("OTP email sent to %s", to_email)
