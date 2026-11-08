# Importação conferida de Tuberculose — Implementation Plan

**Goal:** Criar amostra fictícia e permitir importar registros reconhecidos após conferência.

**Architecture:** Extrator separado do resumo agregado, prévias em memória com limite/expiração, rotas e apresentação próprias. monthly_store recebe registros estruturados somente na confirmação.

**Tech Stack:** Python 3.12, FastAPI, PyMuPDF, SQLite, unittest.

**Spec:** docs/superpowers/specs/2026-11-08-importacao-tb-design.md

## Global Constraints

- Nunca copiar dados pessoais do PDF de Downloads para artefatos ou saídas.
- Preservar alterações existentes, banco de uso e rotas agregadas.
- Confirmar exige Vigilância, CSRF, token vinculado à conta e competência/unidade conferidas.
- Campos ambíguos não são importados; arquivos vazios não confirmam ausência.

## Tarefas

1. [x] Criar gerador de amostra fictícia de 16 colunas e testes de extração/recusa. Observar falhas antes de implementar.
2. [x] Implementar extrator em monitoramento/bulletin_import.py, sem persistência.
3. [x] Testar e implementar prévias temporárias, limites, consumo por conta e expiração.
4. [x] Testar e implementar importação conferida por /vigilancia/importar, /api/boletins/previsualizar e /api/boletins/confirmar. Prévia não altera banco; confirmação usa monthly_store, com proteção de competências.
5. [x] Documentar limitações, gerar PDF fictício compartilhável, verificar o arquivo real apenas em memória sem expor valores, executar suíte completa e solicitar revisão independente.

## Progresso

Reconhecimento local: uma página paisagem, tabela de 7 linhas e 16 colunas com duas linhas de cabeçalho. Dados pessoais não registrados.

- Amostra gerada somente com valores fictícios e geometria conhecida; gerador não lê arquivo de paciente.
- O extrator usa os retângulos das células para preservar espaços e ordem das palavras. A extração tabular inicial do PyMuPDF rearranjava texto nos cabeçalhos pequenos, reproduzido no teste sintético.
- Máscaras vazias de data são mantidas vazias; não houve necessidade de converter anos com dois dígitos.
- Testes direcionados: extração e proteção de entrada (10), controle de prévias, fluxo HTTP de confirmação/cancelamento, CSRF/perfil e guarda transacional de competência passaram após falhas reproduzidas.
- Revisão independente encontrou duas unidades no mesmo cabeçalho não bloqueadas. Cenário reproduzido com PDF fictício e corrigido. Acrescentadas regressões para múltiplas tabelas e primeira linha incompleta.
- Limitação deliberada: uma tabela por página, sem interpretação das células mescladas; compatibilidade com outros layouts exige novo reconhecimento e testes.
- Prévias são locais a um processo e expiradas são removidas na próxima operação da fila; isso está documentado. Não houve implantação, commit nem gravação dos registros do PDF original.
- Verificação final: 82 testes aprovados em 152,569 segundos; sintaxe de 28 arquivos Python validada; quatro rotas novas presentes no OpenAPI; git diff --check sem erros. Mantido o aviso já documentado de descontinuação do HTTPX.
- O arquivo original foi validado somente em memória: cinco registros reconhecidos. A amostra gerada foi verificada separadamente: dois registros fictícios. Nenhum registro original foi importado no banco de uso.
