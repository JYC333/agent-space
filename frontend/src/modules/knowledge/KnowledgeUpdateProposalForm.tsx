import { useState } from 'react'
import { GitPullRequestArrow } from 'lucide-react'
import { toast } from 'sonner'
import { knowledgeApi } from '../../api/client'
import { errMsg } from '../../lib/utils'
import type { KnowledgeContentFormat, KnowledgeItem, KnowledgeUpdateProposalBody, Proposal } from '../../types/api'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardTitle } from '../../components/ui/card'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Textarea } from '../../components/ui/textarea'
import { KNOWLEDGE_FORMATS, parseOptionalConfidence, parseTags, validateConfidence } from './utils'

interface UpdateForm {
  title: string
  content: string
  content_format: KnowledgeContentFormat
  tags: string
  confidence: string
  rationale: string
}

interface KnowledgeUpdateProposalFormProps {
  item: KnowledgeItem
  onProposalCreated: (proposal: Proposal) => void
}

export default function KnowledgeUpdateProposalForm({ item, onProposalCreated }: KnowledgeUpdateProposalFormProps) {
  const [form, setForm] = useState<UpdateForm>({
    title: item.title,
    content: item.content,
    content_format: item.content_format,
    tags: item.tags.join(', '),
    confidence: item.confidence === null ? '' : String(item.confidence),
    rationale: '',
  })
  const [submitting, setSubmitting] = useState(false)

  function setField<K extends keyof UpdateForm>(key: K, value: UpdateForm[K]) {
    setForm(f => ({ ...f, [key]: value }))
  }

  async function submitUpdateProposal() {
    if (!form.title.trim() || !form.content.trim()) {
      toast.error('Title and content are required')
      return
    }
    const confidence = parseOptionalConfidence(form.confidence)
    if (!validateConfidence(confidence)) {
      toast.error('Confidence must be a number from 0 to 1')
      return
    }
    const body: KnowledgeUpdateProposalBody = {
      title: form.title.trim(),
      content: form.content,
      content_format: form.content_format,
      tags: parseTags(form.tags),
      confidence,
      rationale: form.rationale.trim() || null,
      verification_status: item.verification_status,
      reflection_status: item.reflection_status,
    }
    setSubmitting(true)
    try {
      const p = await knowledgeApi.proposeUpdate(item.id, body)
      onProposalCreated(p)
      setField('rationale', '')
      toast.success('Update proposal created')
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card>
      <div className="flex items-center justify-between gap-3 mb-4">
        <CardTitle>Propose Update</CardTitle>
        <Badge variant="outline">proposal only</Badge>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <Label>Title</Label>
          <Input value={form.title} onChange={e => setField('title', e.target.value)} />
        </div>
        <div>
          <Label>Content format</Label>
          <Select value={form.content_format} onChange={v => setField('content_format', v as KnowledgeContentFormat)} options={KNOWLEDGE_FORMATS.map(f => ({ value: f, label: f }))} />
        </div>
        <div>
          <Label>Tags</Label>
          <Input value={form.tags} onChange={e => setField('tags', e.target.value)} />
        </div>
        <div>
          <Label>Confidence</Label>
          <Input value={form.confidence} onChange={e => setField('confidence', e.target.value)} placeholder="optional, 0 to 1" />
        </div>
        <div className="md:col-span-2">
          <Label>Content</Label>
          <Textarea value={form.content} onChange={e => setField('content', e.target.value)} />
        </div>
        <div className="md:col-span-2">
          <Label>Rationale</Label>
          <Textarea value={form.rationale} onChange={e => setField('rationale', e.target.value)} placeholder="Optional. Backend will default if empty." />
        </div>
      </div>
      <Button className="mt-4" onClick={submitUpdateProposal} disabled={submitting}>
        <GitPullRequestArrow className="size-4 mr-1" />Submit update proposal
      </Button>
    </Card>
  )
}
