# Importação conferida de Tuberculose

Continuação autorizada pelo usuário. O PDF de Downloads é referência local de estrutura; seu conteúdo pessoal não será copiado para o projeto, testes ou conversa.

Abordagem escolhida: extração limitada e prévia conferência, seguida de confirmação explícita. Importação automática sem conferência permitiria interpretar células mescladas incorretamente. Reescrever o analisador agregado não é necessário; ele permanece disponível.

Criar amostra inteiramente fictícia na geometria de 16 colunas observada. Extrair apenas colunas inequívocas: notificação, data de notificação, nome, contatos, HIV/TARV/cultura/TRM/histopatologia/TS/TDO, encerramento e sua data. Não inferir Forma, baciloscopias ou transferência das células mescladas. Exibir aviso dessas limitações. Não validar regras clínicas ou afirmar dicionário SINAN vigente.

Página da Vigilância recebe PDF, competência e unidade cadastrada (conta de unidade ativa). A unidade informada no documento, se presente, deve corresponder à seleção; normalizar somente acentos, espaços e caixa, sem aproximação por similaridade. Recusar códigos/datas inválidos, contatos inconsistentes, identificadores duplicados, cabeçalhos desconhecidos, arquivo sem registros, mais de uma unidade e formatos incompatíveis. Não converter arquivo vazio em confirmação de ausência.

Prévia mostra todos os registros e campos que serão gravados. Armazenamento apenas em memória temporária, vinculado ao usuário, com token aleatório, validade de 10 minutos e limite global de 40 MB. Confirmar exige sessão Vigilância, troca de senha concluída, CSRF e o token da própria conta. O PDF é descartado após confirmação; prévias expiram e se perdem ao reiniciar. Uso previsto: um processo do servidor; múltiplos workers exigirão armazenamento temporário compartilhado.

Confirmar alimenta monthly_store e mantém auditoria, idempotência e conflitos. Não importar competência anterior à mais recente nem competência encerrada. A importação de nova competência não encerra uma anterior que ainda tenha fichas não validadas. Apenas o banco escolhido para os testes será usado na validação.

Não alterar outros fluxos e não publicar ou criar commits. Hanseníase permanece com resumo agregado.
