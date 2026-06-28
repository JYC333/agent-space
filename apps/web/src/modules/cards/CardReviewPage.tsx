import { Card, CardTitle } from '../../components/ui/card'

export default function CardReviewPage() {
  return (
    <Card>
      <CardTitle>Cards / Review</CardTitle>
      <p className="text-muted-foreground text-sm text-center py-10">
        Spaced repetition card review is coming — the database schema (<code className="font-mono text-xs bg-muted px-1 py-0.5 rounded">cards</code>, <code className="font-mono text-xs bg-muted px-1 py-0.5 rounded">card_review_states</code>, <code className="font-mono text-xs bg-muted px-1 py-0.5 rounded">card_reviews</code>) is in place; the server module and review UI are not yet implemented.
        See <code className="font-mono text-xs bg-muted px-1 py-0.5 rounded">.agent/modules/spaced-repetition.md</code> for the spec.
      </p>
    </Card>
  )
}
