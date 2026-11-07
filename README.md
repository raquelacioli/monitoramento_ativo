# Monitoramento Ativo

Aplicação demonstrativa para acompanhamento de Tuberculose e Hanseníase com FastAPI.

## Acessar a aplicação

Quando o servidor já estiver em execução, abra `http://127.0.0.1:8000`. A página inicial apresenta os módulos disponíveis; os painéis de acompanhamento exigem login.

Não inicie outra instância se a porta 8000 já estiver ocupada pelo servidor deste projeto.

## Criar o primeiro administrador

No terminal do VS Code, abra a pasta `monitoramento_ativo` e execute:

```powershell
.\.venv\Scripts\python.exe -m monitoramento.auth_admin
```

O programa solicitará um nome de usuário e uma senha com pelo menos 12 caracteres. A senha é digitada sem aparecer na tela e não deve ser compartilhada ou gravada no código. Depois, entre em `/login` e use a área de administração para criar contas e atribuí-las aos perfis e unidades.

## Uso e limitações desta versão

- Os registros são fictícios e servem somente para demonstração e testes.
- A unidade pode atualizar a data do último comparecimento diretamente na linha do registro; o valor fica salvo junto às demais alterações demonstrativas no SQLite local.
- Os formulários PDF disponíveis no projeto são modelos reconstruídos, não oficiais. Os campos e códigos ainda precisam ser conferidos com a documentação oficial.
- O envio de PDF produz um resumo agregado; não importa automaticamente pacientes para as fichas individuais. Um formulário em branco reconhecido é exibido como zero casos listados e não encerra registros de competências anteriores.
- Não use dados reais de pacientes nesta versão. Antes disso, são necessários validação documental e avaliação de segurança e privacidade, incluindo proteção do banco local, backups e implantação com HTTPS.
- Para uma implantação HTTPS, configure `MONITORAMENTO_COOKIE_SECURE=1` no ambiente do processo antes de iniciar a aplicação.
