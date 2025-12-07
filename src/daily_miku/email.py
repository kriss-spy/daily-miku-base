"""Email automation for daily miku notifications."""

import os
import re
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")


def is_valid_email(email: str) -> bool:
    """
    Validate email format.

    Args:
        email: Email address to validate

    Returns:
        True if email format is valid
    """
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def create_html_template(data: dict, use_cid: bool = True) -> str:
    """
    Create simple HTML email template.

    Args:
        data: Daily miku data dict with imageUrl, sourceUrl, title, etc.
        use_cid: If True, use cid:miku_image for embedded image (default)

    Returns:
        HTML string
    """
    date = data.get("date", "")
    image_url = data.get("coverUrl", "")  # Fallback to Raindrop CDN URL
    source_url = data.get("sourceUrl", "")
    title = data.get("title", "Daily Miku")
    description = data.get("description", "")

    # Use cid for embedded image or direct URL as fallback
    img_src = "cid:miku_image" if use_cid and image_url else image_url

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Miku - {date}</title>
</head>
<body style="margin: 0; padding: 20px; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <div style="max-width: 600px; margin: 0 auto; background-color: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; text-align: center;">
            <h1 style="color: white; margin: 0; font-size: 28px;">🎤 Daily Miku</h1>
            <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0;">{date}</p>
        </div>
        
        <div style="padding: 20px;">
            {f'<img src="{img_src}" alt="Daily Miku" style="width: 100%; height: auto; border-radius: 4px; display: block;">' if img_src else ''}
            
            <h2 style="color: #333; margin: 20px 0 10px 0;">{title}</h2>
            
            {f'<p style="color: #666; line-height: 1.6;">{description}</p>' if description else ''}
            
            {f'<a href="{source_url}" style="display: inline-block; margin-top: 20px; padding: 12px 24px; background-color: #667eea; color: white; text-decoration: none; border-radius: 4px; font-weight: bold;">View Source</a>' if source_url else ''}
        </div>
        
        <div style="padding: 20px; background-color: #f9f9f9; text-align: center; color: #999; font-size: 12px;">
            <p style="margin: 0;">daily-miku-base • Powered by raindrop.io</p>
        </div>
    </div>
</body>
</html>
    """

    return html.strip()


def send_email(
    subject: str,
    html_body: str,
    to_email: Optional[str] = None,
    from_email: Optional[str] = None,
    image_url: Optional[str] = None,
) -> bool:
    """
    Send HTML email via SMTP with optional embedded image.

    Args:
        subject: Email subject
        html_body: HTML content
        to_email: Recipient email (default: EMAIL_TO from env)
        from_email: Sender email (default: EMAIL_FROM from env)
        image_url: Optional image URL to download and embed

    Returns:
        True if sent successfully, False otherwise
    """
    to_email = to_email or EMAIL_TO
    from_email = from_email or EMAIL_FROM

    if not all([SMTP_USER, SMTP_PASSWORD, to_email, from_email]):
        print("Error: Missing email configuration. Check .env file.")
        print(f"  SMTP_USER: {'✓' if SMTP_USER else '✗'}")
        print(f"  SMTP_PASSWORD: {'✓' if SMTP_PASSWORD else '✗'}")
        print(f"  EMAIL_FROM: {'✓' if from_email else '✗'}")
        print(f"  EMAIL_TO: {'✓' if to_email else '✗'}")
        return False

    # Validate email formats
    if not is_valid_email(to_email):
        print(f"Error: Invalid recipient email format: {to_email}")
        return False

    if not is_valid_email(from_email):
        print(f"Error: Invalid sender email format: {from_email}")
        return False

    try:
        # Create message
        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email

        # Attach HTML
        msg_alternative = MIMEMultipart("alternative")
        msg.attach(msg_alternative)

        html_part = MIMEText(html_body, "html")
        msg_alternative.attach(html_part)

        # Download and embed image if URL provided
        if image_url:
            try:
                response = requests.get(image_url, timeout=10)
                response.raise_for_status()

                # Create image attachment with Content-ID
                image = MIMEImage(response.content)
                image.add_header("Content-ID", "<miku_image>")
                image.add_header("Content-Disposition", "inline", filename="miku.jpg")
                msg.attach(image)

                print(f"✓ Image embedded from {image_url[:50]}...")
            except Exception as e:
                print(f"⚠ Failed to embed image: {e}")
                # Continue sending email without embedded image

        # Send via SMTP
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        print(f"✓ Email sent successfully to {to_email}")
        return True

    except Exception as e:
        print(f"✗ Failed to send email: {e}")
        return False


def send_daily_miku_email(data: dict) -> bool:
    """
    Send daily miku email with embedded image.

    Args:
        data: Daily miku data dict

    Returns:
        True if sent successfully
    """
    date = data.get("date", "today")
    subject = f"Daily Miku - {date}"
    image_url = data.get("coverUrl", "")

    # Create HTML with cid reference for embedded image
    html_body = create_html_template(data, use_cid=True)

    return send_email(subject, html_body, image_url=image_url)


def send_warning_email(date: str, reason: str = "No daily miku found") -> bool:
    """
    Send warning email to EMAIL_FROM when daily email fails.

    Args:
        date: The date that failed
        reason: Reason for failure

    Returns:
        True if warning sent successfully
    """
    if not EMAIL_FROM:
        print("⚠ EMAIL_FROM not set, cannot send warning")
        return False

    subject = f"⚠️ Daily Miku Failed - {date}"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
            }}
            .warning-box {{
                background: #fff3cd;
                border: 2px solid #ffc107;
                border-radius: 8px;
                padding: 20px;
                margin: 20px 0;
            }}
            .warning-icon {{
                font-size: 48px;
                text-align: center;
                margin-bottom: 10px;
            }}
            h1 {{
                color: #856404;
                margin-top: 0;
            }}
            .detail {{
                background: #f8f9fa;
                padding: 15px;
                border-radius: 5px;
                margin: 15px 0;
            }}
            .action {{
                background: #007bff;
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                border-radius: 5px;
                display: inline-block;
                margin-top: 15px;
            }}
            .footer {{
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #dee2e6;
                font-size: 12px;
                color: #6c757d;
            }}
        </style>
    </head>
    <body>
        <div class="warning-box">
            <div class="warning-icon">⚠️</div>
            <h1>Daily Miku Email Failed</h1>
            <p>The automated daily miku email could not be sent for <strong>{date}</strong>.</p>
            
            <div class="detail">
                <strong>Reason:</strong><br>
                {reason}
            </div>
            
            <div class="detail">
                <strong>What to check:</strong>
                <ul>
                    <li>Did you add a bookmark with the <code>#daily-miku</code> tag in Raindrop.io today?</li>
                    <li>Is the bookmark's "Saved" date set to today ({date})?</li>
                    <li>Does the bookmark have a cover image?</li>
                </ul>
            </div>
            
            <a href="https://app.raindrop.io/" class="action">Go to Raindrop.io</a>
        </div>
        
        <div class="footer">
            This is an automated warning from your Daily Miku system.<br>
            If you continue receiving this, check your GitHub Actions logs for more details.
        </div>
    </body>
    </html>
    """

    try:
        # Send warning to EMAIL_FROM account
        return send_email(
            subject=subject,
            html_body=html_body,
            to_email=EMAIL_FROM,
            from_email=EMAIL_FROM,
            image_url=None,
        )
    except Exception as e:
        print(f"✗ Failed to send warning email: {e}")
        return False
