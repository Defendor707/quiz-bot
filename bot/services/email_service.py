#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gmail orqali email yuborish servisi
"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from bot.config import Config

logger = logging.getLogger(__name__)


class EmailService:
    """Gmail orqali email yuborish servisi"""
    
    def __init__(self):
        self.smtp_server = Config.GMAIL_SMTP_SERVER
        self.smtp_port = Config.GMAIL_SMTP_PORT
        self.sender_email = Config.GMAIL_SENDER_EMAIL
        self.sender_password = Config.GMAIL_SENDER_PASSWORD
        self.recipient_email = Config.GMAIL_RECIPIENT_EMAIL
        
    def send_email(
        self,
        subject: str,
        body: str,
        recipient: Optional[str] = None,
        is_html: bool = False
    ) -> bool:
        """
        Email yuborish
        
        Args:
            subject: Email mavzusi
            body: Email matni
            recipient: Qabul qiluvchi email (agar None bo'lsa, config dan olinadi)
            is_html: HTML formatda yuborish
        
        Returns:
            True agar muvaffaqiyatli, False aks holda
        """
        if not self.sender_email or not self.sender_password:
            logger.warning("⚠️ Gmail sozlamalari to'liq emas. Email yuborilmadi.")
            return False
        
        recipient = recipient or self.recipient_email
        if not recipient:
            logger.warning("⚠️ Qabul qiluvchi email manzili ko'rsatilmagan. Email yuborilmadi.")
            return False
        
        try:
            # Email yaratish
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = self.sender_email
            message["To"] = recipient
            
            # Matn qo'shish
            if is_html:
                part = MIMEText(body, "html", "utf-8")
            else:
                part = MIMEText(body, "plain", "utf-8")
            message.attach(part)
            
            # SMTP orqali yuborish
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(message)
            
            logger.info(f"✅ Email muvaffaqiyatli yuborildi: {subject} -> {recipient}")
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"❌ Gmail autentifikatsiya xatolik: {e}")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"❌ SMTP xatolik: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Email yuborishda xatolik: {e}", exc_info=True)
            return False


# Global email service instance
email_service = EmailService()
