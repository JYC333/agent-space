import { Copy } from 'lucide-react'
import { SpaceLink as Link } from '../../core/spaceNav'
import { toast } from 'sonner'
import type { Proposal } from '../../types/api'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'

interface KnowledgeProposalNoticeProps {
  proposal: Proposal
}

export default function KnowledgeProposalNotice({ proposal }: KnowledgeProposalNoticeProps) {
  async function copyId() {
    await navigator.clipboard.writeText(proposal.id).catch(() => null)
    toast.info('Proposal ID copied')
  }

  return (
    <Card className="border-accent/50">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="secondary">{proposal.proposal_type}</Badge>
            <Badge variant="outline">{proposal.status}</Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            Proposal created: <span className="font-mono select-all text-foreground">{proposal.id}</span>
          </p>
        </div>
        <div className="flex gap-1.5">
          <Button size="sm" variant="outline" onClick={copyId}>
            <Copy className="size-3.5" />Copy ID
          </Button>
          <Button size="sm" asChild>
            <Link to={`/proposals/${proposal.id}`}>Review</Link>
          </Button>
        </div>
      </div>
    </Card>
  )
}
