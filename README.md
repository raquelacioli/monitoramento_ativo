# Monitoramento Ativo

Aplicação demonstrativa para acompanhamento de Tuberculose e Hanseníase com FastAPI.

A persistência atual usa **Cloud Firestore**, sem SQLite no servidor. Consulte o [guia de Firestore e Render](docs/implantacao-render-firestore.md) para variáveis, credenciais, testes com emulador, migração legada e publicação. Nenhuma migração ou implantação ocorre automaticamente.

## Preparar o ambiente e executar os testes

Use Python 3.12 atualizado, versão utilizada na verificação deste projeto. No PowerShell, dentro de `monitoramento_ativo`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
npx.cmd --yes firebase-tools@15.35.0 emulators:start --only firestore --project demo-monitoramento-ativo
```

Em outro terminal, execute `.\.venv\Scripts\python.exe -B scripts/run_tests.py`. Os testes usam namespaces isolados no emulador, dados fictícios e envio de e-mail simulado. Somente os testes da migração criam SQLite temporário; o banco original não é necessário. Para instalar somente as dependências da aplicação, use `requirements.txt`.

Para iniciar o servidor local quando a porta estiver livre:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

O ambiente atual de testes usa HTTPX 0.28.1. Versões recentes do Starlette podem emitir um aviso de descontinuação desse cliente; a migração do cliente de testes deve ser validada separadamente. As dependências de produção continuam com intervalos de versão; esta configuração não é um arquivo de versões totalmente fixadas.

## Acessar a aplicação

Quando o servidor já estiver em execução, abra `http://127.0.0.1:8000`. A página inicial apresenta os módulos disponíveis; os painéis de acompanhamento exigem login.

Não inicie outra instância se a porta 8000 já estiver ocupada pelo servidor deste projeto.

Se o login informar que a tentativa não pôde ser validada, use o formulário renovado e tente novamente. Abrir várias abas de login ou deixar a página aberta por mais de dez minutos pode invalidar a tentativa anterior. Se estiver usando o navegador interno do VS Code e o problema persistir, abra a mesma URL no Edge ou Chrome. O sistema mantém a verificação de segurança; esse erro ocorre antes da conferência da senha.

## Criar o primeiro administrador

No terminal do VS Code, abra a pasta `monitoramento_ativo` e execute:

```powershell
.\.venv\Scripts\python.exe -m monitoramento.auth_admin
```

O programa solicitará um nome de usuário e uma senha com pelo menos 12 caracteres. A senha é digitada sem aparecer na tela e não deve ser compartilhada ou gravada no código. Depois, entre em `/login` e use a área de administração para criar contas e atribuí-las aos perfis e unidades.

Na página **Contas de acesso**, o administrador também pode definir uma senha temporária para uma conta ativa. A pessoa deve trocar essa senha no próximo acesso; as sessões anteriores são encerradas. O formulário exige confirmação da senha e proteção CSRF.

## Redefinir a senha de uma conta Administradora

Se a recuperação por e-mail não estiver disponível, abra um terminal do VS Code na pasta `monitoramento_ativo` e execute:

```powershell
.\.venv\Scripts\python.exe -m monitoramento.reset_admin_password
```

O terminal mostrará o projeto e namespace Firestore para conferência. Informe a conta Administradora ativa, confirme com `REDEFINIR` e digite uma nova senha mascarada, com pelo menos 12 caracteres. Use as mesmas variáveis Firestore do servidor. O comando não cria contas; redefine a senha e revoga sessões anteriores. Não é necessário reiniciar o servidor.

## Uso e limitações desta versão

### Importação individual de Tuberculose com conferência

Na conta Vigilância, abra `/vigilancia/importar` ou o link no painel da Vigilância. Selecione a competência, uma unidade com conta ativa e um PDF do layout reconhecido. A unidade escrita no documento deve corresponder à seleção, desconsiderando somente acentos, caixa e espaços.

A leitura mostra uma prévia dos campos, sem criar fichas. Confira todas as linhas e use **Conferi os registros — confirmar importação** para gravar no histórico mensal. **Descartar prévia sem importar** libera a prévia sem gravar registros. As fichas importadas aparecem em `/monitoramento-mensal`, com acesso limitado à unidade vinculada.

O leitor aceita uma tabela de 16 colunas por página e uma única unidade por arquivo. Extrai número/data de notificação, nome, contatos, HIV, TARV, cultura, TRM-TB, histopatologia, teste de sensibilidade, TDO, situação/data de encerramento. Forma, baciloscopias e transferência nas células mescladas não são importadas. Datas preenchidas precisam de ano com quatro dígitos; máscaras de data vazias permanecem vazias. Campos/códigos são conferidos com o dicionário já disponível no aplicativo, que ainda depende de validação documental oficial. Hanseníase mantém somente o resumo agregado.

A confirmação bloqueia competências encerradas/anteriores e impede abrir uma nova competência enquanto houver fichas não validadas na anterior. Reenvios idênticos não criam cópias; diferenças nos dados originais geram conflitos preservando os registros existentes. PDF vazio não confirma ausência de pacientes.

Prévias ficam apenas na memória do processo: validade de 10 minutos, até duas por usuário, até 50 no total e limite de 40 MB de conteúdo contabilizado. Expiradas são removidas na próxima operação da fila; confirmação/cancelamento removem a prévia imediatamente. Reiniciar o servidor perde as prévias. Use um único processo/worker neste fluxo; múltiplos workers exigem um armazenamento temporário compartilhado. O FastAPI pode usar arquivos temporários durante o recebimento do upload.

Para gerar novamente a amostra sem dados reais:

```powershell
.\.venv\Scripts\python.exe tests/bulletin_pdf_factory.py
```

Ela será criada em `docs/exemplos/boletim_tuberculose_ficticio.pdf`, com a unidade **Unidade ficticia de testes**. Para experimentá-la na interface, cadastre previamente uma conta de unidade ativa com esse nome. Os testes criam suas próprias contas e bancos temporários; não fazem esse cadastro no banco de uso. O PDF original de Downloads nunca é copiado para a amostra nem usado pelos testes.

- Os registros são fictícios e servem somente para demonstração e testes.
- A unidade pode atualizar a data do último comparecimento diretamente na linha do registro; o valor fica salvo junto às demais alterações demonstrativas no Firestore.
- Os arquivos em branco oficiais fornecidos para Tuberculose e Hanseníase foram usados para transcrever os rótulos e códigos explicitamente informados. Isso não valida por si só o dicionário SINAN completo, as regras clínicas, as condicionais ou a versão vigente.
- Somente o perfil Vigilância pode abrir a área de upload e chamar o endpoint de análise de PDF; o perfil Unidade não recebe o formulário nem a navegação para Vigilância.
- O endpoint `/api/boletins/analisar` continua produzindo somente um resumo agregado. A importação individual de Tuberculose usa o fluxo separado de prévia/confirmação descrito acima. Um formulário em branco reconhecido no resumo não encerra registros de competências anteriores.
- O resumo usa as posições de contatos de cada tabela separadamente. Registros reconhecidos sem colunas de contatos, com valores ilegíveis ou com examinados acima de identificados ficam para conferência e não entram nas somas de contatos. A tela sinaliza os totais parciais. Um campo Unidade explicitamente vazio não herda a unidade da página anterior.
- A camada `monitoramento.monthly_store` mantém competências, dados originais, alterações, revisões, conflitos de reimportação e observações da Vigilância. Os endpoints `/api/historico/...` expõem leitura/comparação, rascunho e envio; `/api/vigilancia/competencias/...` permite abrir/encerrar competência; `/api/vigilancia/historico/.../revisar` registra validação ou devolução. As importações dessa camada recebem linhas já estruturadas e não são alimentadas pelo atual analisador agregado de PDFs.
- O painel `/comunicacao` implementa solicitações e respostas mensais com histórico de eventos: a Vigilância pode enviar sugestões automáticas, criar solicitações manuais, pedir complementação, iniciar/revisar e concluir; a unidade pode salvar rascunhos e responder. O backend limita a unidade aos próprios registros. O painel da Vigilância inclui a visão consolidada e os indicadores de comunicação.
- Cada solicitação pode ser vinculada a um campo editável do boletim ou permanecer como observação geral. A tela de detalhe mostra o campo, os valores da competência anterior e da competência aberta, a orientação da Vigilância, a resposta e a trilha histórica. A edição estruturada usa a validação mensal existente; a justificativa textual fica armazenada separadamente e nunca altera o valor oficial. Pendências automáticas ainda abertas são mantidas sem gerar cópias mensais.
- Nos módulos demonstrativos, a equipe encontra o campo editável na coluna “Observação da unidade” e salva pela ação “Salvar alterações”. As solicitações mensais da Vigilância aparecem na área “Observações da Vigilância e resposta da unidade”. As fichas da importação individual são acessadas no painel `/monitoramento-mensal`; os módulos demonstrativos mantêm sua própria lista fictícia. A resposta textual permanece separada dos valores estruturados.
- O painel `/monitoramento-mensal` apresenta prazos, percentuais de envio e situações por unidade e agravo, além da situação individual de cada notificação: verde para enviada/validada, amarelo para rascunho/devolução, vermelho para ficha sem atualização após o prazo e neutro enquanto aguarda o prazo. Os indicadores podem ser usados como filtros. Os detalhes de cada notificação mostram os nomes oficiais dos campos do agravo e os valores atual e anterior, junto às observações, respostas e histórico; a resposta da unidade pode ser registrada ali na competência aberta. O identificador é apresentado com o rótulo oficial “Nº da Notificação Atual”. A classificação da unidade permanece independente: vermelho só é atribuído quando não há envio após o prazo efetivo; amarelo identifica atualização parcial ou reconciliação; verde exige envio de todos os registros; azul identifica boletim coberto com zero pacientes e confirmação pendente ou concluída. A prorrogação substitui o prazo inicial.
- Dentro dos detalhes da ficha mensal, a unidade pode salvar rascunho ou enviar explicitamente a atualização à Vigilância. O envio é auditado e bloqueia novas alterações enquanto está em análise; para corrigir, a Vigilância devolve a ficha, que pode então ser editada e reenviada. A justificativa textual permanece separada dos valores oficiais.
- A cobertura do boletim é registrada por unidade em `import_monthly_records(..., unit_coverage=(...))`. Registros com pacientes têm suas unidades inferidas; um boletim vazio só permite classificar como silenciosa uma unidade explicitamente incluída na cobertura. Unidade sem cobertura, sem importação ou com conflito permanece indisponível, nunca silenciosa por inferência. O analisador PDF atual continua agregado e não alimenta automaticamente essas importações estruturadas.
- Em boletins cobertos sem pacientes, a unidade pode confirmar ausência, informar pacientes não listados ou solicitar conferência. Se pacientes da competência anterior não aparecem, a unidade não pode confirmar a ausência diretamente; a reconciliação é registrada pela Vigilância. Essas ações são auditadas e não alteram nem excluem fichas clínicas, nem classificam abandono, cura, óbito ou transferência.
- A única sugestão automática nesta etapa é a diferença numérica válida entre contatos identificados e examinados. Ela solicita conferência, sem presumir atendimento, falta de atendimento, abandono ou encerramento. Todas as demais regras de alerta e critérios clínicos aguardam validação documental oficial.
- A comparação mensal é técnica (presente, novo, alterado ou não atualizado) e não interpreta códigos clínicos. Campos em branco são mantidos como valores, sem inferir “não aplicável” ou “ignorado”.
- Os campos categóricos usam códigos textuais e descrições separadas. A camada mensal armazena ambos; a importação mantém também o valor original extraído. Campos de identificação ficam protegidos na edição mensal, e “Total de contatos identificados” de Tuberculose está marcado como automático e não pode ser alterado pela unidade.
- A legenda de Histopatologia confirmada pelo responsável está implementada com os códigos 1 a 5, incluindo “4 - Em andamento”. O rótulo informado para TRM-TB código 2 (“Não detectável resistente à rifampicina”) é mantido literalmente, sem interpretação clínica; sua semântica permanece pendente de validação. Os tópicos automáticos 1 a 4 da ficha de Tuberculose também não foram inferidos nem automatizados.
- A importação individual é limitada ao layout reconhecido de Tuberculose e aos campos inequívocos. Para ampliar a cobertura, continuam necessários os dicionários SINAN oficiais vigentes, a validação do rótulo de TRM-TB código 2 e a identificação documentada dos tópicos automáticos 1 a 4. O leitor não infere valores das células mescladas.
- Não use dados reais de pacientes nesta versão. Antes disso, são necessários validação documental e avaliação de segurança e privacidade, incluindo proteção do banco local, backups e implantação com HTTPS.
- Para uma implantação HTTPS, configure `MONITORAMENTO_COOKIE_SECURE=1` no ambiente do processo antes de iniciar a aplicação.
- A autenticação mantém PBKDF2 e os perfis existentes, com contas e sessões no Firestore; Firebase Authentication não é necessário. A recuperação está disponível em `/recuperar-senha`, usa token aleatório de uso único (30 minutos, somente hash armazenado), revoga sessões após redefinição e limita solicitações por IP e e-mail. O token segue no fragmento `#token` do link e a página o envia no POST sem incluí-lo em requisições GET ou no cabeçalho Referer. Configure um provedor HTTPS no Render gratuito conforme o guia; SMTP permanece opcional.
- Endereços para recuperação são opcionais e devem ser cadastrados/alterados somente pelo administrador em Contas de acesso, após confirmar que a pessoa controla o endereço. Contas já existentes começam sem e-mail e não podem recuperar a senha até esse cadastro. A recuperação não altera perfil nem unidade.
- Para configurar o SMTP, copie `.env.example` para `.env` e preencha as credenciais de um provedor aprovado, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` e `APP_BASE_URL`. A URL base deve ser a origem HTTPS pública confiável; o sistema não usa o cabeçalho `Host` recebido. O e-mail é enviado com STARTTLS. Use `MONITORAMENTO_COOKIE_SECURE=1` em produção HTTPS. Sem configuração válida, a resposta pública continua genérica e nenhum link é enviado; o servidor registra apenas aviso sem e-mail/token. Testes automatizados simulam o serviço e não enviam mensagens reais.
