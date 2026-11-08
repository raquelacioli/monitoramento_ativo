# Estabilidade e controle de acesso — 2026-11-08

Escopo autorizado: corrigir os problemas encontrados na revisão, preservando as alterações existentes e a arquitetura FastAPI/SQLite.

1. Restaurar a importação da aplicação e executar a suíte existente.
2. Acrescentar testes de regressão para troca obrigatória de senha e histórico entre unidades; corrigir as falhas demonstradas.
3. Investigar falhas adicionais da suíte, incluindo ordenação do histórico.
4. Documentar instalação e dependências dos testes; executar a suíte completa e solicitar revisão independente.

Critério de conclusão: aplicação importável, testes passando, alterações revisadas e limitações documentadas. Importação individual por PDF e validação clínica não fazem parte desta correção.

Trabalho no diretório atual para preservar e testar as alterações locais ainda não commitadas. Não criar commits ou publicar.

## Evidências

- Antes: erro de sintaxe em views.py impedia importar main; uma execução também demonstrou ordenação instável nos eventos mensais.
- Regressões reproduzidas e corrigidas: operações com troca obrigatória de senha, valor anterior de outra unidade e histórico com horários repetidos.
- A suíte original também demonstrou dependência entre testes: exclusão/recriação de conta alterava a senha esperada por testes posteriores. As contas iniciais agora são restauradas antes de cada teste de rotas.
- Verificação de sintaxe: 21 arquivos Python; importação da aplicação e respostas 200 em / e /api/status confirmadas.
- Revisão independente das alterações: nenhum problema importante encontrado.
- Suíte final: python -m unittest discover -s tests -q — 63 testes em 97,581 segundos, todos aprovados.
- Mantida a arquitetura existente; a dependência HTTPX dos testes foi declarada e o aviso de descontinuação documentado. Uma instalação nova de dependências não foi executada nesta etapa.
