from monitoramento.auth import (
    User,
    change_password,
    database_path,
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
    import tkinter as tk
    from tkinter import messagebox, simpledialog

    database = database_path()
    if not database.is_file():
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Banco de dados não encontrado",
            "Verifique se este é o projeto correto e se "
            "MONITORAMENTO_DB_PATH está igual à configuração do servidor.",
            parent=root,
        )
        root.destroy()
        return

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    if not messagebox.askokcancel(
        "Redefinir senha da conta Administradora",
        "Banco de dados selecionado:\n"
        f"{database.resolve()}\n\n"
        "Confira o caminho antes de continuar. A senha não será alterada "
        "até você confirmar a operação.",
        parent=root,
    ):
        root.destroy()
        return

    username = simpledialog.askstring(
        "Conta Administradora",
        "Digite o usuário da conta Administradora ativa:",
        parent=root,
    )
    if username is None:
        root.destroy()
        return
    try:
        admin = _find_active_admin(username)
    except ValueError as error:
        messagebox.showerror("Conta não encontrada", str(error), parent=root)
        root.destroy()
        return

    if not messagebox.askyesno(
        "Confirme a redefinição",
        f"A conta Administradora {admin.username!r} terá a senha alterada e "
        "suas sessões serão encerradas.\n\nDeseja continuar?",
        parent=root,
    ):
        root.destroy()
        return

    password = simpledialog.askstring(
        "Nova senha",
        "Digite uma nova senha exclusiva (mínimo 12 caracteres):",
        show="*",
        parent=root,
    )
    if password is None:
        root.destroy()
        return
    confirmation = simpledialog.askstring(
        "Confirme a nova senha",
        "Digite novamente a nova senha:",
        show="*",
        parent=root,
    )
    if confirmation is None:
        root.destroy()
        return
    if password != confirmation:
        messagebox.showerror(
            "Senhas diferentes",
            "As senhas não conferem. Nenhuma alteração foi feita.",
            parent=root,
        )
        root.destroy()
        return

    try:
        change_password(admin.id, password)
    except ValueError as error:
        messagebox.showerror("Não foi possível redefinir", str(error), parent=root)
        root.destroy()
        return
    messagebox.showinfo(
        "Senha redefinida",
        "A senha foi alterada. Acesse /login com a nova senha. "
        "Não é necessário reiniciar o servidor.",
        parent=root,
    )
    root.destroy()


if __name__ == "__main__":
    main()
