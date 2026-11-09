from monitoramento.auth import (
    User,
    change_password,
    list_users,
)


def _find_active_admin(username: str) -> User:
    normalized_username = username.strip().casefold()
    if not normalized_username:
        raise ValueError("Informe o nome de usuário da conta Administradora.")
    admin = next(
        (
            user
            for user in list_users()
            if user.username.casefold() == normalized_username
            and user.role == "admin"
            and user.active
        ),
        None,
    )
    if admin is None:
        raise ValueError("Conta Administradora ativa não encontrada.")
    return admin


def reset_admin_password(username: str, password: str) -> None:
    admin = _find_active_admin(username)
    change_password(admin.id, password)


def main() -> None:
    import getpass
    from monitoramento.firestore_store import get_store
    store = get_store()
    print(f"Firestore: projeto {store.client.project}, namespace {store.namespace}")
    username = input("Usuário da conta Administradora ativa: ").strip()
    admin = _find_active_admin(username)
    if input("Digite REDEFINIR para confirmar: ").strip() != "REDEFINIR":
        raise SystemExit("Operação cancelada.")
    password = getpass.getpass("Nova senha (mínimo 12 caracteres): ")
    if password != getpass.getpass("Confirme a nova senha: "):
        raise SystemExit("As senhas não conferem.")
    change_password(admin.id, password)
    print("Senha redefinida; sessões anteriores revogadas.")


if __name__ == "__main__":
    main()
