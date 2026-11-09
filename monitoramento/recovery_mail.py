import os
import smtplib
import ssl
import json
import hashlib
import urllib.request
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
    provider = os.environ.get('RECOVERY_EMAIL_PROVIDER', 'smtp')
    if provider == 'resend':
        _send_https(recipient, token)
        return
    if provider != 'smtp':
        raise RecoveryMailConfigurationError('Provedor de e-mail inválido.')
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


def _send_https(recipient: str, token: str) -> None:
    api_key = os.environ.get('RESEND_API_KEY', '')
    sender = os.environ.get('RECOVERY_EMAIL_FROM', '').strip()
    base_url = os.environ.get('APP_BASE_URL', '').rstrip('/')
    parsed = urlsplit(base_url)
    if (not api_key or parsed.scheme != 'https' or not parsed.netloc
            or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise RecoveryMailConfigurationError('Configure o provedor e a origem HTTPS pública.')
    try:
        name, address = parseaddr(sender, strict=True)
        if name or address != sender or '@' not in sender or '\r' in sender or '\n' in sender:
            raise ValueError('invalid sender')
    except ValueError:
        raise RecoveryMailConfigurationError('Remetente de recuperação inválido.') from None
    reset_link = f'{base_url}/redefinir-senha#token={token}'
    payload = {'from': sender, 'to': [recipient],
               'subject': 'Monitoramento Ativo — Recuperação de senha',
               'text': 'Recebemos uma solicitação para redefinir sua senha.\n\n'
                       f'{reset_link}\n\nEste link é válido por 30 minutos e pode ser usado uma vez. '
                       'Se não solicitou a alteração, ignore esta mensagem.'}
    request = urllib.request.Request('https://api.resend.com/emails',
        data=json.dumps(payload).encode(), method='POST',
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json',
                 'User-Agent': 'MonitoramentoAtivo/1.0',
                 'Idempotency-Key': hashlib.sha256(token.encode()).hexdigest()})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status not in (200, 201, 202):
                raise OSError('delivery failed')
    except Exception:
        # Do not propagate headers, response bodies, addresses or reset links.
        raise RecoveryMailConfigurationError('Envio de recuperação indisponível.') from None
