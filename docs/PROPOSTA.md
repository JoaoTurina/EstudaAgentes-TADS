# Proposta e escopo do MVP

**Problema real:** estudantes com várias disciplinas e prazos precisam transformar uma lista de tarefas em agenda realista com capacidade limitada.

**Objetivo:** propor sessões de estudo respeitando tempo disponível e prazos, identificando o trabalho que não cabe.

**Casos de uso:** cadastrar tarefa; marcar conclusão; gerar proposta; ver justificativa, pendências e traces; aprovar plano.

**Dados:** título, disciplina, data limite, minutos estimados, prioridade, estado de conclusão; planos e traces no SQLite.

**Autonomia:** modo Ollama decide ordenação e oferece dicas/riscos; alocação e guardrails não são delegados à IA. Nenhuma escrita do modelo em ferramentas.

**Validade:** o revisor garante limites de capacidade, prazo, IDs conhecidos e não excesso de minutos por tarefa. A ordenação da triagem é validada como permutação exata dos IDs.

**Escopo excluído:** busca web, calendário externo, notificações, login, otimização global e agentes com ferramentas dinâmicas. Consulte o README para os limites detalhados.

**Critérios de sucesso demonstráveis:** plano de ponta a ponta; trace das etapas; testes passando; pendência visível quando a capacidade não basta; aprovação humana separada.
