# Firestore Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or executing-plans; execução já autorizada pelo usuário. Não fazer commits, deploy ou migração real.

**Goal:** Firestore nativo substitui SQLite no Monitoramento Ativo, preservando comportamento.
**Architecture:** Cliente servidor central, repositórios nativos por domínio e transações com escrita diferida; APIs públicas existentes preservadas. SQLite restrito ao importador legado somente leitura.
**Tech Stack:** Python 3.12, FastAPI, google-cloud-firestore, emulador Firebase, unittest.
**Spec:** docs/superpowers/specs/2026-11-09-firestore-design.md

## Global Constraints

- Projeto `monitoramentoativo`, banco `(default)`, namespace `monitoramento_ativo`; testes somente `demo-monitoramento-ativo` e emulador local.
- Não acessar ou modificar MeuSinan, credenciais ou dados reais; SQLite original intacto.
- Render gratuito, sem persistência local; um worker; e-mail HTTPS como alternativa SMTP.
- Código e configuração ficam locais, sem commits ou publicação.

## Review Focus

- Concorrência entre fechamento/importação/edição: conflito não pode causar perda ou publicação parcial.
- Migração ou reimportação repetida: preservar IDs e impedir duplicidade e mistura com banco ativo.
- Token reutilizado ou usuário desativado: rejeitar acesso mesmo com sessão anteriormente válida.
- Falha de serviço e credenciais: não cair silenciosamente em SQLite nem expor segredos.
- Consultas e dashboards: preservar isolamento por unidade e histórico, sem leituras do banco inteiro em cada página.

## Task 1: Cliente Firestore e emulador

Files: monitoramento/firestore_store.py, tests/firestore_support.py, tests/test_firestore_store.py, firebase.json, firestore.rules, requirements*.txt.
Interface: `get_store()` retorna Store; `Store.get(collection, key)`, `Store.query(collection, filters=())`, `Store.run(fn, guard='domain')`. Callback recebe transação com `get/query/set/delete/next_id`; escritas diferidas até todas as leituras terminarem, guard serializa invariantes do domínio; `key(*parts)` gera hash determinístico.
- [x] Escrever testes de namespace, projeto, rollback, unicidade e concorrência; executar RED.
- [x] Implementar cliente/credenciais sem logs, emulador com proteção de destino, transações com retries e consultas filtradas; executar GREEN no emulador.

## Task 2: Persistência mensal nativa

Files: monitoramento/monthly_store.py, tests/test_firestore_monthly.py.
Consumes: Store da tarefa 1. Produces: mesmas assinaturas e dataclasses públicas atuais, sem SQL.
- [x] Criar testes de importação, estados, revisões, solicitações, indicadores e concorrência; executar RED.
- [x] Implementar todas as funções públicas com documentos e transações, incluindo publicação atômica de importações grandes em lotes; executar GREEN no emulador (10 testes novos).
- [x] Cobrir falha entre lotes e consulta de versões publicadas; adaptar testes SQL sem reduzir cenários (10 testes existentes passando).

## Task 3: Autenticação e acompanhamento

Files: monitoramento/auth.py, monitoramento/tracking_store.py, monitoramento/reset_admin_password.py, tests/test_firestore_auth.py.
Consumes: Store. Produces: contratos públicos existentes e CLI sem GUI.
- [x] Testar login, CSRF, hashes, unicidade, bloqueio, tokens únicos, revogação e último administrador no emulador; executar RED.
- [x] Implementar transações por domínio auth, gerações de sessão e recuperação; acompanhamento por agravo/registro. Executar GREEN.
- [x] Adaptar fixtures antigas para emulador e substituir manipulação SQL por documentos equivalentes; executar suíte.

## Task 4: Migração fictícia e Render gratuito

Files: monitoramento/migrate_sqlite.py, monitoramento/recovery_mail.py, main.py, render.yaml, .env.example, .gitignore, README.md, tests/test_firestore_migration.py.
- [x] Testar dry-run read-only, destino vazio, idempotência, referências e credenciais inválidas; executar RED.
- [x] Implementar migração explícita em namespace de preparação, sem executar em produção; invalidar sessões e tokens. Executar GREEN com SQLite fictício.
- [x] Adicionar provedor de e-mail HTTPS para Render gratuito mantendo SMTP opcional e testes simulados; não enviar e-mails reais.
- [x] Preparar manifesto Render, health check, secret file e documentação das variáveis e CLI; nenhum deploy.

## Task 5: Verificação e revisão

- [x] Executar suíte completa com emulador, dados fictícios e credenciais anônimas; confirmar nenhum SQLite local tocado.
- [x] Revisão independente das mudanças e correções verificadas; conferir segredos e arquivos rastreados.
- [x] Registrar resultados, limitações e passos pendentes de produção; nenhuma publicação.

## Decisões de execução

- Trabalhar no diretório autorizado já aberto: alterações ficam revisáveis no IDE; não criar branch/commit ou mudar checkout durante o trabalho.
- Autorização explícita de implementação dispensa nova aprovação do plano. Delegação técnica autorizada pela skill subagent-driven-development, com arquivos de responsabilidade separados; revisão final independente.
- Dependências atuais serão reaproveitadas para a linha de base antes de instalar ferramentas locais adicionais.

## Resultado final

117 testes completos passaram no emulador (380,676 s); pip check sem conflitos; wheels Linux/Python 3.12 resolvidas; configuracoes e AST validos; sem credenciais candidatas ao Git. Revisao independente encontrou tres falhas corrigidas com regressao. Consulte docs/validacao-firestore.md para evidencias, incidente local de teste, preservacao do SQLite e pendencias de producao. Nenhum commit, push, deploy ou migracao real.
