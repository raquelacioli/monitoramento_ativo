# Monitoramento Ativo: Firestore e Render

## Estado da integração

A aplicação usa Firestore nativo no servidor para contas, sessões, boletins, alterações, alertas, observações, prazos, confirmações, dashboards e histórico. O banco é `(default)` do projeto `monitoramentoativo`. Os documentos ficam exclusivamente em `monitoramento_ativo/<namespace>/<coleção>/<hash>`; não há acesso às coleções do MeuSinan. Firebase Authentication não é necessário: login e PBKDF2 continuam com os contratos anteriores.

SQLite não é aberto pelo servidor. O importador separado o abre em modo somente leitura. Não há fallback local quando Firestore falha. Os PDFs originais continuam sem armazenamento permanente: são processados na memória e prévias expiram em dez minutos; reiniciar ou suspender o serviço perde as prévias. Dados confirmados permanecem no Firestore. Nenhum bucket é exigido.

## Variáveis

| Nome | Configuração |
|---|---|
| `APP_ENV` | `production` no Render; `test` exclusivamente no emulador |
| `FIREBASE_PROJECT_ID` | `monitoramentoativo` |
| `FIRESTORE_DATABASE_ID` | `(default)` |
| `FIRESTORE_NAMESPACE` | `monitoramento_ativo` em instalação nova; namespace reconciliado de preparação se houver migração |
| `GOOGLE_APPLICATION_CREDENTIALS` | Caminho do Secret File: `/etc/secrets/firebase-service-account.json` |
| `MONITORAMENTO_COOKIE_SECURE` | `1` em HTTPS |
| `APP_BASE_URL` | Origem HTTPS pública, sem caminho, query ou fragmento |
| `RECOVERY_EMAIL_PROVIDER` | `resend` para envio HTTPS no Render gratuito; `smtp` como alternativa em outra hospedagem/plano |
| `RECOVERY_EMAIL_FROM` | Remetente verificado no provedor HTTPS |
| `RESEND_API_KEY` | Chave secreta do provedor HTTPS |
| `PORT` | Fornecida pelo Render; não fixar no código |

Para SMTP opcional: `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_PORT` (padrão 587, STARTTLS). Não configurar SMTP 587 no Render gratuito: o plano bloqueia saída nas portas 25, 465 e 587. Recuperação de senha exige provedor configurado e e-mail cadastrado pelo administrador; sem isso, login continua funcionando, mas nenhum link é entregue.

`FIRESTORE_EMULATOR_HOST=127.0.0.1:8085` e `FIREBASE_PROJECT_ID=demo-monitoramento-ativo` são exclusivos dos testes. O cliente rejeita emulador remoto, projeto real no emulador e emulador em ambiente production. `MONITORAMENTO_DB_PATH` não controla a persistência web; o importador recebe a origem por `--source`.

## Credenciais e acesso

Criar/configurar uma conta de serviço exclusiva para o Monitoramento Ativo com permissão mínima para ler e escrever no banco, como `roles/datastore.user`. Não conceder Owner/Editor. O SDK servidor usa IAM e ignora regras de clientes; a restrição aos caminhos do aplicativo também é feita pelo código. Uma conta com acesso amplo ao banco ainda pode tecnicamente acessar outras coleções fora do aplicativo; use isolamento de projeto/banco/IAM conforme política da organização. Nenhuma configuração IAM é alterada automaticamente.

No Render, cadastrar o JSON como **Secret File**, com nome `firebase-service-account.json`. Não colar o JSON no código, README, Blueprint ou GitHub. O cliente confere se o projeto das credenciais coincide com `monitoramentoativo` e sanitiza erros de carregamento. `.gitignore` ignora arquivos de credenciais, `.env`, bancos, PDFs, caches e logs.

`firestore.rules` é uma proposta de negação de acesso direto de clientes somente para o namespace deste app. **Não executar `firebase deploy` neste projeto** nem substituir regras compartilhadas com outros sistemas. Caso o banco tenha outras regras abrangentes, um administrador deve avaliar o conjunto, pois regras permissivas de outros matches podem conceder acesso. Nenhuma regra foi publicada.

## Testes com dados fictícios

Requisitos locais: Python 3.12 atualizado, Java 21 e Node.js compatível com Firebase CLI. Na raiz deste repositório (`monitoramento_ativo`):

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
npx.cmd --yes firebase-tools@15.35.0 emulators:start --only firestore --project demo-monitoramento-ativo
```

Em outro terminal:

```powershell
.venv/Scripts/python.exe -B scripts/run_tests.py
```

No Linux, usar `python` da virtualenv e `npx` no lugar de `npx.cmd`. O runner fixa projeto fictício, host local e ambiente test, remove o caminho de credenciais do processo filho e cria namespaces isolados. Sem emulador, a suíte de integração falha explicitamente; não é substituída por testes contra produção. Nenhum e-mail real é enviado nos testes. O teste de migração cria seu próprio SQLite fictício.

Para experimentar a interface no emulador, configure explicitamente essas variáveis em um terminal separado, escolha um namespace `test_demo_manual`, use `MONITORAMENTO_COOKIE_SECURE=0` somente para HTTP local e crie o administrador com a CLI. Depois execute `uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1` e abra `http://127.0.0.1:8000`. Não reutilizar credenciais reais.

## Migração legada: executar somente após autorização

Não existe migração automática no startup, build ou deploy. Primeiro parar gravações no SQLite, manter backup verificado e fazer dry-run:

```powershell
.venv/Scripts/python.exe -B -m monitoramento.migrate_sqlite --source CAMINHO_DO_BACKUP.sqlite3
```

Dry-run valida integridade, esquema, referências, chaves e JSON e imprime apenas contagens. Não exige conexão ao Firestore e não altera a origem.

A escrita exige um namespace vazio de preparação, como `monitoramento_ativo_migration_20261109`, credenciais explicitamente configuradas e autorização do responsável. Só então usar o mesmo comando com `--apply`. O código recusa o namespace padrão para migração, destino já ocupado por outros dados ou checkpoint de outra origem. Mantém IDs e contadores, hashes/salts de senha, históricos e campos originais. Sessões, limites transitórios e tokens de recuperação antigos não são migrados; usuários fazem novo login com a senha existente.

Os lotes têm checkpoints idempotentes. Uma falha deixa o namespace indisponível; repetir com a mesma origem retoma. A reconciliação compara todos os documentos preparados antes de marcar `complete`. Não editar a origem entre tentativas. Ao final, revisar contagens, login e funções, e somente depois configurar `FIRESTORE_NAMESPACE` com o namespace reconciliado. Isso evita copiar dados outra vez ou misturar com instalação ativa.

Preservar SQLite original e backup após a validação, conforme política de retenção. Rollback de uma migração inicial pode voltar à versão anterior do código e SQLite congelado; alterações posteriores feitas no Firestore não existem nesse SQLite e exigem reconciliação antes de voltar. A migração real não foi executada por esta implementação.

## Preparação do Render gratuito

`render.yaml` fica na raiz Git, ao lado de `main.py` e `requirements.txt`. Usar Web Service Python, **Root Directory vazio**, plano Free. O arquivo `.python-version` seleciona a linha 3.12 atualizada.

- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1`
- Health check: `/healthz` (verifica leitura do Firestore, sem divulgar configuração)
- Auto-deploy: desligado no Blueprint.
- Nenhum disco ou banco SQLite local é necessário.

Cadastrar o Secret File e as variáveis antes da inicialização. Criar o serviço via Blueprint dispara sua implantação inicial; só fazer essa ação após aprovação. O manifesto preparado não executa nada sozinho.

O plano gratuito suspende o serviço sem tráfego. O primeiro acesso após suspensão pode demorar; prévias PDF em memória se perdem. Firestore e provedor de e-mail possuem cotas próprias, independentes do plano Render. Avaliar consumo de leituras/escritas, região, tamanho dos PDFs e concorrência antes de uso amplo.

O administrador inicial deve ser criado de um terminal local confiável com as mesmas variáveis do destino, após autorização de escrita no ambiente:

```powershell
.venv/Scripts/python.exe -B -m monitoramento.auth_admin
```

O Render Free não oferece shell; essa operação não deve ir no build. A CLI solicita senha mascarada e recusa criar outro primeiro administrador. Recuperação administrativa offline: `python -m monitoramento.reset_admin_password`, com confirmação textual e sem Tkinter.

## Limites preservados e publicação

Importações são publicadas em lotes com marcador atômico e leituras consistentes; uma importação interrompida bloqueia outras mutações mensais até retomada do mesmo boletim. Isso evita alterações sobre dados parcialmente preparados. Um worker é obrigatório enquanto as prévias estiverem na memória. A aplicação conserva as limitações do leitor de PDFs e da validação documental descritas no README; a troca do banco não é validação clínica.

Antes da publicação autorizada: cadastrar credenciais e provedor, revisar IAM/regras existentes, aprovar eventual migração de produção e conferir namespace. A validação no emulador não comprova permissões IAM nem entrega de e-mail no serviço real. Não publicar dados reais de pacientes sem concluir a avaliação documental, de privacidade e segurança indicada pelo projeto.

Referências: [Firestore transactions](https://firebase.google.com/docs/firestore/manage-data/transactions), [emulador](https://firebase.google.com/docs/emulator-suite/connect_firestore), [Render Free](https://render.com/docs/free), [Blueprint](https://render.com/docs/blueprint-spec), [Resend HTTPS API](https://resend.com/docs/api-reference/emails/send-email).
