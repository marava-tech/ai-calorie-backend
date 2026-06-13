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
    msg["Subject"] = f"{otp} — GymPulse AI verification code"
    msg["From"] = _from
    msg["To"] = to_email

    text = (
        f"Your GymPulse AI verification code is: {otp}\n\n"
        f"This code expires in 5 minutes.\n"
        f"If you didn't request this, you can safely ignore this email."
    )

    digits = "  ".join(list(otp))
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>GymPulse AI — Verification Code</title>
</head>
<body style="margin:0;padding:0;background-color:#0A0A10;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0A0A10;padding:40px 16px;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;">

          <!-- Header -->
          <tr>
            <td align="center" style="padding-bottom:32px;">
              <table cellpadding="0" cellspacing="0">
                <tr>
                  <td style="background:linear-gradient(135deg,#00C896,#0097a7);border-radius:16px;padding:12px 16px;text-align:center;">
                    <span style="font-size:22px;font-weight:900;letter-spacing:-0.5px;color:#fff;">&#9889; GymPulse AI</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Card -->
          <tr>
            <td style="background:#12121E;border-radius:24px;border:1px solid rgba(255,255,255,0.06);padding:40px 36px;">

              <!-- Icon -->
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding-bottom:24px;">
                    <div style="display:inline-block;background:rgba(0,200,150,0.12);border-radius:50%;width:64px;height:64px;line-height:64px;text-align:center;font-size:30px;">&#128274;</div>
                  </td>
                </tr>
              </table>

              <!-- Title -->
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding-bottom:8px;">
                    <h1 style="margin:0;font-size:22px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;">Verify your identity</h1>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-bottom:32px;">
                    <p style="margin:0;font-size:14px;color:#767690;line-height:1.5;">Use the code below to sign in to your GymPulse AI account.</p>
                  </td>
                </tr>
              </table>

              <!-- OTP Code Block -->
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding-bottom:28px;">
                    <div style="background:#0E0E1C;border:1px solid rgba(0,200,150,0.25);border-radius:16px;padding:28px 24px;display:inline-block;width:100%;box-sizing:border-box;">
                      <p style="margin:0 0 10px;font-size:11px;font-weight:700;letter-spacing:2px;color:#00C896;text-transform:uppercase;">Your verification code</p>
                      <p style="margin:0;font-size:42px;font-weight:900;letter-spacing:14px;color:#ffffff;font-variant-numeric:tabular-nums;">{digits}</p>
                    </div>
                  </td>
                </tr>
              </table>

              <!-- Expiry -->
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding-bottom:24px;">
                    <table cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="background:rgba(255,200,0,0.08);border:1px solid rgba(255,200,0,0.18);border-radius:8px;padding:8px 16px;">
                          <span style="font-size:12px;font-weight:700;color:#FFD600;">&#9203; Expires in 5 minutes</span>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Divider -->
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="border-top:1px solid rgba(255,255,255,0.06);padding-top:24px;">
                    <p style="margin:0;font-size:12px;color:#4A4A6A;line-height:1.6;text-align:center;">
                      If you didn't request this code, you can safely ignore this email.<br/>
                      Never share this code with anyone — GymPulse AI will never ask for it.
                    </p>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td align="center" style="padding-top:28px;">
              <p style="margin:0 0 4px;font-size:12px;color:#4A4A6A;">Sent by GymPulse AI &mdash; Marava Technologies</p>
              <p style="margin:0;font-size:11px;color:#2E2E4A;">This is an automated message, please do not reply.</p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

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
