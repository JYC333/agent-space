export function researchQuestionDrift(
  currentQuestion: string | null | undefined,
  workflowQuestion: string | null | undefined,
): boolean {
  const current = typeof currentQuestion === "string" ? currentQuestion.trim() : "";
  const workflow = typeof workflowQuestion === "string" ? workflowQuestion.trim() : "";
  return Boolean(workflow) && current !== workflow;
}
