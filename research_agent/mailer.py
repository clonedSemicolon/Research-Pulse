"""Email delivery over SMTP with automatic fallback.

Primary: AWS SES (recommended, port 587)
Backup: Self-hosted Postfix on EC2 (port 587, when port 25 is unblocked)

Supports automatic failover: if primary SMTP fails, tries backup.
"""

from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from typing import Optional

from .config import Secrets
from .log import get as _log

log = _log("mailer")


class Mailer:
    def __init__(self, secrets: Secrets):
        self.secrets = secrets
        self._server: Optional[smtplib.SMTP] = None
        self._using_backup = False

    @property
    def configured(self) -> bool:
        s = self.secrets
        # Primary SMTP must be configured
        primary_ok = bool(s.smtp_host and s.smtp_user and s.smtp_key and s.sender_email)
        # Backup is optional
        return primary_ok

    def __enter__(self) -> "Mailer":
        if self.configured:
            self._connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _connect(self) -> None:
        """Connect to primary SMTP, with fallback to backup if available."""
        context = ssl.create_default_context()

        # Try primary SMTP
        try:
            log.info("connecting to primary SMTP: %s:%d", self.secrets.smtp_host, self.secrets.smtp_port)
            server = smtplib.SMTP(self.secrets.smtp_host, self.secrets.smtp_port, timeout=30)
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(self.secrets.smtp_user, self.secrets.smtp_key)
            self._server = server
            self._using_backup = False
            log.info("connected to primary SMTP successfully")
            return
        except Exception as exc:
            log.warning("primary SMTP connection failed: %s", exc)

        # Try backup SMTP if configured
        if self.secrets.smtp_host_backup and self.secrets.smtp_user_backup:
            try:
                log.info("trying backup SMTP: %s:%d", self.secrets.smtp_host_backup, self.secrets.smtp_port_backup)
                server = smtplib.SMTP(self.secrets.smtp_host_backup, self.secrets.smtp_port_backup, timeout=30)
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(self.secrets.smtp_user_backup, self.secrets.smtp_key_backup)
                self._server = server
                self._using_backup = True
                log.info("connected to backup SMTP successfully")
                return
            except Exception as exc:
                log.error("backup SMTP connection also failed: %s", exc)

        log.error("all SMTP connection attempts failed")

    def close(self) -> None:
        if self._server is not None:
            try:
                self._server.quit()
            except smtplib.SMTPException:
                pass
            self._server = None

    def send(self, to_email: str, subject: str, html: str) -> bool:
        """Send one HTML email. Returns True on success."""
        if self._server is None:
            raise RuntimeError("Mailer is not connected (use as a context manager).")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr((self.secrets.sender_name, self.secrets.sender_email))
        msg["To"] = to_email
        # A minimal plain-text part improves deliverability.
        msg.attach(MIMEText("Open this email in an HTML-capable client.", "plain"))
        msg.attach(MIMEText(html, "html"))

        try:
            self._server.sendmail(self.secrets.sender_email, [to_email], msg.as_string())
            server_type = "backup" if self._using_backup else "primary"
            log.info("sent to %s via %s SMTP", to_email, server_type)
            return True
        except smtplib.SMTPException as exc:
            log.error("failed to send to %s: %s", to_email, exc)
            return False
