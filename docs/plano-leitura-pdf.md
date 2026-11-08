# Confiabilidade da leitura dos boletins — 2026-11-08

Continuação autorizada da revisão e correção do sistema.

Os dois PDFs locais estão em branco. Não há amostra preenchida anonimizada para validar uma importação individual. Preservar o fluxo agregado enquanto se corrige a extração já disponível.

1. Reproduzir a unidade fictícia extraída de um campo Unidade vazio.
2. Reproduzir totais incorretos em múltiplas tabelas com posições de colunas diferentes.
3. Tratar ausência de colunas de contatos como dados indisponíveis para conferência, preservando a contagem dos registros reconhecidos.
4. Validar com PDFs sintéticos, os modelos locais e a suíte completa; solicitar revisão independente.

Não modificar dados do banco de uso da aplicação, não automatizar classificação clínica e não publicar.

## Evidências e decisões

- Reproduzidas falhas de unidade vazia, posições diferentes entre tabelas, contatos sem colunas e examinados acima de identificados. Corrigidas com seis cenários de teste, incluindo unidade em linha separada e mudança de página.
- O resumo identifica como parciais as somas que excluem registros com contatos ausentes ou inconsistentes.
- Os dois PDFs em branco fornecidos no projeto foram processados: zero unidades inventadas e zero registros sem unidade em ambos.
- Revisão independente não confirmou problemas importantes nas mudanças. Possível duplicação de linhas pelo extrator em tabelas sobrepostas não foi reproduzida; não se aplicou deduplicação sem evidência, pois linhas iguais podem representar dados diferentes.
- A importação individual permanece pendente de exemplos preenchidos com dados fictícios e da validação documental já descrita no README.
- Verificação final: 69 testes aprovados em 96,059 segundos; sintaxe de 22 arquivos Python validada; git diff --check sem erros. Mantido o aviso de descontinuação do HTTPX já documentado.
