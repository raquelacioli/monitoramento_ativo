import getpass

from monitoramento.auth import create_first_admin


def main() -> None:
    username = input("Nome de usuário do primeiro administrador: ").strip()
    password = getpass.getpass("Senha (mínimo 12 caracteres): ")
    confirmation = getpass.getpass("Confirme a senha: ")
    if password != confirmation:
        raise SystemExit("As senhas não conferem.")
    try:
        create_first_admin(username, password)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print("Administrador criado. Acesse /login e crie as contas dos profissionais.")


if __name__ == "__main__":
    main()
