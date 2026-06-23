import { useEffect, useId, useState } from 'react'
import { Settings, Users, Mail, Send, Globe2, ShieldAlert, Puzzle, History, Search } from 'lucide-react'
import { toast } from 'sonner'
import { SpaceLink as Link } from '../../core/spaceNav'
import { useAuth } from '../../contexts/AuthContext'
import { useSpace } from '../../contexts/SpaceContext'
import { spacesApi } from '../../api/client'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Badge } from '../../components/ui/badge'
import { UserAvatar } from '../../components/UserAvatar'
import { cn, errMsg } from '../../lib/utils'
import { SpaceRuntimePolicyPanel } from '../runtime_tools/SpaceRuntimePolicyPanel'
import { ObjectSchemaPanel } from './ObjectSchemaPanel'
import type { MemberRole, SpaceMember } from '../../types/api'

const INVITE_ROLES: MemberRole[] = ['admin', 'member', 'viewer']

function canManageSpace(role: MemberRole | undefined): boolean {
  return role === 'owner' || role === 'admin'
}

export default function SpaceSettingsPage() {
  const headingId = useId()
  const { currentUser } = useAuth()
  const { activeSpaceId, activeSpaceName, spaces } = useSpace()
  const activeSpace = spaces.find(s => s.id === activeSpaceId)
  const manageable = canManageSpace(activeSpace?.role)
  const waitingForSpace = Boolean(activeSpaceId && !activeSpace && spaces.length === 0)

  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<MemberRole>('member')
  const [inviting, setInviting] = useState(false)
  const [members, setMembers] = useState<SpaceMember[]>([])
  const [loadingMembers, setLoadingMembers] = useState(false)

  useEffect(() => {
    if (!currentUser || !activeSpaceId || !manageable) {
      setMembers([])
      return
    }
    setLoadingMembers(true)
    spacesApi.members(activeSpaceId)
      .then(setMembers)
      .catch(() => setMembers([]))
      .finally(() => setLoadingMembers(false))
  }, [activeSpaceId, currentUser, manageable])

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault()
    if (!inviteEmail.trim() || !activeSpaceId) return
    setInviting(true)
    try {
      const inv = await spacesApi.invite(activeSpaceId, { email: inviteEmail.trim(), role: inviteRole })
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

  const title = activeSpaceName ?? activeSpace?.name ?? 'Space'

  return (
    <div className="p-6 space-y-6 max-w-4xl" id={headingId}>
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
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight">Space Settings</h1>
          <p className="text-sm text-muted-foreground truncate">
            Manage space-level configuration for {title}.
          </p>
        </div>
      </div>

      {waitingForSpace ? (
        <Card>
          <CardTitle>Loading space</CardTitle>
          <p className="text-sm text-muted-foreground">Loading space permissions…</p>
        </Card>
      ) : !activeSpaceId ? (
        <Card>
          <CardTitle>Select a space</CardTitle>
          <p className="text-sm text-muted-foreground">
            Space settings are available from a concrete space route.
          </p>
        </Card>
      ) : !manageable ? (
        <Card>
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="size-3.5" /> Space admin required
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Only this space's owner or admins can view and change space settings.
          </p>
        </Card>
      ) : (
        <>
          <SpaceRuntimePolicyPanel />

          <ObjectSchemaPanel />

          <Card>
            <CardTitle className="flex items-center gap-2">
              <Puzzle className="size-3.5" /> Optional Modules
            </CardTitle>
            <p className="text-sm text-muted-foreground mb-3">
              Enable or disable official optional modules for this space.
            </p>
            <Button asChild variant="outline" size="sm">
              <Link to="/plugins">Manage Modules</Link>
            </Button>
          </Card>

          <Card>
            <CardTitle className="flex items-center gap-2">
              <Globe2 className="size-3.5" /> Network Profiles
            </CardTitle>
            <p className="text-sm text-muted-foreground mb-3">
              Configure direct and proxy routing profiles used by this space.
            </p>
            <Button asChild variant="outline" size="sm">
              <Link to="/network-profiles">Open Network Profiles</Link>
            </Button>
          </Card>

          <Card>
            <CardTitle className="flex items-center gap-2">
              <History className="size-3.5" /> Snapshot Rollback
            </CardTitle>
            <p className="text-sm text-muted-foreground mb-3">
              Configure per-workspace retention for code-patch rollback snapshots (days and max count).
            </p>
            <Button asChild variant="outline" size="sm">
              <Link to="/workspace-snapshot-settings">Manage Snapshot Settings</Link>
            </Button>
          </Card>

          <Card>
            <CardTitle className="flex items-center gap-2">
              <Search className="size-3.5" /> Retrieval Search
            </CardTitle>
            <p className="text-sm text-muted-foreground mb-3">
              View and configure search mode, rewrite prompt, rerank, cache, trace, and result defaults for this space.
            </p>
            <Button asChild variant="outline" size="sm">
              <Link to="/retrieval-settings">Open Retrieval Settings</Link>
            </Button>
          </Card>

          <Card>
            <CardTitle className="flex items-center gap-2">
              <Users className="size-3.5" /> Members · {title}
            </CardTitle>

            {loadingMembers ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : members.length === 0 ? (
              <p className="text-sm text-muted-foreground">No members found.</p>
            ) : (
              <div className="divide-y divide-border">
                {members.map(m => (
                  <div key={m.user_id} className="flex items-center gap-3 py-2.5">
                    <div className="size-7 shrink-0 overflow-hidden rounded-full border border-border">
                      <UserAvatar
                        avatarUrl={m.avatar_url}
                        displayName={m.display_name}
                        email={m.email}
                      />
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
                  {INVITE_ROLES.map(role => (
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
      )}
    </div>
  )
}
