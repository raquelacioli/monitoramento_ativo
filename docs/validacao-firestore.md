# Validação local da integração Firestore — 2026-11-09

## Escopo e limites

Alterações restritas ao repositório Monitoramento Ativo. Nenhuma alteração no MeuSinan, deploy, publicação de regras, commit, push, migração de produção ou envio real de e-mail foi realizado. O Firestore remoto não foi usado para os testes. A validação usa o projeto fictício `demo-monitoramento-ativo`, emulador local em `127.0.0.1:8085`, credenciais anônimas e namespaces `test_*` isolados.

## Verificações

- Linha de base anterior à troca: 84 testes passaram com bancos temporários fictícios.
- Suíte final completa: **117 testes passaram, zero falhas e zero erros**, em 380,676 segundos, com emulador local e dados fictícios. Comando: `python -B -c "import unittest; r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests')); raise SystemExit(not r.wasSuccessful())"`, com host do emulador e projeto fictício configurados. Foi usado diagnóstico periódico de stack para confirmar progresso durante os cálculos de hashes; não houve timeout imposto aos testes.
- Testes específicos verificam 1.000 fichas, publicação em lotes, falhas e retomada, uso único de tokens, isolamento por unidade, histórico, observações, alertas, dashboards, concorrência e migração fictícia com reconciliação.
- Rotas de login, páginas e `/healthz` verificadas pelo TestClient; erro de serviço resulta em resposta sanitizada.
- `pip check`: sem conflitos no ambiente utilizado.
- Resolução completa das dependências de produção para Linux x86_64/Python 3.12: wheels disponíveis e download concluído. Isso verifica distribuição e resolução, não execução em Linux/Render.
- Sintaxe Python, JSON, manifesto YAML e `git diff --check` verificados. Somente aviso Git de conversão futura de LF para CRLF.
- Busca por padrões de credenciais em arquivos rastreados e novos candidatos ao Git: nenhuma correspondência. Bancos, backup, arquivos de credenciais, caches, ferramentas e logs estão ignorados.

## Revisão independente e correções

1. Consulta de lote antes da publicação e leitura de marcador depois dela podia expor 80 de 180 fichas. Teste determinístico reproduziu a falha; snapshots Firestore read-only em toda operação de leitura corrigiram o caso.
2. Migração aceitava esquema incompleto de usuários. Testes reproduziram o problema; validação de colunas, hashes, salts, identificadores e origem vazia agora ocorre antes de qualquer escrita.
3. Admissão da migração não conflituava com gravações de outros domínios. Todas mutações agora tocam uma guarda de namespace transacional; teste com dois clientes independentes verifica que não há mistura ou sobrescrita.
4. Namespace com migração parcial podia ser lido. Teste reproduziu o problema; leituras e mutações são bloqueadas até reconciliação e estado `complete`.

## Incidente local de teste e preservação do SQLite

Um teste novo foi executado antes de a função de autenticação antiga ser substituída e sem caminho SQLite temporário. Isso criou acidentalmente um usuário fictício no SQLite local, junto a seus artefatos de recuperação. O erro foi identificado durante a execução, comunicado ao usuário e limpo com critérios exatos de nome fictício, ID e instante de criação. Foram removidos somente esse usuário e seus artefatos identificados; o contador foi restaurado. Nenhum registro preexistente foi alterado pela limpeza. Não houve migração ou escrita no Firestore de produção.

Não existe uma cópia byte a byte anterior a esse incidente. Após a limpeza, foi preservada a cópia `instance/monitoramento.pre-firestore.sqlite3`, ignorada pelo Git, e registrado o hash SHA-256 `09928b8aacb4ade2d31229adf51eb1cafbcdeef4043ab4585df752aee8b7153e`. O arquivo SQLite e essa cópia foram conferidos como idênticos; verificações posteriores usam esse hash para detectar alterações.

As fixtures agora exigem host local do emulador, projeto fictício e namespace isolado e fixam `MONITORAMENTO_DB_PATH=:memory:` como proteção adicional contra chamadas legadas. O runner também remove o caminho de credenciais do processo filho. SQLite é importado somente pelo importador legado e pelos testes de migração.

## Pendências antes de publicação

- Configurar Secret File e permissões IAM da conta exclusiva; validar acesso real após autorização. O emulador não verifica IAM de produção.
- Configurar domínio/remetente e chave do provedor HTTPS de recuperação; envio real não foi testado.
- Autorizar separadamente migração de dados reais, eventual criação de administrador, publicação no GitHub e deploy Render.
- Render gratuito suspende sem tráfego e perde prévias em memória; dados confirmados permanecem no Firestore. Usar somente um worker.
- A suíte emite aviso de depreciação do TestClient Starlette com HTTPX, já presente antes da integração.
- As dependências usam intervalos de versões; futuros builds podem resolver versões diferentes das verificadas.
- Permanecem as limitações documentais/clínicas do projeto demonstrativo. A integração do banco não constitui validação para uso com dados reais de pacientes.

Instruções e variáveis completas: [guia de implantação](implantacao-render-firestore.md).
