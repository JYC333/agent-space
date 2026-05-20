import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { agentsApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import ProviderSelector from '../providers/ProviderSelector'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Card } from '../../components/ui/card'
import { errMsg } from '../../lib/utils'

export default function AgentFormPage() {
  const { agentId } = useParams()
  const isEdit = Boolean(agentId)
  const navigate = useNavigate()
  const { activeOperationalSpaceId } = useSpace()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [modelSelection, setModelSelection] = useState<{ provider_id: string; model: string } | null>(null)
  const [loading, setLoading] = useState(isEdit)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!isEdit || !agentId) return
    setLoading(true)
    agentsApi.get(agentId)
      .then(a => {
        setName(a.name)
        setDescription(a.description ?? '')
        if (a.model?.provider_id) {
          setModelSelection({ provider_id: a.model.provider_id, model: a.model.model ?? '' })
        }
      })
      .catch(err => toast.error(errMsg(err)))
      .finally(() => setLoading(false))
  }, [agentId, isEdit])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!activeOperationalSpaceId) {
      toast.error('Select an operational space')
      return
    }
    setSaving(true)
    try {
      const body = {
        name: name.trim(),
        description: description.trim() || null,
        default_model_provider_id: modelSelection?.provider_id ?? null,
        default_model: modelSelection?.model || null,
      }
      if (isEdit && agentId) {
        await agentsApi.update(agentId, body)
        toast.success('Agent updated')
        navigate(`/agents/${agentId}`)
      } else {
        const created = await agentsApi.create(body)
        toast.success('Agent created')
        navigate(`/agents/${created.id}`)
      }
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div className="p-6 flex items-center gap-2 text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Loading…</div>
  }

  return (
    <div className="p-6 max-w-xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">{isEdit ? 'Edit agent' : 'New agent'}</h1>
        <p className="text-sm text-muted-foreground">Configure identity and default model.</p>
      </div>
      <Card>
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground uppercase">Name</label>
            <Input value={name} onChange={e => setName(e.target.value)} required />
          </div>
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground uppercase">Description</label>
            <Input value={description} onChange={e => setDescription(e.target.value)} />
          </div>
          <div className="space-y-2 border-t border-border pt-4">
            <h2 className="text-sm font-medium">Model</h2>
            {!modelSelection && (
              <p className="text-xs text-muted-foreground">This agent will use the system default model unless you choose one.</p>
            )}
            <ProviderSelector value={modelSelection} onChange={setModelSelection} />
          </div>
          <div className="flex gap-2">
            <Button type="submit" disabled={saving}>{saving ? <Loader2 className="size-4 animate-spin" /> : 'Save'}</Button>
            <Button type="button" variant="outline" asChild><Link to={isEdit && agentId ? `/agents/${agentId}` : '/agents'}>Cancel</Link></Button>
          </div>
        </form>
      </Card>
    </div>
  )
}
