import { useState, useEffect, useId } from 'react'
import { Settings, KeyRound, User, Sun, Moon, Users, Plus, Mail, Send } from 'lucide-react'
import { toast } from 'sonner'
import { useAuth } from '../../contexts/AuthContext'
import { useSpace } from '../../contexts/SpaceContext'
import { useTheme, type Theme } from '../../contexts/ThemeContext'
import { spacesApi } from '../../api/client'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { Badge } from '../../components/ui/badge'
import { cn, errMsg } from '../../lib/utils'
import type { SpaceMember, SpaceType } from '../../types/api'

const THEME_OPTIONS: { value: Theme; label: string; icon: typeof Sun; description: string }[] = [
  { value: 'dark',  label: 'Dark',  icon: Moon, description: 'Deep navy — default' },
  { value: 'light', label: 'Light', icon: Sun,  description: 'Light purple skin'    },
]

const SPACE_TYPES: { value: Exclude<SpaceType, 'personal'>; label: string; description: string }[] = [
  { value: 'team',   label: 'Team',   description: 'Collaborative workspace for a team' },
  { value: 'family', label: 'Family', description: 'Shared space for household members' },
]

export default function SettingsPage() {
  const { apiKey, saveApiKey, clearApiKey, currentUser } = useAuth()
  const { spaceId, userId, spaces, setSpace, reloadSpaces } = useSpace()
  const { theme, setTheme } = useTheme()

  // Legacy dev-mode context
  const [draftApiKey, setDraftApiKey] = useState(apiKey)
  const [draftSpace, setDraftSpace]   = useState(spaceId)
  const [draftUser, setDraftUser]     = useState(userId)

  // Create space
  const [newSpaceName, setNewSpaceName] = useState('')
  const [newSpaceType, setNewSpaceType] = useState<Exclude<SpaceType, 'personal'>>('team')
  const [creating, setCreating]         = useState(false)

  // Invite member
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole]   = useState('member')
  const [inviting, setInviting]       = useState(false)

  // Members list
  const [members, setMembers]         = useState<SpaceMember[]>([])
  const [loadingMembers, setLoadingMembers] = useState(false)

  const headingId = useId()

  useEffect(() => {
    if (!currentUser) return
    setLoadingMembers(true)
    spacesApi.members(spaceId)
      .then(setMembers)
      .catch(() => setMembers([]))
      .finally(() => setLoadingMembers(false))
  }, [spaceId, currentUser])

  function handleSaveApiKey(e: React.FormEvent) {
    e.preventDefault()
    saveApiKey(draftApiKey)
    toast.success('API key saved')
  }

  function handleSaveSpace(e: React.FormEvent) {
    e.preventDefault()
    setSpace(draftSpace.trim() || 'personal', draftUser.trim() || 'default_user')
    toast.success('Space context updated')
  }

  async function handleCreateSpace(e: React.FormEvent) {
    e.preventDefault()
    if (!newSpaceName.trim()) return
    setCreating(true)
    try {
      const space = await spacesApi.create({ name: newSpaceName.trim(), type: newSpaceType })
      toast.success(`Space "${space.name}" created`)
      setNewSpaceName('')
      await reloadSpaces()
      setSpace(space.id)
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setCreating(false)
    }
  }

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault()
    if (!inviteEmail.trim()) return
    setInviting(true)
    try {
      const inv = await spacesApi.invite(spaceId, { email: inviteEmail.trim(), role: inviteRole })
      toast.success(`Invitation sent to ${inv.invited_email}`)
      const link = `${window.location.origin}/invitations/${inv.token}`
      await navigator.clipboard.writeText(link).catch(() => null)
      toast.info('Invite link copied to clipboard')
      setInviteEmail('')
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setInviting(false)
    }
  }

  return (
    <div className="p-6 space-y-6 max-w-2xl" id={headingId}>
      {/* Page header */}
      <div className="flex items-center gap-4 pb-4 border-b border-border">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{
            background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
            border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
          }}
        >
          <Settings className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
          <p className="text-sm text-muted-foreground">Configure spaces, users, API keys, and preferences.</p>
        </div>
      </div>

      {/* Appearance */}
      <Card>
        <CardTitle className="flex items-center gap-2">
          <Sun className="size-3.5" /> Appearance
        </CardTitle>
        <div className="grid grid-cols-2 gap-2">
          {THEME_OPTIONS.map(({ value, label, icon: Icon, description }) => (
            <button
              key={value}
              onClick={() => setTheme(value)}
              className={cn(
                'flex items-center gap-3 p-3 rounded-lg border text-left transition-colors',
                theme === value
                  ? 'border-primary/50 bg-primary/8 text-foreground'
                  : 'border-border hover:bg-accent text-muted-foreground hover:text-foreground',
              )}
            >
              <Icon className="size-4 shrink-0" />
              <div>
                <div className="text-[13px] font-medium leading-none">{label}</div>
                <div className="text-[11px] mt-1 text-muted-foreground">{description}</div>
              </div>
              {theme === value && (
                <span className="ml-auto w-2 h-2 rounded-full shrink-0" style={{ background: 'var(--primary)' }} />
              )}
            </button>
          ))}
        </div>
      </Card>

      {/* API Key */}
      <Card>
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="size-3.5" /> API Key
        </CardTitle>
        <form onSubmit={handleSaveApiKey} className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="api-key">Anthropic API key</Label>
            <Input
              id="api-key"
              type="password"
              value={draftApiKey}
              onChange={e => setDraftApiKey(e.target.value)}
              placeholder="ask_…"
              className="font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">
              Used for agent runs and LLM features. Stored in localStorage only.
            </p>
          </div>
          <div className="flex gap-2">
            <Button type="submit" size="sm">Save key</Button>
            {apiKey && (
              <Button type="button" size="sm" variant="outline"
                onClick={() => { clearApiKey(); setDraftApiKey(''); toast.success('API key cleared') }}>
                Clear
              </Button>
            )}
          </div>
        </form>
      </Card>

      {/* ── Space management (authenticated users only) ── */}
      {currentUser ? (
        <>
          {/* Create space — anchor target */}
          <Card id="spaces">
            <CardTitle className="flex items-center gap-2">
              <Plus className="size-3.5" /> Create space
            </CardTitle>
            <form onSubmit={handleCreateSpace} className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="space-name">Space name</Label>
                <Input
                  id="space-name"
                  value={newSpaceName}
                  onChange={e => setNewSpaceName(e.target.value)}
                  placeholder="My Team"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                {SPACE_TYPES.map(t => (
                  <button
                    key={t.value}
                    type="button"
                    onClick={() => setNewSpaceType(t.value)}
                    className={cn(
                      'flex flex-col gap-1 p-3 rounded-lg border text-left transition-colors',
                      newSpaceType === t.value
                        ? 'border-primary/50 bg-primary/8 text-foreground'
                        : 'border-border hover:bg-accent text-muted-foreground hover:text-foreground',
                    )}
                  >
                    <span className="text-[13px] font-medium">{t.label}</span>
                    <span className="text-[11px]">{t.description}</span>
                  </button>
                ))}
              </div>
              <Button type="submit" size="sm" disabled={!newSpaceName.trim() || creating}>
                {creating ? 'Creating…' : 'Create space'}
              </Button>
            </form>
          </Card>

          {/* Members of current space */}
          <Card>
            <CardTitle className="flex items-center gap-2">
              <Users className="size-3.5" /> Members · {spaces.find(s => s.id === spaceId)?.name ?? spaceId}
            </CardTitle>

            {loadingMembers ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : members.length === 0 ? (
              <p className="text-sm text-muted-foreground">No members found.</p>
            ) : (
              <div className="divide-y divide-border">
                {members.map(m => (
                  <div key={m.user_id} className="flex items-center gap-3 py-2.5">
                    <div
                      className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-[11px] font-semibold text-accent-foreground"
                      style={{ background: 'color-mix(in oklch, var(--primary) 12%, transparent)' }}
                    >
                      {m.avatar_url
                        ? <img src={m.avatar_url} alt="" className="w-full h-full object-cover rounded-full" />
                        : m.display_name.slice(0, 2).toUpperCase()
                      }
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-medium text-foreground truncate">{m.display_name}</div>
                      <div className="text-[11px] text-muted-foreground truncate">{m.email}</div>
                    </div>
                    <Badge variant="muted" className="text-[10px] px-1.5 py-0 shrink-0">{m.role}</Badge>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Invite member */}
          <Card>
            <CardTitle className="flex items-center gap-2">
              <Mail className="size-3.5" /> Invite member
            </CardTitle>
            <form onSubmit={handleInvite} className="space-y-3">
              <div className="space-y-2">
                <Input
                  type="email"
                  value={inviteEmail}
                  onChange={e => setInviteEmail(e.target.value)}
                  placeholder="colleague@example.com"
                />
                <div className="flex gap-1.5">
                  {(['admin', 'member', 'viewer'] as const).map(role => (
                    <button
                      key={role}
                      type="button"
                      onClick={() => setInviteRole(role)}
                      className={cn(
                        'flex-1 h-8 rounded-md border text-[12px] font-medium capitalize transition-colors',
                        inviteRole === role
                          ? 'border-primary/50 bg-primary/8 text-foreground'
                          : 'border-border text-muted-foreground hover:text-foreground hover:bg-accent',
                      )}
                    >
                      {role}
                    </button>
                  ))}
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                An invitation link will be generated and copied to your clipboard.
              </p>
              <Button type="submit" size="sm" disabled={!inviteEmail.trim() || inviting}>
                <Send className="size-3.5 mr-1.5" />
                {inviting ? 'Sending…' : 'Generate invite link'}
              </Button>
            </form>
          </Card>
        </>
      ) : (
        /* Dev-mode space context override */
        <Card>
          <CardTitle className="flex items-center gap-2">
            <User className="size-3.5" /> Space context <Badge variant="muted" className="text-[9px]">dev</Badge>
          </CardTitle>
          <form onSubmit={handleSaveSpace} className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="space-id">Space ID</Label>
                <Input id="space-id" value={draftSpace} onChange={e => setDraftSpace(e.target.value)}
                  placeholder="personal" className="font-mono text-sm" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="user-id">User ID</Label>
                <Input id="user-id" value={draftUser} onChange={e => setDraftUser(e.target.value)}
                  placeholder="default_user" className="font-mono text-sm" />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Dev mode only. Sign in with Google to manage real spaces.
            </p>
            <Button type="submit" size="sm">Update context</Button>
          </form>
        </Card>
      )}
    </div>
  )
}
