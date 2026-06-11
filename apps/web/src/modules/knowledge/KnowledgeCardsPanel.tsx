import { Card } from '../../components/ui/card'
import { EmptyState } from '../../components/ui/empty-state'
import KnowledgeSectionHeader from './KnowledgeSectionHeader'

/**
 * Cards sub-area inside the Knowledge module. Cards are review/learning units
 * derived from Notes, Wiki items, and Sources. The review queue and FSRS
 * scheduling UI are intentionally out of scope for this slice — this is a clean
 * placeholder, not a fake review surface. See .agent/modules/spaced-repetition.md.
 */
export default function KnowledgeCardsPanel() {
  return (
    <div className="p-6 space-y-6">
      <KnowledgeSectionHeader
        section="cards"
        description="Review cards derived from Notes, Wiki items, and Sources."
      />
      <Card>
        <EmptyState
          title="Cards are coming soon"
          description="Spaced-repetition review cards generated from your Notes, Wiki, and Sources will appear here."
        />
      </Card>
    </div>
  )
}
