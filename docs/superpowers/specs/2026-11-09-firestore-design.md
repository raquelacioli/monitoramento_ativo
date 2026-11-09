# Integração Firestore do Monitoramento Ativo

Status: aprovado pelo usuário em 2026-11-09; implementação local em validação, sem deploy ou migração de produção.

## Objetivo e limites

Substituir a persistência SQLite por Cloud Firestore no projeto `monitoramentoativo`, preservando contratos das rotas, login, permissões por unidade, boletins, histórico, alertas e dashboards. Alterar somente este repositório. Não modificar MeuSinan, não fazer deploy e não publicar credenciais. Não executar migração de dados reais automaticamente.

## Abordagens

Proposta técnica: repositórios nativos Firestore por domínio, preservando as funções públicas de auth.py, tracking_store.py e monthly_store.py e as validações independentes do banco. Firebase Authentication seria outra migração, com impacto nas contas e no login por nome de usuário; fica fora deste escopo. Não armazenar um arquivo SQLite serializado no Firestore nem implementar um interpretador SQL.

## Dados e transações

Usar namespace exclusivo `monitoramento_ativo` no banco `(default)`, configurável, sem escrever em coleções de outros aplicativos. Documentos separados para usuários, reservas de nomes/e-mails únicos, sessões, limites de autenticação, tokens de recuperação, alterações demonstrativas, competências, importações, cobertura por unidade, fichas, revisões, conflitos, notas, solicitações, respostas, eventos, prazos e confirmações. Identificadores determinísticos derivados de hashes de chaves compostas; nenhuma identificação clínica em caminhos de documentos. Preservar identificadores inteiros de usuários e solicitações por contadores transacionais para manter os contratos atuais.

Transações devem garantir unicidade de usuário/e-mail, criação exclusiva do primeiro administrador, proteção do último administrador, limites de login, uso único de tokens, revogação de sessões e atualizações com versão esperada. Leitura precede escrita em transações; retries não podem enviar e-mail nem produzir outros efeitos externos. Estado de sessão deve depender da versão de autenticação do usuário, permitindo revogação atômica sem apagar quantidade ilimitada de documentos. Expiração validada no servidor mesmo quando existir TTL.

Serializar abertura/fechamento/importação por documento de controle da competência. Importação mantém deduplicação por hash, conflitos e auditoria. PDFs podem ter até 1.000 registros: não assumir que cabem numa transação. Preparar importações em lotes limitados e publicar uma versão somente após concluir todos os lotes; leituras ignoram versões incompletas, e retries retomam a mesma operação. Bloquear alterações incompatíveis durante publicação; falhas deixam o estado anterior visível. Documentar limites e criar testes de falha antes da publicação.

Consultas por unidade e competência, paginação e índices versionados quando necessários; evitar carregar todo o banco em cada requisição. Indicadores conservam as regras Python existentes. Históricos continuam separados dos valores oficiais. Nunca usar fallback silencioso para SQLite quando Firestore estiver indisponível.

## Autenticação e PDFs

Preservar PBKDF2, perfis, CSRF, bloqueio de tentativas, troca obrigatória de senha e recuperação SMTP. SDK exclusivamente no servidor; navegador não recebe conta de serviço. Regras Firestore propostas negam acesso direto de clientes; permissões IAM limitadas ao banco e aplicação, pois SDK servidor não depende das regras de clientes. Não publicar regras automaticamente.

Preservar o comportamento dos PDFs: leitura e prévias temporárias em memória, sem arquivar os originais. Um worker no Render. Armazenamento permanente em Cloud Storage e prévias compartilhadas ficam fora deste pedido de troca de persistência.

## Migração segura

Comando separado de migração lê SQLite em modo somente leitura, começa em dry-run, verifica esquema e referências e produz apenas contagens/erros sem valores sensíveis. Preservar IDs, hashes e salts PBKDF2, relações, revisões e histórico. Invalidar sessões e tokens de recuperação na troca; usuários conservam senha e fazem novo login. Escrita exige opção explícita, destino vazio ou namespace de preparação e checkpoint idempotente. Proibir mistura de importações com destino ativo. Manter o SQLite original e relatório de reconciliação para rollback. Nenhuma migração real será executada nesta implementação; validação usa banco fictício.

## Configuração Render

Adicionar manifesto sem deploy, com build `pip install -r requirements.txt`, start `uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1`, Python 3.12 atualizado, cookie seguro e health check. Credenciais por Secret File fora do repositório, com `GOOGLE_APPLICATION_CREDENTIALS`; validar projeto do cliente e das credenciais. Variáveis: `FIREBASE_PROJECT_ID=monitoramentoativo`, `FIRESTORE_DATABASE_ID=(default)`, `FIRESTORE_NAMESPACE=monitoramento_ativo`, `GOOGLE_APPLICATION_CREDENTIALS`, `MONITORAMENTO_COOKIE_SECURE=1`, `APP_BASE_URL`, além de `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` para recuperação. `PORT` fornecida pelo Render. `FIRESTORE_EMULATOR_HOST` exclusivo de testes locais, rejeitado em produção. Nenhum segredo no manifesto ou logs. `MONITORAMENTO_DB_PATH` usado apenas como origem explícita da migração legada.

Documentar que SMTP 587 não funciona no plano gratuito do Render. Não criar primeiro administrador no build ou por senha em variável de ambiente. Disponibilizar CLI de criação e recuperação administrativa sem Tkinter.

## Verificação e critérios de aceite

Testes primeiro para contratos de persistência, depois implementação. Executar a suíte existente adaptando fixtures que manipulam SQL diretamente, sem enfraquecer os cenários. Adicionar integração no emulador Firestore com projeto fictício `demo-monitoramento-ativo`, namespace isolado por teste e proteção contra destino remoto. Validar login e logout, perfis e isolamento entre unidades, CSRF, recuperação e revogação, duplicidade de usuários, último administrador, boletins PDF fictícios, importação/reimportação, rascunho/envio/revisão, encerramento, alertas, prazos, confirmações e dashboards.

Testar concorrência, retries, conflito de versões, indisponibilidade sem fallback, migração fictícia e falha entre lotes. Testes unitários com cliente controlado complementam o emulador; não substituem verificação real do SDK. Se ambiente impedir o emulador, registrar explicitamente integração não validada e não declarar prontidão completa. Não usar documentos reais do projeto remoto para testes.

## Decisões do implementador

Detalhar módulos, índices, tamanhos de lotes, abstração de relógio e fixtures durante o plano. Manter nomes de variáveis acima consistentes no código e documentação. Firestore remoto e permissões reais serão verificados somente por leitura quando ferramentas autorizadas estiverem disponíveis; emulador não comprova IAM remoto. Entrega inclui alterações locais revisáveis, resultados dos testes, instruções Render e pendências; nenhuma publicação automática.
