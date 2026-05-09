import { Card, CardTitle } from '../../components/ui/card'

export default function WikiPage() {
  return (
    <Card>
      <CardTitle>Wiki</CardTitle>
      <p className="text-muted-foreground text-sm text-center py-10">
        Wiki (LLM-structured knowledge) is planned — backend <code className="font-mono text-xs bg-muted px-1 py-0.5 rounded">KnowledgeItem</code> model not yet implemented.
        See <code className="font-mono text-xs bg-muted px-1 py-0.5 rounded">.agent/modules/llm-wiki.md</code> for the spec.
      </p>
    </Card>
  )
}
