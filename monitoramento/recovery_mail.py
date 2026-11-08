import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import urlsplit


class RecoveryMailConfigurationError(RuntimeError):
    pass


def _mail_configuration() -> tuple[str, int, str, str, str, str]:
    host = os.environ.get("SMTP_HOST", "").strip()
    username = os.environ.get("SMTP_USERNAME", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM", "").strip()
    base_url = os.environ.get("APP_BASE_URL", "").rstrip("/")
    if not all((host, username, password, sender, base_url)):
        raise RecoveryMailConfigurationError("O serviço de e-mail não está configurado.")
    if "\r" in sender or "\n" in sender:
        raise RecoveryMailConfigurationError("O remetente de e-mail não é válido.")
    try:
        sender_name, sender_address = parseaddr(sender, strict=True)
    except ValueError as error:
        raise RecoveryMailConfigurationError(
            "O remetente de e-mail não é válido."
        ) from error
    if sender_name or sender_address != sender or "@" not in sender_address:
        raise RecoveryMailConfigurationError("O remetente de e-mail não é válido.")
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.path not in ("", "/"):
        raise RecoveryMailConfigurationError("A URL pública segura não está configurada.")
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
    except ValueError as error:
        raise RecoveryMailConfigurationError("A porta SMTP não é válida.") from error
    if not 1 <= port <= 65535:
        raise RecoveryMailConfigurationError("A porta SMTP não é válida.")
    return host, port, username, password, sender, base_url


def send_password_reset_email(recipient: str, token: str) -> None:
    host, port, username, password, sender, base_url = _mail_configuration()
    message = EmailMessage()
    message["Subject"] = "Monitoramento Ativo — Recuperação de senha"
    message["From"] = sender
    message["To"] = recipient
    reset_link = f"{base_url}/redefinir-senha#token={token}"
    message.set_content(
        "Olá,\n\n"
        "Recebemos uma solicitação para redefinir a senha de acesso ao "
        "Monitoramento Ativo de Tuberculose e Hanseníase.\n\n"
        "Para cadastrar uma nova senha, acesse o link abaixo:\n\n"
        f"{reset_link}\n\n"
        "Este link é válido por 30 minutos e poderá ser utilizado apenas uma vez.\n\n"
        "Se você não solicitou a recuperação, ignore esta mensagem. "
        "Sua senha permanecerá inalterada.\n\n"
        "Equipe do Monitoramento Ativo."
    )
    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=15) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(username, password)
        server.send_message(message)
