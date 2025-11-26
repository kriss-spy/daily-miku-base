"""Email automation for daily miku notifications."""

import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT_STR = os.getenv("SMTP_PORT", "587").strip()
SMTP_PORT = int(SMTP_PORT_STR) if SMTP_PORT_STR else 587
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


def create_html_template(data: dict) -> str:
    """
    Create simple HTML email template.

    Args:
        data: Daily miku data dict with imageUrl, sourceUrl, title, etc.

    Returns:
        HTML string
    """
    date = data.get("date", "")
    image_url = data.get("coverUrl", "")  # Use Raindrop CDN URL
    source_url = data.get("sourceUrl", "")
    title = data.get("title", "Daily Miku")
    description = data.get("description", "")

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
            {f'<img src="{image_url}" alt="Daily Miku" style="width: 100%; height: auto; border-radius: 4px; display: block;">' if image_url else ''}
            
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
) -> bool:
    """
    Send HTML email via SMTP.

    Args:
        subject: Email subject
        html_body: HTML content
        to_email: Recipient email (default: EMAIL_TO from env)
        from_email: Sender email (default: EMAIL_FROM from env)

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
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email

        # Attach HTML
        html_part = MIMEText(html_body, "html")
        msg.attach(html_part)

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
    Send daily miku email with data.

    Args:
        data: Daily miku data dict

    Returns:
        True if sent successfully
    """
    date = data.get("date", "today")
    subject = f"Daily Miku - {date}"
    html_body = create_html_template(data)

    return send_email(subject, html_body)
