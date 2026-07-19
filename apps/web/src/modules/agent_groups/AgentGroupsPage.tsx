import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ArrowLeft,
  Ban,
  Bot,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  FileText,
  GitBranch,
  Loader2,
  MessageSquare,
  MessagesSquare,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Save,
  Send,
  Settings,
} from 'lucide-react'
import { toast } from 'sonner'
import { agentGroupsApi, agentsApi, runsApi } from '../../api/client'
import { SpaceLink as Link } from '../../core/spaceNav'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type {
  AgentOut,
  AgentRunGroup,
  AgentRunGroupTimeline,
  AgentRunGroupTrace,
  AgentRunMessage,
  Run,
  RunDelegation,
} from '../../types/api'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardTitle } from '../../components/ui/card'
import { ConfirmDialog } from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Skeleton } from '../../components/ui/skeleton'
import { Textarea } from '../../components/ui/textarea'
import {
  RoomMessageComposer,
  emptyRoomMessageComposerValue,
  type RoomMessageRoutingSegment,
  type RoomMessageComposerValue,
} from './RoomMessageComposer'
import { MarkdownMessage } from './MarkdownMessage'

type RoomView = 'chat' | 'settings'
type ConversationId = string | 'new' | null
type RoomRoutingMode = 'direct' | 'agent_coordination'

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString() : '-'
}

function short(id: string | null | undefined) {
  return id ? `${id.slice(0, 10)}...` : '-'
}

function agentName(agents: AgentOut[], id: string | null | undefined) {
  if (!id) return '-'
  return agents.find(agent => agent.id === id)?.name ?? short(id)
}

function mentionLabel(agents: AgentOut[], id: string) {
  return `@${agentName(agents, id)}`
}

function activeRunStatus(status: string | null | undefined) {
  return status === 'queued' || status === 'running' || status === 'waiting_for_dependency'
}

function activeDelegationStatus(status: string | null | undefined) {
  return status === 'requested' || status === 'queued' || status === 'running'
}

function terminalDelegationCount(delegations: RunDelegation[]) {
  return delegations.filter(item => ['succeeded', 'failed', 'cancelled', 'policy_denied'].includes(item.status)).length
}

function runErrorText(run: Run | null | undefined) {
  if (!run) return null
  if (run.error_message) return run.error_message
  const errorJson = run.error_json
  if (!errorJson) return null
  const code = errorJson.error_code ?? errorJson.code
  const text = errorJson.error_text ?? errorJson.message ?? errorJson.error
  if (typeof text === 'string' && typeof code === 'string') return `${code}: ${text}`
  if (typeof text === 'string') return text
  if (typeof code === 'string') return code
  return null
}

function collectRunIds(timeline: AgentRunGroupTimeline, trace: AgentRunGroupTrace | null) {
  const ids = new Set<string>()
  if (timeline.group.root_run_id) ids.add(timeline.group.root_run_id)
  if (trace?.root_run_id) ids.add(trace.root_run_id)
  for (const id of trace?.child_run_ids ?? []) ids.add(id)
  for (const item of timeline.messages) {
    if (item.run_id) ids.add(item.run_id)
  }
  for (const item of timeline.delegations) {
    ids.add(item.parent_run_id)
    if (item.child_run_id) ids.add(item.child_run_id)
  }
  return [...ids]
}

interface WorkItem {
  key: string
  agent_id: string | null
  from_agent_id?: string | null
  label: string
  status: string
  run_id: string | null
  detail: string | null
}

interface Conversation {
  id: string
  message: AgentRunMessage
  title: string
  run_id: string | null
  created_at: string
  updated_at: string
  count: number
}

interface ChatEntry {
  key: string
  kind: 'message' | 'delegation_group'
  created_at: string
  message?: AgentRunMessage
  delegations?: RunDelegation[]
}

function collectActiveWorkItems(
  group: AgentRunGroup | null,
  rootRun: Run | null,
  messages: AgentRunMessage[],
  delegations: RunDelegation[],
  runsById: Record<string, Run>,
): WorkItem[] {
  const items: WorkItem[] = []
  if (rootRun && activeRunStatus(rootRun.status)) {
    items.push({
      key: `run:${rootRun.id}`,
      agent_id: rootRun.agent_id,
      label: 'Manager run',
      status: rootRun.status,
      run_id: rootRun.id,
      detail: rootRun.instruction ?? rootRun.prompt ?? group?.goal ?? null,
    })
  }
  const seenRunIds = new Set(rootRun ? [rootRun.id] : [])
  for (const message of messages) {
    if (!message.run_id || seenRunIds.has(message.run_id)) continue
    const run = runsById[message.run_id]
    if (!run || !activeRunStatus(run.status)) continue
    seenRunIds.add(run.id)
    items.push({
      key: `run:${run.id}`,
      agent_id: run.agent_id,
      label: run.agent_id === group?.manager_agent_id ? 'Manager turn' : 'Agent turn',
      status: run.status,
      run_id: run.id,
      detail: message.content,
    })
  }
  for (const delegation of delegations) {
    const childRun = delegation.child_run_id ? runsById[delegation.child_run_id] : null
    const status = childRun?.status ?? delegation.status
    if (!activeDelegationStatus(delegation.status) && !activeRunStatus(childRun?.status)) continue
    items.push({
      key: `delegation:${delegation.id}`,
      agent_id: delegation.target_agent_id,
      from_agent_id: delegation.requesting_agent_id,
      label: 'Agent call',
      status,
      run_id: delegation.child_run_id,
      detail: delegation.instruction,
    })
  }
  return items
}

function collectRoomTurnRuns(
  group: AgentRunGroup | null,
  messages: AgentRunMessage[],
  delegations: RunDelegation[],
  runsById: Record<string, Run>,
): Run[] {
  if (!group) return []
  const delegatedChildRunIds = new Set(delegations.map(item => item.child_run_id).filter(Boolean))
  const seen = new Set<string>()
  const runs: Run[] = []
  for (const message of messages) {
    if (!message.run_id || message.run_id === group.root_run_id || delegatedChildRunIds.has(message.run_id)) continue
    if (seen.has(message.run_id)) continue
    const run = runsById[message.run_id]
    if (!run) continue
    seen.add(run.id)
    runs.push(run)
  }
  return runs
}

function roomHasLiveWork(
  group: AgentRunGroup | null,
  rootRun: Run | null,
  activeWorkItems: WorkItem[],
  delegations: RunDelegation[],
) {
  if (!group || group.status !== 'active') return false
  if (group.root_run_id && !rootRun) return true
  return activeWorkItems.length > 0 || delegations.some(item => activeDelegationStatus(item.status))
}

function roomHasPendingProjectedReplies(
  conversation: Conversation | null,
  messages: AgentRunMessage[],
  runsById: Record<string, Run>,
) {
  if (!conversation) return false
  const threadMessages = threadMessagesForRoot(conversation.message, messages)
  const projectedRunIds = new Set(messages
    .filter(item => item.message_type === 'agent_message')
    .map(item => item.run_id)
    .filter(Boolean))

  for (const message of threadMessages) {
    if (message.message_type !== 'user_instruction') continue
    for (const runId of recipientRunIdsForMessage(message)) {
      if (projectedRunIds.has(runId)) continue
      const run = runsById[runId]
      if (!run) return true
      if (activeRunStatus(run.status)) return true
      if ((run.status === 'succeeded' || run.status === 'degraded') && runHasProjectableOutput(run)) return true
    }
  }
  return false
}

function recipientRunIdsForMessage(message: AgentRunMessage): string[] {
  const metadata = recordValue(message.metadata_json)
  const ids = metadata.recipient_run_ids
  if (Array.isArray(ids)) return uniqueIds(ids.filter((id): id is string => typeof id === 'string'))
  return typeof metadata.recipient_run_id === 'string' ? [metadata.recipient_run_id] : []
}

function runHasProjectableOutput(run: Run) {
  const output = recordValue(run.output_json)
  return Boolean(stringValue(output.output_text) || stringValue(output.summary) || stringValue(output.result_summary))
}

function firstLine(value: string) {
  const line = value.trim().split(/\n/)[0] ?? ''
  return line.length > 80 ? `${line.slice(0, 77)}...` : line || 'New conversation'
}

function directRoutingSegments(value: RoomMessageComposerValue): RoomMessageRoutingSegment[] {
  return value.routingSegments
    .map(segment => ({
      recipient_agent_ids: uniqueIds(segment.recipient_agent_ids),
      content: segment.content.trim(),
    }))
    .filter(segment => segment.recipient_agent_ids.length > 0 && segment.content.length > 0)
}

function uniqueIds(ids: string[]): string[] {
  return [...new Set(ids.map(id => id.trim()).filter(Boolean))]
}

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function routePreviewKind(
  value: RoomMessageComposerValue,
  routingMode: RoomRoutingMode,
) {
  const segments = directRoutingSegments(value)
  if (routingMode === 'agent_coordination') return 'Agent coordination'
  if (segments.length === 0 && value.mentionIds.length > 0) return 'Waiting for task'
  if (segments.length === 0) return 'Manager default'
  if (segments.length === 1 && segments[0]!.recipient_agent_ids.length > 1) return 'Parallel direct'
  if (segments.length > 1) return 'Segmented direct'
  return 'Direct'
}

function routePreviewRunCount(
  value: RoomMessageComposerValue,
  routingMode: RoomRoutingMode,
) {
  if (routingMode === 'agent_coordination') return 1
  const segments = directRoutingSegments(value)
  if (segments.length === 0 && value.mentionIds.length > 0) return 0
  if (segments.length === 0) return 1
  return segments.reduce((count, segment) => count + segment.recipient_agent_ids.length, 0)
}

function pendingDirectMentionIds(value: RoomMessageComposerValue): string[] {
  const routedIds = new Set(directRoutingSegments(value).flatMap(segment => segment.recipient_agent_ids))
  return uniqueIds(value.mentionIds).filter(id => !routedIds.has(id))
}

function hasPendingDirectMentions(value: RoomMessageComposerValue, routingMode: RoomRoutingMode) {
  return routingMode === 'direct' && pendingDirectMentionIds(value).length > 0
}

function previewText(value: string) {
  const trimmed = value.trim()
  return trimmed.length > 48 ? `${trimmed.slice(0, 45)}...` : trimmed
}

function compareDesc(a: string, b: string) {
  return new Date(b).getTime() - new Date(a).getTime()
}

function compareAsc(a: string, b: string) {
  return new Date(a).getTime() - new Date(b).getTime()
}

function conversationRoots(messages: AgentRunMessage[]): Conversation[] {
  const userMessages = messages.filter(item => item.message_type === 'user_instruction')
  const roots = userMessages.filter(item => !item.parent_message_id)
  return roots
    .map(root => {
      const thread = threadMessagesForRoot(root, messages)
      const threadUserMessages = thread.filter(item => item.message_type === 'user_instruction')
      const updatedAt = thread.reduce((latest, item) => compareDesc(item.created_at, latest) < 0 ? item.created_at : latest, root.created_at)
      return {
        id: root.id,
        message: root,
        title: firstLine(root.content),
        run_id: root.run_id,
        created_at: root.created_at,
        updated_at: updatedAt,
        count: threadUserMessages.length,
      }
    })
    .sort((a, b) => compareDesc(a.updated_at, b.updated_at))
}

function threadMessagesForRoot(root: AgentRunMessage, messages: AgentRunMessage[]): AgentRunMessage[] {
  const byParent = new Map<string, AgentRunMessage[]>()
  for (const message of messages) {
    if (!message.parent_message_id) continue
    const current = byParent.get(message.parent_message_id) ?? []
    current.push(message)
    byParent.set(message.parent_message_id, current)
  }
  const result: AgentRunMessage[] = []
  const seen = new Set<string>()
  const queue: AgentRunMessage[] = [root]
  while (queue.length > 0) {
    const message = queue.shift()
    if (!message || seen.has(message.id)) continue
    seen.add(message.id)
    result.push(message)
    queue.push(...(byParent.get(message.id) ?? []))
  }
  return result.sort((a, b) => compareAsc(a.created_at, b.created_at))
}

function buildChatEntries(
  conversation: Conversation | null,
  messages: AgentRunMessage[],
  delegations: RunDelegation[],
): ChatEntry[] {
  if (!conversation) return []
  const threadMessages = threadMessagesForRoot(conversation.message, messages)
  const threadMessageIds = new Set(threadMessages.map(item => item.id))
  const threadRunIds = new Set(threadMessages.map(item => item.run_id).filter(Boolean))
  const threadDelegations = delegations.filter(item =>
    (item.request_message_id && threadMessageIds.has(item.request_message_id)) ||
    threadRunIds.has(item.parent_run_id),
  )
  const mainThreadMessages = messages.filter(item =>
    threadMessageIds.has(item.id) &&
    (item.message_type === 'user_instruction' || item.message_type === 'agent_message' || item.message_type === 'review_note'),
  ).sort((a, b) => compareAsc(a.created_at, b.created_at))
  const delegationsByParentRunId = new Map<string, RunDelegation[]>()
  for (const delegation of threadDelegations) {
    const current = delegationsByParentRunId.get(delegation.parent_run_id) ?? []
    current.push(delegation)
    delegationsByParentRunId.set(delegation.parent_run_id, current)
  }
  const usedDelegationIds = new Set<string>()
  const entries: ChatEntry[] = []
  for (const message of mainThreadMessages) {
    entries.push({
      key: `message:${message.id}`,
      kind: 'message' as const,
      created_at: message.created_at,
      message,
    })
    if (!message.run_id) continue
    const grouped = delegationsByParentRunId.get(message.run_id)?.filter(item => !usedDelegationIds.has(item.id)) ?? []
    if (grouped.length === 0) continue
    grouped.forEach(item => usedDelegationIds.add(item.id))
    entries.push({
      key: `delegation-group:${message.id}`,
      kind: 'delegation_group',
      created_at: grouped.reduce((earliest, item) => compareAsc(item.created_at, earliest) < 0 ? item.created_at : earliest, grouped[0]!.created_at),
      delegations: grouped,
    })
  }
  const unassignedDelegations = threadDelegations.filter(item => !usedDelegationIds.has(item.id))
  if (unassignedDelegations.length > 0) {
    entries.push({
      key: `delegation-group:${conversation.id}:unassigned`,
      kind: 'delegation_group',
      created_at: unassignedDelegations.reduce((earliest, item) => compareAsc(item.created_at, earliest) < 0 ? item.created_at : earliest, unassignedDelegations[0]!.created_at),
      delegations: unassignedDelegations,
    })
  }
  return entries.sort((a, b) => compareAsc(a.created_at, b.created_at))
}

export default function AgentGroupsPage() {
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedGroupId = searchParams.get('room')
  const roomView: RoomView = searchParams.get('view') === 'settings' ? 'settings' : 'chat'

  const [agents, setAgents] = useState<AgentOut[]>([])
  const [groups, setGroups] = useState<AgentRunGroup[]>([])
  const [timeline, setTimeline] = useState<AgentRunGroupTimeline | null>(null)
  const [trace, setTrace] = useState<AgentRunGroupTrace | null>(null)
  const [runsById, setRunsById] = useState<Record<string, Run>>({})
  const [statusFilter, setStatusFilter] = useState('')
  const [loadingGroups, setLoadingGroups] = useState(true)
  const [loadingRoom, setLoadingRoom] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [selectedConversationId, setSelectedConversationId] = useState<ConversationId>(null)
  const backgroundRefreshInFlight = useRef(false)

  const [title, setTitle] = useState('')
  const [goal, setGoal] = useState('')
  const [managerAgentId, setManagerAgentId] = useState('')
  const [memberAgentIds, setMemberAgentIds] = useState<string[]>([])
  const [message, setMessage] = useState<RoomMessageComposerValue>(() => emptyRoomMessageComposerValue())
  const [messageResetToken, setMessageResetToken] = useState(0)
  const [routingMode, setRoutingMode] = useState<RoomRoutingMode>('direct')

  const loadAgents = useCallback(async () => {
    if (!activeSpaceId) {
      setAgents([])
      return
    }
    try {
      const list = await agentsApi.list({ status: 'active,disabled,inactive' })
      setAgents(list.filter(agent => agent.agent_kind !== 'system_assistant'))
    } catch (err) {
      toast.error(errMsg(err))
      setAgents([])
    }
  }, [activeSpaceId])

  const loadGroups = useCallback(async () => {
    if (!activeSpaceId) {
      setGroups([])
      setTimeline(null)
      setTrace(null)
      setLoadingGroups(false)
      return
    }
    setLoadingGroups(true)
    try {
      const page = await agentGroupsApi.list({
        status: statusFilter || undefined,
        limit: 50,
      })
      setGroups(page.items)
    } catch (err) {
      toast.error(errMsg(err))
      setGroups([])
    } finally {
      setLoadingGroups(false)
    }
  }, [activeSpaceId, statusFilter])

  const loadRoom = useCallback(async (groupId: string | null = selectedGroupId, options: { background?: boolean } = {}) => {
    if (!activeSpaceId || !groupId) {
      setTimeline(null)
      setTrace(null)
      setRunsById({})
      return
    }
    if (!options.background) setLoadingRoom(true)
    try {
      const [nextTimeline, nextTrace] = await Promise.all([
        agentGroupsApi.timeline(groupId, { limit: 200 }),
        agentGroupsApi.trace(groupId),
      ])
      const runIds = collectRunIds(nextTimeline, nextTrace)
      const runRows = await Promise.all(runIds.map(async runId => {
        try {
          return await runsApi.get(runId)
        } catch {
          return null
        }
      }))
      setTimeline(nextTimeline)
      setTrace(nextTrace)
      setGroups(current => {
        const exists = current.some(item => item.id === nextTimeline.group.id)
        return exists
          ? current.map(item => item.id === nextTimeline.group.id ? nextTimeline.group : item)
          : [nextTimeline.group, ...current]
      })
      setRunsById(Object.fromEntries(runRows.filter((run): run is Run => Boolean(run)).map(run => [run.id, run])))
    } catch (err) {
      if (!options.background) {
        toast.error(errMsg(err))
        setTimeline(null)
        setTrace(null)
        setRunsById({})
      }
    } finally {
      if (!options.background) setLoadingRoom(false)
    }
  }, [activeSpaceId, selectedGroupId])

  useEffect(() => { void loadAgents() }, [loadAgents])
  useEffect(() => { void loadGroups() }, [loadGroups])
  useEffect(() => { void loadRoom(selectedGroupId) }, [loadRoom, selectedGroupId])

  useEffect(() => {
    const firstActiveAgent = agents.find(agent => agent.status === 'active')
    if (!managerAgentId && firstActiveAgent) setManagerAgentId(firstActiveAgent.id)
  }, [agents, managerAgentId])

  const managerOptions = useMemo(
    () => agents
      .filter(agent => agent.status === 'active')
      .map(agent => ({ value: agent.id, label: agent.name })),
    [agents],
  )

  const selectedGroup = timeline?.group ?? groups.find(group => group.id === selectedGroupId) ?? null
  const delegations = timeline?.delegations ?? []
  const messages = timeline?.messages ?? []
  const members = timeline?.members ?? []
  const conversations = useMemo(() => conversationRoots(messages), [messages])
  const selectedConversation = useMemo(
    () => conversations.find(item => item.id === selectedConversationId) ?? null,
    [conversations, selectedConversationId],
  )
  const chatEntries = useMemo(
    () => buildChatEntries(selectedConversation, messages, delegations),
    [selectedConversation, messages, delegations],
  )
  const rootRun = selectedGroup?.root_run_id ? runsById[selectedGroup.root_run_id] : null
  const activeWorkItems = useMemo(
    () => collectActiveWorkItems(selectedGroup, rootRun, messages, delegations, runsById),
    [selectedGroup, rootRun, messages, delegations, runsById],
  )
  const pendingProjectedReplies = useMemo(
    () => roomHasPendingProjectedReplies(selectedConversation, messages, runsById),
    [selectedConversation, messages, runsById],
  )
  const roomTurns = useMemo(
    () => collectRoomTurnRuns(selectedGroup, messages, delegations, runsById),
    [selectedGroup, messages, delegations, runsById],
  )
  const autoRefreshRoom = roomHasLiveWork(selectedGroup, rootRun, activeWorkItems, delegations)
  const shouldAutoRefreshRoom = autoRefreshRoom || pendingProjectedReplies

  useEffect(() => {
    if (!selectedGroup) {
      setSelectedConversationId(null)
      return
    }
    setSelectedConversationId(current => {
      if (conversations.length === 0) return current
      if (current === 'new') return current
      if (current && conversations.some(item => item.id === current)) return current
      return conversations[0]?.id ?? 'new'
    })
  }, [conversations, selectedGroup])

  useEffect(() => {
    if (!activeSpaceId || !selectedGroupId || !shouldAutoRefreshRoom) return
    const timer = window.setInterval(() => {
      if (backgroundRefreshInFlight.current) return
      backgroundRefreshInFlight.current = true
      void loadRoom(selectedGroupId, { background: true }).finally(() => {
        backgroundRefreshInFlight.current = false
      })
    }, 1200)
    return () => window.clearInterval(timer)
  }, [activeSpaceId, loadRoom, selectedGroupId, shouldAutoRefreshRoom])

  function openRoom(groupId: string) {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('room', groupId)
      next.delete('view')
      return next
    })
  }

  function closeRoom() {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.delete('room')
      next.delete('view')
      return next
    })
    setTimeline(null)
    setTrace(null)
    setRunsById({})
    setSelectedConversationId(null)
    setMessage(emptyRoomMessageComposerValue())
    setMessageResetToken(token => token + 1)
    setRoutingMode('direct')
  }

  function setRoomView(nextView: RoomView) {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (nextView === 'settings') next.set('view', 'settings')
      else next.delete('view')
      return next
    })
  }

  function toggleMember(agentId: string) {
    setMemberAgentIds(current =>
      current.includes(agentId)
        ? current.filter(id => id !== agentId)
        : [...current, agentId],
    )
  }

  async function createRoom() {
    if (!activeSpaceId || !managerAgentId || !title.trim()) return
    setBusy('create')
    try {
      const activeAgentIds = new Set(agents.filter(agent => agent.status === 'active').map(agent => agent.id))
      const memberIds = Array.from(new Set([managerAgentId, ...memberAgentIds]))
        .filter(agentId => activeAgentIds.has(agentId))
      const result = await agentGroupsApi.create({
        space_id: activeSpaceId,
        title: title.trim(),
        ...(goal.trim() ? { goal: goal.trim() } : {}),
        manager_agent_id: managerAgentId,
        member_agent_ids: memberIds,
        budget_json: {},
        context_policy_json: {},
      })
      setTitle('')
      setGoal('')
      setMemberAgentIds([])
      setGroups(current => [result.group, ...current.filter(item => item.id !== result.group.id)])
      openRoom(result.group.id)
      toast.success('Room created')
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function updateRoomDetails(next: { title: string; goal: string }) {
    if (!activeSpaceId || !selectedGroup || !next.title.trim()) return
    setBusy('settings')
    try {
      const result = await agentGroupsApi.update(selectedGroup.id, {
        space_id: activeSpaceId,
        title: next.title.trim(),
        goal: next.goal.trim(),
      })
      setGroups(current => current.map(item => item.id === result.group.id ? result.group : item))
      setTimeline(current => current ? { ...current, group: result.group } : current)
      setTrace(current => current ? { ...current, group: result.group, timeline: { ...current.timeline, group: result.group } } : current)
      toast.success('Room settings saved')
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function sendMessage() {
    const content = message.text.trim()
    if (!activeSpaceId || !selectedGroup || !content) return
    if (hasPendingDirectMentions(message, routingMode)) return
    setBusy('message')
    try {
      const recipientSegments = routingMode === 'direct' ? directRoutingSegments(message) : []
      const result = await agentGroupsApi.sendMessage(selectedGroup.id, {
        space_id: activeSpaceId,
        group_id: selectedGroup.id,
        content,
        parent_message_id: selectedConversation?.message.id ?? undefined,
        routing_mode: routingMode,
        ...(recipientSegments.length ? { recipient_segments: recipientSegments } : {}),
        metadata_json: {
          route_preview: {
            mode: routingMode,
            kind: routePreviewKind(message, routingMode),
            run_count: routePreviewRunCount(message, routingMode),
          },
          ...(routingMode === 'agent_coordination' && message.mentionIds.length
            ? { coordination_target_agent_ids: message.mentionIds }
            : {}),
        },
      })
      setMessage(emptyRoomMessageComposerValue())
      setMessageResetToken(token => token + 1)
      setSelectedConversationId(selectedConversationId === 'new' || !selectedConversation ? result.message.id : selectedConversation.id)
      await loadRoom(selectedGroup.id)
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function changeStatus(action: 'pause' | 'resume' | 'cancel') {
    if (!selectedGroup) return
    setBusy(action)
    try {
      if (action === 'pause') await agentGroupsApi.pause(selectedGroup.id)
      if (action === 'resume') await agentGroupsApi.resume(selectedGroup.id)
      if (action === 'cancel') await agentGroupsApi.cancel(selectedGroup.id)
      await Promise.all([loadGroups(), loadRoom(selectedGroup.id)])
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  if (!selectedGroupId) {
    return (
      <RoomsLanding
        activeSpaceId={activeSpaceId}
        activeSpaceName={activeSpaceName}
        agents={agents}
        groups={groups}
        loadingGroups={loadingGroups}
        statusFilter={statusFilter}
        setStatusFilter={setStatusFilter}
        managerAgentId={managerAgentId}
        setManagerAgentId={setManagerAgentId}
        managerOptions={managerOptions}
        memberAgentIds={memberAgentIds}
        toggleMember={toggleMember}
        title={title}
        setTitle={setTitle}
        goal={goal}
        setGoal={setGoal}
        busy={busy}
        createRoom={createRoom}
        openRoom={openRoom}
        refreshRooms={loadGroups}
      />
    )
  }

  return (
    <div className="flex h-[calc(100vh-96px)] min-h-[620px] flex-col overflow-hidden">
      <ConfirmDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        title="Cancel room work"
        description="This marks the room as cancelled and prevents more work from starting. Existing messages, runs, and audit history stay visible."
        confirmLabel="Cancel room work"
        variant="outline"
        onConfirm={() => void changeStatus('cancel')}
      />

      {!selectedGroup ? (
        <div className="flex h-full items-center justify-center p-6">
          <Card className="max-w-md p-8 text-center">
            <CardTitle>Room unavailable</CardTitle>
            <p className="mt-3 text-sm text-muted-foreground">
              {loadingRoom ? 'Loading room...' : 'This room was not found or is not accessible.'}
            </p>
            <Button className="mt-4" variant="outline" onClick={closeRoom}>
              <ArrowLeft className="size-4" />Rooms
            </Button>
          </Card>
        </div>
      ) : roomView === 'settings' ? (
        <RoomSettingsView
          group={selectedGroup}
          agents={agents}
          members={members}
          rootRun={rootRun}
          roomTurns={roomTurns}
          delegations={delegations}
          runsById={runsById}
          trace={trace}
          busy={busy}
          loadingRoom={loadingRoom}
          onBackToChat={() => setRoomView('chat')}
          onBackToRooms={closeRoom}
          onRefresh={() => void loadRoom(selectedGroup.id)}
          onSaveDetails={updateRoomDetails}
          onPause={() => void changeStatus('pause')}
          onResume={() => void changeStatus('resume')}
          onCancel={() => setCancelOpen(true)}
        />
      ) : (
        <RoomChatView
          group={selectedGroup}
          activeSpaceName={activeSpaceName}
          agents={agents}
          members={members}
          conversations={conversations}
          selectedConversationId={selectedConversationId}
          onSelectConversation={setSelectedConversationId}
          chatEntries={chatEntries}
          selectedConversation={selectedConversation}
          delegations={delegations}
          runsById={runsById}
          activeWorkItems={activeWorkItems}
          autoRefreshing={shouldAutoRefreshRoom}
          pendingProjectedReplies={pendingProjectedReplies}
          loadingRoom={loadingRoom}
          message={message}
          setMessage={setMessage}
          routingMode={routingMode}
          setRoutingMode={setRoutingMode}
          messageResetToken={messageResetToken}
          busy={busy}
          sendMessage={sendMessage}
          onBackToRooms={closeRoom}
          onSettings={() => setRoomView('settings')}
          onRefresh={() => void loadRoom(selectedGroup.id)}
        />
      )}
    </div>
  )
}

function RoomsLanding({
  activeSpaceId,
  activeSpaceName,
  agents,
  groups,
  loadingGroups,
  statusFilter,
  setStatusFilter,
  managerAgentId,
  setManagerAgentId,
  managerOptions,
  memberAgentIds,
  toggleMember,
  title,
  setTitle,
  goal,
  setGoal,
  busy,
  createRoom,
  openRoom,
  refreshRooms,
}: {
  activeSpaceId: string | null
  activeSpaceName: string | null
  agents: AgentOut[]
  groups: AgentRunGroup[]
  loadingGroups: boolean
  statusFilter: string
  setStatusFilter: (value: string) => void
  managerAgentId: string
  setManagerAgentId: (value: string) => void
  managerOptions: { value: string; label: string }[]
  memberAgentIds: string[]
  toggleMember: (agentId: string) => void
  title: string
  setTitle: (value: string) => void
  goal: string
  setGoal: (value: string) => void
  busy: string | null
  createRoom: () => Promise<void>
  openRoom: (groupId: string) => void
  refreshRooms: () => Promise<void>
}) {
  return (
    <div className="mx-auto grid min-h-full w-full max-w-6xl gap-5 p-6 xl:grid-cols-[380px_minmax(0,1fr)]">
      <div className="xl:sticky xl:top-6 xl:self-start">
        <div className="mb-5 flex items-center gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-primary/30 bg-primary/10">
            <MessagesSquare className="size-5 text-accent-foreground" />
          </div>
          <div className="min-w-0">
            <h1 className="text-xl font-semibold tracking-tight">Agent Rooms</h1>
            <p className="truncate text-xs text-muted-foreground">{activeSpaceName ?? activeSpaceId ?? 'No space selected'}</p>
          </div>
        </div>

        <Card className="space-y-4 p-4">
          <div className="flex items-center justify-between gap-3">
            <CardTitle>Create room</CardTitle>
            {busy === 'create' && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
          </div>
          <div className="space-y-2">
            <Label htmlFor="room-title">Title</Label>
            <Input id="room-title" value={title} onChange={event => setTitle(event.target.value)} disabled={!activeSpaceId} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="room-goal">Goal (optional)</Label>
            <Textarea id="room-goal" value={goal} onChange={event => setGoal(event.target.value)} disabled={!activeSpaceId} />
          </div>
          <div className="space-y-2">
            <Label>Manager</Label>
            <Select
              value={managerAgentId}
              options={managerOptions.length ? managerOptions : [{ value: '', label: 'No active agents' }]}
              onChange={setManagerAgentId}
              disabled={!activeSpaceId || managerOptions.length === 0}
            />
          </div>
          <div className="space-y-2">
            <Label>Members</Label>
            <div className="max-h-44 space-y-1 overflow-auto rounded-md border border-border p-2">
              {agents.length === 0 ? (
                <p className="px-1 py-2 text-sm text-muted-foreground">No agents.</p>
              ) : agents.map(agent => (
                <label key={agent.id} className="flex items-center gap-2 rounded px-1.5 py-1 text-sm hover:bg-accent">
                  <input
                    type="checkbox"
                    checked={agent.id === managerAgentId || memberAgentIds.includes(agent.id)}
                    disabled={agent.id === managerAgentId || agent.status !== 'active' || !activeSpaceId}
                    onChange={() => toggleMember(agent.id)}
                  />
                  <span className="min-w-0 flex-1 truncate">{agent.name}</span>
                  <StatusBadge status={agent.status} />
                </label>
              ))}
            </div>
          </div>
          <Button
            className="w-full"
            onClick={() => void createRoom()}
            disabled={!activeSpaceId || busy !== null || !managerAgentId || !title.trim()}
          >
            {busy === 'create' ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
            Create
          </Button>
        </Card>
      </div>

      <section className="min-w-0">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Rooms</h2>
            <p className="text-xs text-muted-foreground">{groups.length} visible</p>
          </div>
          <div className="flex items-center gap-2">
            <Select
              size="sm"
              className="w-32"
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: '', label: 'Any' },
                { value: 'active', label: 'Active' },
                { value: 'paused', label: 'Paused' },
                { value: 'cancelled', label: 'Cancelled' },
              ]}
            />
            <Button size="sm" variant="outline" onClick={() => void refreshRooms()} disabled={loadingGroups || !activeSpaceId}>
              <RefreshCw className="size-3.5" />Refresh
            </Button>
          </div>
        </div>

        {loadingGroups ? (
          <div className="grid gap-3 md:grid-cols-2">
            <Skeleton className="h-36 w-full" />
            <Skeleton className="h-36 w-full" />
          </div>
        ) : groups.length === 0 ? (
          <div className="rounded-lg border border-border p-10 text-center text-sm text-muted-foreground">
            {activeSpaceId ? 'No rooms.' : 'Select a space.'}
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {groups.map(group => (
              <button
                key={group.id}
                type="button"
                onClick={() => openRoom(group.id)}
                className="rounded-lg border border-border bg-card p-4 text-left transition-colors hover:border-primary/40 hover:bg-accent"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold">{group.title}</h3>
                    {group.goal ? (
                      <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{group.goal}</p>
                    ) : (
                      <p className="mt-1 text-sm text-muted-foreground">No goal set.</p>
                    )}
                  </div>
                  <StatusBadge status={group.status} />
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                  <span>{fmt(group.updated_at)}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function RoomChatView({
  group,
  activeSpaceName,
  agents,
  members,
  conversations,
  selectedConversationId,
  onSelectConversation,
  chatEntries,
  selectedConversation,
  delegations,
  runsById,
  activeWorkItems,
  autoRefreshing,
  pendingProjectedReplies,
  loadingRoom,
  message,
  setMessage,
  routingMode,
  setRoutingMode,
  messageResetToken,
  busy,
  sendMessage,
  onBackToRooms,
  onSettings,
  onRefresh,
}: {
  group: AgentRunGroup
  activeSpaceName: string | null
  agents: AgentOut[]
  members: AgentRunGroupTimeline['members']
  conversations: Conversation[]
  selectedConversationId: ConversationId
  onSelectConversation: (id: ConversationId) => void
  chatEntries: ChatEntry[]
  selectedConversation: Conversation | null
  delegations: RunDelegation[]
  runsById: Record<string, Run>
  activeWorkItems: WorkItem[]
  autoRefreshing: boolean
  pendingProjectedReplies: boolean
  loadingRoom: boolean
  message: RoomMessageComposerValue
  setMessage: (value: RoomMessageComposerValue) => void
  routingMode: RoomRoutingMode
  setRoutingMode: (value: RoomRoutingMode) => void
  messageResetToken: number
  busy: string | null
  sendMessage: () => Promise<void>
  onBackToRooms: () => void
  onSettings: () => void
  onRefresh: () => void
}) {
  const messageSendBlocked = !message.text.trim() || hasPendingDirectMentions(message, routingMode)
  return (
    <div className="grid h-full min-h-0 grid-cols-[300px_minmax(0,1fr)] overflow-hidden border-y border-border bg-background max-lg:grid-cols-1">
      <aside className="flex min-h-0 flex-col border-r border-border bg-card max-lg:hidden">
        <div className="border-b border-border p-3">
          <Button size="sm" variant="ghost" onClick={onBackToRooms} className="mb-3">
            <ArrowLeft className="size-4" />Rooms
          </Button>
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold">{group.title}</h2>
              <p className="mt-1 truncate text-xs text-muted-foreground">{activeSpaceName ?? group.space_id}</p>
            </div>
            <StatusBadge status={group.status} />
          </div>
        </div>

        <div className="border-b border-border p-3">
          <Button
            size="sm"
            className="w-full justify-start"
            variant={selectedConversationId === 'new' ? 'default' : 'outline'}
            onClick={() => onSelectConversation('new')}
          >
            <Plus className="size-4" />New conversation
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto p-2">
          {conversations.length === 0 ? (
            <p className="px-2 py-4 text-sm text-muted-foreground">No conversations.</p>
          ) : conversations.map(conversation => {
            const run = conversation.run_id ? runsById[conversation.run_id] : null
            return (
              <button
                key={conversation.id}
                type="button"
                onClick={() => onSelectConversation(conversation.id)}
                className={`mb-1 w-full rounded-md px-3 py-2 text-left transition-colors ${
                  selectedConversationId === conversation.id ? 'bg-primary/10 text-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate text-sm font-medium">{conversation.title}</span>
                  {run && <StatusBadge status={run.status} />}
                </div>
                <div className="mt-1 flex items-center gap-2 text-[11px]">
                  <span>{fmt(conversation.updated_at)}</span>
                  {conversation.count > 1 && <span>{conversation.count} turns</span>}
                </div>
              </button>
            )
          })}
        </div>
      </aside>

      <main className="flex min-h-0 flex-col">
        <div className="flex items-center justify-between gap-3 border-b border-border bg-card px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Button size="icon" variant="ghost" onClick={onBackToRooms} className="lg:hidden" aria-label="Rooms">
                <ArrowLeft className="size-4" />
              </Button>
              <div className="min-w-0">
                <h1 className="truncate text-base font-semibold">
                  {selectedConversationId === 'new' || conversations.length === 0 ? 'New conversation' : selectedConversation?.title ?? group.title}
                </h1>
                <p className="truncate text-xs text-muted-foreground">
                  Manager {agentName(agents, group.manager_agent_id)}
                </p>
              </div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button size="sm" variant="outline" onClick={onRefresh} disabled={loadingRoom}>
              <RefreshCw className="size-3.5" />Refresh
            </Button>
            <Button size="sm" variant="outline" onClick={onSettings}>
              <Settings className="size-3.5" />Settings
            </Button>
          </div>
        </div>

        <ChatStatusStrip
          activeWorkItems={activeWorkItems}
          delegations={delegations}
          agents={agents}
          autoRefreshing={autoRefreshing}
          pendingProjectedReplies={pendingProjectedReplies}
        />

        <div className="min-h-0 flex-1 overflow-auto px-4 py-5">
          {selectedConversationId === 'new' || conversations.length === 0 ? (
            <div className="mx-auto flex h-full max-w-2xl items-center justify-center text-center text-sm text-muted-foreground">
              <div>
                <MessageSquare className="mx-auto mb-3 size-8 text-muted-foreground" />
                <p>Start a new room conversation.</p>
              </div>
            </div>
          ) : chatEntries.length === 0 ? (
            <div className="mx-auto flex h-full max-w-2xl items-center justify-center text-center text-sm text-muted-foreground">
              No messages in this conversation.
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-4">
              {chatEntries.map(entry => entry.kind === 'message' && entry.message ? (
                <ChatMessageBubble
                  key={entry.key}
                  message={entry.message}
                  agents={agents}
                  run={entry.message.run_id ? runsById[entry.message.run_id] : null}
                />
              ) : entry.delegations ? (
                <AgentCallsBubble
                  key={entry.key}
                  delegations={entry.delegations}
                  agents={agents}
                  runsById={runsById}
                />
              ) : null)}
            </div>
          )}
        </div>

        <div className="border-t border-border bg-card px-4 py-3">
          <div className="mx-auto max-w-3xl">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <RoutingModeControls
                value={routingMode}
                onChange={setRoutingMode}
                disabled={group.status !== 'active' || busy !== null}
              />
              <RoutePreview
                group={group}
                agents={agents}
                message={message}
                routingMode={routingMode}
              />
            </div>
            <div className="flex items-end gap-2">
              <div className="min-w-0 flex-1">
                <RoomMessageComposer
                  value={message}
                  onChange={setMessage}
                  agents={agents}
                  members={members}
                  disabled={group.status !== 'active' || busy !== null}
                  resetToken={messageResetToken}
                  onSubmit={() => void sendMessage()}
                />
              </div>
              <Button
                onClick={() => void sendMessage()}
                disabled={group.status !== 'active' || busy !== null || messageSendBlocked}
                aria-label="Send"
              >
                {busy === 'message' ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
                Send
              </Button>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

function RoutingModeControls({
  value,
  onChange,
  disabled,
}: {
  value: RoomRoutingMode
  onChange: (value: RoomRoutingMode) => void
  disabled: boolean
}) {
  return (
    <div className="flex shrink-0 items-center gap-1 rounded-md border border-border bg-muted/20 p-0.5">
      <Button
        type="button"
        size="sm"
        variant={value === 'direct' ? 'default' : 'outline'}
        onClick={() => onChange('direct')}
        disabled={disabled}
        className="h-7 px-2 text-xs"
      >
        <Bot className="size-3.5" />Direct
      </Button>
      <Button
        type="button"
        size="sm"
        variant={value === 'agent_coordination' ? 'default' : 'outline'}
        onClick={() => onChange('agent_coordination')}
        disabled={disabled}
        className="h-7 px-2 text-xs"
      >
        <GitBranch className="size-3.5" />Coordinate
      </Button>
    </div>
  )
}

function RoutePreview({
  group,
  agents,
  message,
  routingMode,
}: {
  group: AgentRunGroup
  agents: AgentOut[]
  message: RoomMessageComposerValue
  routingMode: RoomRoutingMode
}) {
  const segments = directRoutingSegments(message)
  const kind = routePreviewKind(message, routingMode)
  const runCount = routePreviewRunCount(message, routingMode)
  const managerLabel = group.manager_agent_id ? mentionLabel(agents, group.manager_agent_id) : '@Manager'
  const content = message.text.trim()
  const pendingIds = routingMode === 'direct' ? pendingDirectMentionIds(message) : []

  let chips: Array<{ key: string; text: string }> = []
  if (routingMode === 'agent_coordination') {
    chips = [{
      key: 'coordination',
      text: `${managerLabel}${content ? `: ${previewText(content)}` : ''}`,
    }]
  } else if (segments.length === 0) {
    chips = [{
      key: 'manager-default',
      text: pendingIds.length > 0 ? 'Add task text after @' : managerLabel,
    }]
  } else {
    chips = segments.map((segment, index) => ({
      key: `${index}:${segment.recipient_agent_ids.join(',')}`,
      text: `${segment.recipient_agent_ids.map(id => mentionLabel(agents, id)).join(', ')}: ${previewText(segment.content)}`,
    }))
  }

  return (
    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
      <Badge variant={routingMode === 'agent_coordination' ? 'warning' : 'muted'}>{kind}</Badge>
      <span>{runCount} run{runCount === 1 ? '' : 's'}</span>
      {chips.slice(0, 3).map(chip => (
        <span key={chip.key} className="max-w-[260px] truncate rounded-full bg-muted px-2 py-0.5">
          {chip.text}
        </span>
      ))}
      {chips.length > 3 && <span>+{chips.length - 3} more</span>}
      {pendingIds.map(id => (
        <span key={`pending:${id}`} className="rounded-full bg-warning/10 px-2 py-0.5 text-warning">
          {mentionLabel(agents, id)} pending
        </span>
      ))}
    </div>
  )
}

function ChatStatusStrip({
  activeWorkItems,
  delegations,
  agents,
  autoRefreshing,
  pendingProjectedReplies,
}: {
  activeWorkItems: WorkItem[]
  delegations: RunDelegation[]
  agents: AgentOut[]
  autoRefreshing: boolean
  pendingProjectedReplies: boolean
}) {
  const latestCalls = delegations.slice(-3).reverse()
  const hasExecutableWork = activeWorkItems.some(item => item.status === 'queued' || item.status === 'running')
  const hasWaitingWork = activeWorkItems.some(item => item.status === 'waiting_for_dependency')
  const statusLabel = hasExecutableWork ? 'Running' : hasWaitingWork ? 'Waiting' : pendingProjectedReplies ? 'Updating' : 'Idle'
  return (
    <div className="border-b border-border bg-muted/30 px-4 py-2">
      <div className="mx-auto flex max-w-3xl flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant={autoRefreshing ? 'warning' : 'muted'} className="gap-1">
          {autoRefreshing && <Loader2 className="size-3 animate-spin" />}
          {statusLabel}
        </Badge>
        {activeWorkItems.length === 0 ? (
          <span>{pendingProjectedReplies ? 'Waiting for agent messages' : 'No active agent work'}</span>
        ) : activeWorkItems.map(item => (
          <span key={item.key} className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5">
            <Bot className="size-3" />
            {agentName(agents, item.agent_id)}
            <StatusBadge status={item.status} />
          </span>
        ))}
        {latestCalls.map(item => (
          <span key={item.id} className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5">
            {agentName(agents, item.requesting_agent_id)} {'->'} {agentName(agents, item.target_agent_id)}
            <StatusBadge status={item.status} />
          </span>
        ))}
      </div>
    </div>
  )
}

function ChatMessageBubble({
  message,
  agents,
  run,
}: {
  message: AgentRunMessage
  agents: AgentOut[]
  run: Run | null
}) {
  const fromUser = message.message_type === 'user_instruction'
  const label = message.sender_agent_id ? agentName(agents, message.sender_agent_id) : 'You'
  const target = message.mentions_json[0]?.agent_id
  const error = runErrorText(run)
  return (
    <div className={`flex ${fromUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[82%] rounded-lg border px-4 py-3 ${
        fromUser ? 'border-primary/25 bg-primary/10' : 'border-border bg-card'
      }`}>
        <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">{label}</span>
          {fromUser && target && <span>to {mentionLabel(agents, target)}</span>}
          <span>{fmt(message.created_at)}</span>
          {run && <StatusBadge status={run.status} />}
        </div>
        <MarkdownMessage content={message.content} />
        {error && <RunIssue label="Agent turn stopped" message={error} className="mt-2" compact />}
      </div>
    </div>
  )
}

function AgentCallsBubble({
  delegations,
  agents,
  runsById,
}: {
  delegations: RunDelegation[]
  agents: AgentOut[]
  runsById: Record<string, Run>
}) {
  const [open, setOpen] = useState(false)
  const activeCount = delegations.filter(item => activeDelegationStatus(item.status)).length
  const doneCount = terminalDelegationCount(delegations)
  return (
    <div className="flex justify-start">
      <div className="max-w-[82%] rounded-lg border border-border bg-card px-4 py-3">
        <button
          type="button"
          onClick={() => setOpen(value => !value)}
          className="flex w-full items-center justify-between gap-3 text-left"
        >
          <span className="flex min-w-0 items-center gap-2 text-sm font-medium">
            <GitBranch className="size-4 shrink-0" />
            <span className="truncate">Agent calls</span>
          </span>
          <span className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
            {activeCount > 0 ? `${activeCount} active` : `${doneCount}/${delegations.length} done`}
            {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </span>
        </button>
        {open && (
          <div className="mt-3 space-y-2 border-t border-border pt-3">
            {delegations.map(delegation => {
              const run = delegation.child_run_id ? runsById[delegation.child_run_id] : null
              const error = runErrorText(run)
              return (
                <div key={delegation.id} className="rounded-md border border-border px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">
                      {agentName(agents, delegation.requesting_agent_id)} {'->'} {agentName(agents, delegation.target_agent_id)}
                    </span>
                    <StatusBadge status={run?.status ?? delegation.status} />
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed">{delegation.instruction}</p>
                  {delegation.result_summary && (
                    <div className="mt-2">
                      <MarkdownMessage content={delegation.result_summary} className="text-xs text-muted-foreground" />
                    </div>
                  )}
                  {error && <RunIssue label="Call stopped" message={error} className="mt-2" compact />}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

function RoomSettingsView({
  group,
  agents,
  members,
  rootRun,
  roomTurns,
  delegations,
  runsById,
  trace,
  busy,
  loadingRoom,
  onBackToChat,
  onBackToRooms,
  onRefresh,
  onSaveDetails,
  onPause,
  onResume,
  onCancel,
}: {
  group: AgentRunGroup
  agents: AgentOut[]
  members: AgentRunGroupTimeline['members']
  rootRun: Run | null
  roomTurns: Run[]
  delegations: RunDelegation[]
  runsById: Record<string, Run>
  trace: AgentRunGroupTrace | null
  busy: string | null
  loadingRoom: boolean
  onBackToChat: () => void
  onBackToRooms: () => void
  onRefresh: () => void
  onSaveDetails: (next: { title: string; goal: string }) => Promise<void>
  onPause: () => void
  onResume: () => void
  onCancel: () => void
}) {
  const [showAudit, setShowAudit] = useState(false)
  const [draftTitle, setDraftTitle] = useState(group.title)
  const [draftGoal, setDraftGoal] = useState(group.goal)
  useEffect(() => {
    setDraftTitle(group.title)
    setDraftGoal(group.goal)
  }, [group.id, group.title, group.goal])
  const detailsDirty = draftTitle.trim() !== group.title || draftGoal.trim() !== group.goal
  return (
    <div className="min-h-0 flex-1 overflow-auto p-6">
      <div className="mx-auto max-w-5xl space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap gap-2">
              <Button size="sm" variant="ghost" onClick={onBackToChat}>
                <ArrowLeft className="size-4" />Chat
              </Button>
              <Button size="sm" variant="ghost" onClick={onBackToRooms}>
                <MessagesSquare className="size-4" />Rooms
              </Button>
            </div>
            <h1 className="truncate text-xl font-semibold tracking-tight">{group.title}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{group.goal || 'No goal set.'}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={group.status} />
            <Button size="sm" variant="outline" onClick={onRefresh} disabled={loadingRoom}>
              <RefreshCw className="size-3.5" />Refresh
            </Button>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <Metric label="Active calls" value={delegations.filter(item => activeDelegationStatus(item.status)).length} />
          <Metric label="Done calls" value={terminalDelegationCount(delegations)} />
          <Metric label="Runs" value={(trace?.root_run_id ? 1 : 0) + (trace?.child_run_ids.length ?? 0)} />
        </div>

        <Card className="space-y-4 p-4">
          <CardTitle>Room details</CardTitle>
          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <div className="space-y-2">
              <Label htmlFor="settings-room-title">Title</Label>
              <Input
                id="settings-room-title"
                value={draftTitle}
                onChange={event => setDraftTitle(event.target.value)}
                disabled={busy !== null}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="settings-room-goal">Goal</Label>
              <Textarea
                id="settings-room-goal"
                value={draftGoal}
                onChange={event => setDraftGoal(event.target.value)}
                disabled={busy !== null}
                className="min-h-[96px]"
              />
            </div>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => void onSaveDetails({ title: draftTitle, goal: draftGoal })}
            disabled={busy !== null || !draftTitle.trim() || !detailsDirty}
          >
            {busy === 'settings' ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
            Save details
          </Button>
        </Card>

        <Card className="space-y-4 p-4">
          <CardTitle>Room controls</CardTitle>
          <div className="flex flex-wrap gap-2">
            {group.status === 'active' && (
              <Button size="sm" variant="outline" onClick={onPause} disabled={busy !== null}>
                <Pause className="size-3.5" />Pause room
              </Button>
            )}
            {group.status === 'paused' && (
              <Button size="sm" variant="outline" onClick={onResume} disabled={busy !== null}>
                <Play className="size-3.5" />Resume room
              </Button>
            )}
            {group.status !== 'cancelled' && (
              <Button
                size="sm"
                variant="outline"
                onClick={onCancel}
                disabled={busy !== null}
                title="Marks this room as cancelled and prevents more room work. Existing messages, runs, and audit history stay visible."
              >
                <Ban className="size-3.5" />Cancel room work
              </Button>
            )}
          </div>
        </Card>

        <Card className="space-y-3 p-4">
          <CardTitle>Members</CardTitle>
          <div className="flex flex-wrap gap-2">
            {members.map(member => (
              <Badge key={member.id} variant={member.role === 'manager' ? 'default' : 'secondary'} className="gap-1">
                <Bot className="size-3" />{agentName(agents, member.agent_id)}
              </Badge>
            ))}
          </div>
        </Card>

        <Card className="space-y-4 p-4">
          <CardTitle>Outputs</CardTitle>
          <div className="grid gap-4 md:grid-cols-2">
            <LinkList icon="artifact" title="Artifacts" ids={trace?.artifact_ids ?? []} to={id => `/artifacts/${id}`} />
            <LinkList icon="proposal" title="Proposals" ids={trace?.proposal_ids ?? []} to={id => `/proposals/${id}`} />
          </div>
        </Card>

        <Card className="space-y-3 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>Execution audit</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">Advanced trace records for debugging and governance.</p>
            </div>
            <Button size="sm" variant="outline" onClick={() => setShowAudit(value => !value)}>
              <GitBranch className="size-3.5" />{showAudit ? 'Hide audit' : 'Show audit'}
            </Button>
          </div>
          {showAudit && (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
              <div className="space-y-3">
                <RunNode title="Root run" runId={group.root_run_id} run={rootRun} />
                {roomTurns.map(run => (
                  <RunNode
                    key={run.id}
                    title={run.agent_id === group.manager_agent_id ? 'Manager turn' : 'Agent turn'}
                    runId={run.id}
                    run={run}
                  />
                ))}
                {delegations.map(item => (
                  <div key={item.id} className="rounded-md border border-border p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <GitBranch className="size-4" />
                      <span className="text-sm font-medium">
                        {agentName(agents, item.requesting_agent_id)} {'->'} {agentName(agents, item.target_agent_id)}
                      </span>
                      <StatusBadge status={item.status} />
                    </div>
                    <p className="mt-2 line-clamp-3 text-sm text-muted-foreground">{item.instruction}</p>
                    {item.child_run_id && (
                      <RunNode title="Child run" runId={item.child_run_id} run={runsById[item.child_run_id]} compact />
                    )}
                  </div>
                ))}
              </div>
              <LinkList icon="policy" title="Policy records" ids={trace?.policy_decision_record_ids ?? []} to={() => ''} />
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3 text-center">
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  )
}

function RunNode({
  title,
  runId,
  run,
  compact = false,
}: {
  title: string
  runId: string | null | undefined
  run: Run | null | undefined
  compact?: boolean
}) {
  return (
    <div className={`rounded-md border border-border p-3 ${compact ? 'mt-3' : ''}`}>
      <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
        <GitBranch className="size-4" />{title}
        {run && <StatusBadge status={run.status} />}
      </div>
      {runId ? (
        <Link to={`/runs/${runId}`} className="mt-1 block font-mono text-xs text-accent-foreground hover:underline">
          {runId}
        </Link>
      ) : (
        <p className="mt-1 text-xs text-muted-foreground">-</p>
      )}
      {run && <RunMeta run={run} />}
    </div>
  )
}

function RunIssue({
  label,
  message,
  className = '',
  compact = false,
}: {
  label: string
  message: string
  className?: string
  compact?: boolean
}) {
  return (
    <p className={`rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning ${className}`}>
      <span className="font-medium">{label}</span>
      {!compact && <span>: </span>}
      {compact ? <span className="ml-1">{message}</span> : <span>{message}</span>}
    </p>
  )
}

function RunMeta({ run }: { run: Run }) {
  const error = runErrorText(run)
  return (
    <div className="mt-2 space-y-2 text-xs text-muted-foreground">
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {run.selected_adapter_type && <span>Adapter {run.selected_adapter_type}</span>}
        <span>Started {fmt(run.started_at)}</span>
        <span>Ended {fmt(run.ended_at)}</span>
      </div>
      {error && <RunIssue label="Last error" message={error} />}
    </div>
  )
}

function LinkList({
  icon,
  title,
  ids,
  to,
}: {
  icon: 'artifact' | 'proposal' | 'policy'
  title: string
  ids: string[]
  to: (id: string) => string
}) {
  const Icon = icon === 'artifact' ? FileText : icon === 'proposal' ? CheckCircle2 : Bot
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Icon className="size-4" />{title}
      </div>
      {ids.length === 0 ? (
        <p className="rounded-md border border-border px-3 py-2 text-xs text-muted-foreground">None</p>
      ) : (
        <div className="space-y-1">
          {ids.map(id => {
            const href = to(id)
            return href ? (
              <Link key={id} to={href} className="block rounded-md border border-border px-3 py-2 font-mono text-xs text-accent-foreground hover:bg-accent">
                {id}
              </Link>
            ) : (
              <div key={id} className="rounded-md border border-border px-3 py-2 font-mono text-xs text-muted-foreground">
                {id}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
