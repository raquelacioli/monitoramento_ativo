# Recuperação do formulário de login

Problema apresentado: POST de login retornava JSON com erro de token, deixando a pessoa sem formulário para tentar novamente. Reproduzido com formulário de outra aba e com cookie ausente.

Correção: devolver novo formulário HTML com código 403, novo token/cookie, cabeçalhos sem cache e orientação de nova tentativa ou navegador externo. Nenhuma autenticação ocorre enquanto o token é inválido. Credenciais inválidas continuam retornando 401; autenticação válida mantém redirecionamento normal.

Contas reais foram consultadas somente para confirmar o identificador e o estado ativo da administração. Nenhuma senha foi solicitada, consultada, alterada ou registrada. O uso do navegador interno é uma hipótese para a ausência de cookie; não foi reproduzido nesse navegador.

Validação direcionada: quatro testes de login aprovados, incluindo recuperação de formulário antigo e cookie ausente.

Validação final: 84 testes aprovados em 158,948 segundos; revisão independente sem problemas importantes; git diff --check sem erros. O servidor local também retornou HTML com 403 na tentativa diagnóstica sem token válido, sem utilizar credenciais reais.
