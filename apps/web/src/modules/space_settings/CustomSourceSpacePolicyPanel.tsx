import { useEffect, useState } from 'react'
import { Loader2, RefreshCw, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { intakeApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardTitle } from '../../components/ui/card'
import { Label } from '../../components/ui/label'
import { Textarea } from '../../components/ui/textarea'
import { cn, errMsg } from '../../lib/utils'
import type {
  CustomSourceCapturePolicy,
  CustomSourceCreatorRole,
  CustomSourceRetentionPolicy,
  CustomSourceSpacePolicy,
} from '../../types/api'

const CREATOR_ROLE_OPTIONS: Array<{ value: CustomSourceCreatorRole; label: string; fixed?: boolean }> = [
  { value: 'owner', label: 'Owner', fixed: true },
  { value: 'admin', label: 'Admin', fixed: true },
  { value: 'reviewer', label: 'Reviewer' },
  { value: 'member', label: 'Member' },
]

const CAPTURE_OPTIONS: Array<{ value: CustomSourceCapturePolicy; label: string }> = [
  { value: 'reference_only', label: 'Save reference' },
  { value: 'extract_text', label: 'Extract text' },
  { value: 'archive_original', label: 'Archive original' },
]

const RETENTION_OPTIONS: Array<{ value: CustomSourceRetentionPolicy; label: string }> = [
  { value: 'metadata_only', label: 'Metadata only' },
  { value: 'summary_only', label: 'Summary only' },
  { value: 'full_text', label: 'Full text' },
  { value: 'full_snapshot', label: 'Full snapshot' },
  { value: 'archived', label: 'Archived' },
]

interface PolicyForm {
  creatorRoles: CustomSourceCreatorRole[]
  defaultCapturePolicy: CustomSourceCapturePolicy
  defaultRetentionPolicy: CustomSourceRetentionPolicy
  allowedDomainsText: string
  downloadMiB: string
  credentialedSourcesAllowed: boolean
  sameEnvelopeRepairAutoApply: boolean
}

function formatMiB(bytes: number): string {
  const value = bytes / (1024 * 1024)
  if (Number.isInteger(value)) return String(value)
  return value.toFixed(value < 0.01 ? 6 : value < 1 ? 3 : 2).replace(/0+$/, '').replace(/\.$/, '')
}

function formFromPolicy(policy: CustomSourceSpacePolicy): PolicyForm {
  return {
    creatorRoles: policy.creator_roles,
    defaultCapturePolicy: policy.default_capture_policy,
    defaultRetentionPolicy: policy.default_retention_policy,
    allowedDomainsText: policy.allowed_domains.join('\n'),
    downloadMiB: formatMiB(policy.download_bytes_max),
    credentialedSourcesAllowed: policy.credentialed_sources_allowed,
    sameEnvelopeRepairAutoApply: policy.same_envelope_repair_auto_apply,
  }
}

function parseDomains(text: string): string[] {
  return text
    .split(/[\n,]+/)
    .map(item => item.trim())
    .filter(Boolean)
}

function parseDownloadBytes(value: string): number {
  const mib = Number(value)
  if (!Number.isFinite(mib) || mib <= 0) throw new Error('Download max must be a positive MiB value')
  const bytes = Math.round(mib * 1024 * 1024)
  if (bytes < 1024 || bytes > 104_857_600) throw new Error('Download max must be between 1 KiB and 100 MiB')
  return bytes
}

export function CustomSourceSpacePolicyPanel() {
  const { activeSpaceId, spaces } = useSpace()
  const activeSpace = spaces.find(space => space.id === activeSpaceId) ?? null
  const canManage = activeSpace?.role === 'owner' || activeSpace?.role === 'admin'
  const [policy, setPolicy] = useState<CustomSourceSpacePolicy | null>(null)
  const [form, setForm] = useState<PolicyForm | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  async function load(options: { clear?: boolean } = {}) {
    if (!activeSpaceId) return
    if (options.clear) {
      setPolicy(null)
      setForm(null)
    }
    setLoading(true)
    try {
      const next = await intakeApi.customSourceSpacePolicy()
      setPolicy(next)
      setForm(formFromPolicy(next))
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    async function loadForSpace() {
      setPolicy(null)
      setForm(null)
      if (!activeSpaceId) {
        setLoading(false)
        return
      }
      setLoading(true)
      try {
        const next = await intakeApi.customSourceSpacePolicy()
        if (cancelled) return
        setPolicy(next)
        setForm(formFromPolicy(next))
      } catch (err) {
        if (!cancelled) toast.error(errMsg(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void loadForSpace()
    return () => { cancelled = true }
  }, [activeSpaceId])

  function toggleCreatorRole(role: CustomSourceCreatorRole) {
    if (!form || role === 'owner' || role === 'admin') return
    setForm(prev => {
      if (!prev) return prev
      const roles = prev.creatorRoles.includes(role)
        ? prev.creatorRoles.filter(item => item !== role)
        : [...prev.creatorRoles, role]
      return { ...prev, creatorRoles: roles }
    })
  }

  async function save() {
    if (!form) return
    setSaving(true)
    try {
      const downloadBytesMax = parseDownloadBytes(form.downloadMiB)
      const next = await intakeApi.updateCustomSourceSpacePolicy({
        creator_roles: form.creatorRoles,
        default_capture_policy: form.defaultCapturePolicy,
        default_retention_policy: form.defaultRetentionPolicy,
        allowed_domains: parseDomains(form.allowedDomainsText),
        download_bytes_max: downloadBytesMax,
        credentialed_sources_allowed: form.credentialedSourcesAllowed,
        same_envelope_repair_auto_apply: form.sameEnvelopeRepairAutoApply,
      })
      setPolicy(next)
      setForm(formFromPolicy(next))
      toast.success('Custom Source policy updated')
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setSaving(false)
    }
  }

  const disabled = !canManage || loading || saving || !form

  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="size-3.5" /> Custom Source Policy
          </CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            Configure creation roles, defaults, allowed domains, credential policy, and repair activation for this space.
          </p>
        </div>
        <Badge variant="muted" className="shrink-0">
          {policy?.updated_at ? 'configured' : 'defaults'}
        </Badge>
      </div>

      <div className="mt-4 flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          {policy?.updated_at ? `Updated ${new Date(policy.updated_at).toLocaleString()}` : 'System defaults'}
        </p>
        <Button size="sm" variant="ghost" onClick={() => load()} disabled={loading || saving || !activeSpaceId}>
          {loading ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
          Refresh
        </Button>
      </div>

      {!canManage && (
        <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          Updating Custom Source policy requires space owner or admin role.
        </p>
      )}

      {loading && !form ? (
        <p className="mt-4 text-sm text-muted-foreground">Loading Custom Source policy…</p>
      ) : form ? (
        <div className="mt-4 space-y-4">
          <div>
            <Label>Creator roles</Label>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {CREATOR_ROLE_OPTIONS.map(option => {
                const selected = form.creatorRoles.includes(option.value)
                return (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={selected}
                    aria-label={option.fixed ? `${option.label} role is always allowed` : `${option.label} role`}
                    disabled={disabled || option.fixed}
                    onClick={() => toggleCreatorRole(option.value)}
                    className={cn(
                      'h-9 rounded-md border text-xs font-medium transition-colors',
                      selected
                        ? 'border-primary/50 bg-primary/8 text-foreground'
                        : 'border-border text-muted-foreground hover:bg-accent hover:text-foreground',
                      (disabled || option.fixed) && 'cursor-not-allowed opacity-80',
                    )}
                  >
                    {option.label}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor="custom-source-capture">Default capture</Label>
              <select
                id="custom-source-capture"
                value={form.defaultCapturePolicy}
                disabled={disabled}
                onChange={event => setForm(prev => prev ? {
                  ...prev,
                  defaultCapturePolicy: event.target.value as CustomSourceCapturePolicy,
                } : prev)}
                className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
              >
                {CAPTURE_OPTIONS.map(option => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </div>
            <div>
              <Label htmlFor="custom-source-retention">Default retention</Label>
              <select
                id="custom-source-retention"
                value={form.defaultRetentionPolicy}
                disabled={disabled}
                onChange={event => setForm(prev => prev ? {
                  ...prev,
                  defaultRetentionPolicy: event.target.value as CustomSourceRetentionPolicy,
                } : prev)}
                className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
              >
                {RETENTION_OPTIONS.map(option => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </div>
            <div>
              <Label htmlFor="custom-source-download-max">Download max (MiB)</Label>
              <input
                id="custom-source-download-max"
                type="number"
                min="0.000977"
                max="100"
                step="any"
                value={form.downloadMiB}
                disabled={disabled}
                onChange={event => setForm(prev => prev ? {
                  ...prev,
                  downloadMiB: event.target.value,
                } : prev)}
                className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
              />
            </div>
          </div>

          <div>
            <Label htmlFor="custom-source-domains">Allowed domains</Label>
            <Textarea
              id="custom-source-domains"
              value={form.allowedDomainsText}
              disabled={disabled}
              placeholder="example.com"
              onChange={event => setForm(prev => prev ? { ...prev, allowedDomainsText: event.target.value } : prev)}
              className="font-mono text-xs"
            />
            <p className="mt-1 text-xs text-muted-foreground">Blank allows any HTTP(S) domain.</p>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex items-start gap-2 rounded-md border border-border p-3 text-sm">
              <input
                type="checkbox"
                checked={form.credentialedSourcesAllowed}
                disabled={disabled}
                onChange={event => setForm(prev => prev ? {
                  ...prev,
                  credentialedSourcesAllowed: event.target.checked,
                } : prev)}
                className="mt-1"
              />
              <span>
                <span className="block font-medium">Credentialed sources</span>
                <span className="block text-xs text-muted-foreground">Allow sources that request stored credentials.</span>
              </span>
            </label>
            <label className="flex items-start gap-2 rounded-md border border-border p-3 text-sm">
              <input
                type="checkbox"
                checked={form.sameEnvelopeRepairAutoApply}
                disabled={disabled}
                onChange={event => setForm(prev => prev ? {
                  ...prev,
                  sameEnvelopeRepairAutoApply: event.target.checked,
                } : prev)}
                className="mt-1"
              />
              <span>
                <span className="block font-medium">Same-envelope repair</span>
                <span className="block text-xs text-muted-foreground">Auto-apply repair handlers that stay inside the approved envelope.</span>
              </span>
            </label>
          </div>

          <div className="flex justify-end">
            <Button size="sm" onClick={save} disabled={disabled}>
              {saving ? <Loader2 className="size-3.5 animate-spin" /> : null}
              Save policy
            </Button>
          </div>
        </div>
      ) : (
        <p className="mt-4 text-sm text-muted-foreground">Custom Source policy is unavailable.</p>
      )}
    </Card>
  )
}
