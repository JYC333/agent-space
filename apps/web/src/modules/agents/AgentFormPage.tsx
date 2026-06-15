import { useEffect, useState } from 'react'
import { useSpaceNavigate as useNavigate, SpaceLink as Link } from '../../core/spaceNav'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { agentsApi, credentialsApi } from '../../api/client'
import type { CredentialStatus } from '../../types/api'
import { useSpace } from '../../contexts/SpaceContext'
import ProviderSelector from '../providers/ProviderSelector'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Textarea } from '../../components/ui/textarea'
import { Card } from '../../components/ui/card'
import { errMsg } from '../../lib/utils'

/**
 * Manual agent creation. Creating from a template lives at
 * /agents/templates/:id/use; editing an existing agent happens in the
 * Agent Detail tabs (which create new immutable versions).
 */
export default function AgentFormPage() {
  const navigate = useNavigate()
  const { activeSpaceId } = useSpace()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [modelSelection, setModelSelection] = useState<{ provider_id: string; model: string } | null>(null)
  const [runtime, setRuntime] = useState<string>('model_api')
  const [cliRuntimes, setCliRuntimes] = useState<CredentialStatus[]>([])
  const [saving, setSaving] = useState(false)

  // CLI runtimes are offered only when a login profile exists for them; the
  // catalog of installed-and-logged-in CLIs comes from the credential status
  // endpoint rather than a hardcoded list.
  useEffect(() => {
    credentialsApi.status()
      .then(list => setCliRuntimes(list.filter(c => c.logged_in)))
      .catch(() => setCliRuntimes([]))
  }, [])

  const isCli = runtime !== 'model_api'
  const providerRequired = !isCli

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!activeSpaceId) { toast.error('Select an operational space'); return }
    if (providerRequired && !modelSelection?.provider_id) {
      toast.error('Select a model provider for the API runtime')
      return
    }
    setSaving(true)
    try {
      const created = await agentsApi.create({
        name: name.trim(),
        description: description.trim() || null,
        system_prompt: systemPrompt.trim() || null,
        adapter_type: runtime,
        // CLI runtimes manage their own model; never carry a provider/model.
        default_model_provider_id: isCli ? null : (modelSelection?.provider_id ?? null),
        default_model: isCli ? null : (modelSelection?.model || null),
      })
      toast.success('Agent created')
      navigate(`/agents/${created.id}`)
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="p-6 max-w-xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">New agent</h1>
        <p className="text-sm text-muted-foreground">
          Configure identity, runtime, and default model. Or{' '}
          <Link to="/agents/templates" className="underline">start from a template</Link>.
        </p>
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
          <div className="space-y-3 border-t border-border pt-4">
            <h2 className="text-sm font-medium">Behavior, runtime &amp; model</h2>
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">System prompt</label>
              <Textarea
                value={systemPrompt}
                onChange={e => setSystemPrompt(e.target.value)}
                rows={4}
                placeholder="You are a daily news summarizer. Be concise and factual…"
              />
              <p className="text-xs text-muted-foreground">The agent's persistent role/identity. The per-run prompt is the task input.</p>
            </div>
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Runtime</label>
              <select
                value={runtime}
                onChange={e => setRuntime(e.target.value)}
                className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
              >
                <option value="model_api">API — call a model provider (no tools)</option>
                {cliRuntimes.map(c => (
                  <option key={c.runtime} value={c.runtime}>{c.label} (tools, filesystem)</option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">
                {isCli
                  ? 'Uses the CLI with its own login; the model is managed by the CLI runtime.'
                  : 'Runs a prompt against a configured model provider. Pick the provider below.'}
              </p>
            </div>
            {!isCli && (
              <ProviderSelector value={modelSelection} onChange={setModelSelection} required={providerRequired} />
            )}
          </div>
          <div className="flex gap-2">
            <Button type="submit" disabled={saving}>{saving ? <Loader2 className="size-4 animate-spin" /> : 'Create agent'}</Button>
            <Button type="button" variant="outline" asChild><Link to="/agents">Cancel</Link></Button>
          </div>
        </form>
      </Card>
    </div>
  )
}
