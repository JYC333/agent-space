import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

export type NavSection = 'capture' | 'knowledge' | 'agents' | 'dev'
export type AppGroup   = 'daily' | 'work' | 'knowledge' | 'agents' | 'workspace' | 'system'
export type PerspectiveType = 'space-scoped' | 'personal' | 'neutral'

/**
 * Where an app entry originates.
 *
 * built_in  — shipped with the core bundle, always present.
 * installed — a capability that was installed into this instance
 *             (exists in the backend capability registry).
 * external  — references a remote tool or external service (reserved).
 *
 * For MVP all entries are built_in. Future capability install/uninstall
 * would add entries with source: 'installed' at runtime.
 */
export type AppSource = 'built_in' | 'installed' | 'external'

export interface Module {
  // ── Identity ───────────────────────────────────────────────────────────────
  id: string
  label: string
  path: string
  icon: string          // lucide icon name (kebab-case)
  description: string   // gallery card description
  group: AppGroup       // gallery section
  section: NavSection   // nav grouping for the shell layout

  // ── Capability link ────────────────────────────────────────────────────────
  /**
   * Backend capability ID this entry is backed by.
   * undefined = no formal capability (core UI feature).
   *
   * Future: when a capability is installed, its manifest populates this.
   * The frontend can then query GET /capabilities/:capabilityId to read
   * enabled state, version, permissions, etc.
   */
  capabilityId?: string

  // ── Origin ────────────────────────────────────────────────────────────────
  /** Where this entry comes from. */
  source: AppSource

  // ── Runtime state ─────────────────────────────────────────────────────────
  /**
   * Whether the capability is enabled for the active space.
   * - true  → app is interactive and navigable.
   * - false → app appears in the gallery but is grayed out (not clickable).
   *
   * For built_in entries this is always true at static registration time.
   * Future: overlaid from GET /capabilities response per space.
   */
  enabled: boolean

  /**
   * Whether the app card is shown in the home gallery.
   * - true  → card renders in gallery grid.
   * - false → card is hidden (e.g. retired capability, space policy).
   *
   * Intentionally separate from `enabled`: a capability can be enabled
   * but its gallery card hidden (accessed only via direct URL).
   */
  visible: boolean

  /**
   * Dev-status flag: feature is not yet implemented.
   * Shows a "soon" badge on the card. Implies non-interactive regardless
   * of `enabled`. Does NOT mean permanently disabled — `enabled` handles that.
   */
  planned: boolean

  // ── Display preferences (user-adjustable in future) ────────────────────────
  /** Pin to the top row of the home gallery. */
  pinned?: boolean
  /** Explicit display order within the group. Lower = earlier. */
  order?: number

  // ── UI hints ──────────────────────────────────────────────────────────────
  /** Render this card with an indigo accent tile (one per group recommended). */
  accent?: boolean

  // ── Router ────────────────────────────────────────────────────────────────
  /** When true, route is registered as `path/*` to allow nested <Routes>. */
  hasSubRoutes?: boolean
  /** Whether this route operates against personal aggregation, a concrete space, or no perspective. */
  perspectiveType: PerspectiveType
  component: LazyExoticComponent<ComponentType>
}

/**
 * Central app + module registry.
 *
 * Every entry is simultaneously:
 *   - A gallery card on the home page (uses group, icon, description, enabled, visible)
 *   - A React Router route (uses path, component, hasSubRoutes)
 *   - A future capability link (uses capabilityId, source, enabled)
 *
 * ── Extension boundary ──────────────────────────────────────────────────────
 * To add a new BUILT-IN app:
 *   1. Create src/modules/<id>/<PageName>.tsx
 *   2. Add an entry below with source: 'built_in'
 *   3. Route auto-registers in App.tsx
 *
 * To support INSTALLED capabilities in the future (do not implement yet):
 *   1. Fetch enabled capabilities from GET /api/v1/capabilities
 *   2. For each: find the matching entry by capabilityId (or create a new one)
 *   3. Overlay enabled: capability.enabled, visible: capability.enabled
 *   4. For new entries (not in static registry), push to a runtime registry
 *      and register their routes dynamically
 *   5. The component for installed capabilities would be resolved from the
 *      capability manifest's frontend_bundle field (not implemented, reserved)
 *
 * ── State semantics ─────────────────────────────────────────────────────────
 *   planned   = not yet built ("soon" badge, non-interactive, dev concern)
 *   !enabled  = capability off for this space (grayed card, runtime concern)
 *   !visible  = hidden from gallery (space policy or user pref, shown nowhere)
 *   pinned    = promoted in gallery (user preference, future)
 * ───────────────────────────────────────────────────────────────────────────
 */
export const MODULE_REGISTRY: Module[] = [

  // ── Daily ─────────────────────────────────────────────────────────────────
  {
    id: 'today', label: 'Today', path: '/today',
    section: 'capture', group: 'daily', icon: 'sun', accent: true,
    description: "This space's daily overview, active items, and suggested actions.",
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    component: lazy(() => import('./today/TodayPage')),
  },
  {
    id: 'capture', label: 'Capture', path: '/capture',
    section: 'capture', group: 'daily', icon: 'plus',
    description: 'Quickly save thoughts, ideas, notes, and external content.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    component: lazy(() => import('./capture/CapturePage')),
  },
  {
    id: 'activity', label: 'Inbox', path: '/activity',
    section: 'capture', group: 'daily', icon: 'inbox',
    description: 'Capture intake — review raw records before they become proposals.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    hasSubRoutes: true,
    component: lazy(() => import('./activity/ActivityModule')),
  },
  {
    id: 'intake', label: 'Intake', path: '/intake',
    section: 'capture', group: 'daily', icon: 'radio',
    description: 'Connect source streams, triage candidate items, and select evidence for context.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    component: lazy(() => import('./intake/IntakePage')),
  },
  {
    id: 'daily_reports', label: 'Daily Report', path: '/daily-report',
    section: 'capture', group: 'daily', icon: 'calendar-check',
    description: 'Automatically generate a structured daily report from your captures. Experience and memory proposals require your review.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    component: lazy(() => import('./daily_reports/DailyReportSettingsPage')),
  },
  {
    id: 'sessions', label: 'Sessions', path: '/sessions',
    section: 'capture', group: 'daily', icon: 'message-square',
    description: 'Manage and continue agent sessions and conversations.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    component: lazy(() => import('./sessions/SessionsPage')),
  },
  {
    id: 'time', label: 'Time', path: '/time',
    section: 'capture', group: 'daily', icon: 'clock',
    description: 'Track time records and convert them into activity summaries.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: true,
    perspectiveType: 'neutral',
    component: lazy(() => import('./time/TimePage')),
  },

  // ── Work (task → run → outputs → review) ───────────────────────────────────
  {
    id: 'projects', label: 'Projects', path: '/projects',
    section: 'agents', group: 'work', icon: 'folder-kanban', accent: true,
    description: 'Goal and knowledge context. Organize objectives, artifacts, proposals, memory, and linked workspaces.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    order: 5,
    hasSubRoutes: true,
    component: lazy(() => import('./projects/ProjectsModule')),
  },
  {
    id: 'tasks', label: 'Tasks', path: '/tasks',
    section: 'agents', group: 'work', icon: 'list-todo',
    description: 'Plan work, start runs, and review linked outputs.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    order: 10,
    hasSubRoutes: true,
    component: lazy(() => import('./tasks/TasksModule')),
  },
  {
    id: 'runs', label: 'Runs', path: '/runs',
    section: 'agents', group: 'work', icon: 'cpu', accent: true,
    description: 'Inspect agent runs, status, activities, artifacts, and proposals.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    order: 20,
    hasSubRoutes: true,
    component: lazy(() => import('./runs/RunsModule')),
  },
  {
    id: 'proposals', label: 'Review', path: '/proposals',
    section: 'knowledge', group: 'work', icon: 'check-circle',
    description: 'Review memory, knowledge, card, code, and system proposals.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    order: 30,
    hasSubRoutes: true,
    component: lazy(() => import('./memory/ProposalsModule')),
  },
  {
    id: 'artifacts', label: 'Artifacts', path: '/artifacts',
    section: 'agents', group: 'work', icon: 'package',
    description: 'Browse and export outputs produced by runs.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    order: 40,
    hasSubRoutes: true,
    component: lazy(() => import('./artifacts/ArtifactsModule')),
  },

  // ── Knowledge ─────────────────────────────────────────────────────────────
  {
    id: 'knowledge', label: 'Knowledge', path: '/knowledge',
    section: 'knowledge', group: 'knowledge', icon: 'book-open', accent: true,
    description: 'Working notes, canonical wiki knowledge, sources, and review material.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    hasSubRoutes: true,
    component: lazy(() => import('./knowledge/KnowledgeModule')),
  },
  {
    id: 'cards', label: 'Cards', path: '/cards',
    section: 'knowledge', group: 'knowledge', icon: 'layers',
    description: 'Review and manage spaced-repetition flashcards.',
    source: 'built_in', capabilityId: undefined,
    enabled: false, visible: false, planned: true,
    perspectiveType: 'neutral',
    component: lazy(() => import('./cards/CardReviewPage')),
  },
  {
    id: 'memory', label: 'Memory', path: '/memory',
    section: 'knowledge', group: 'knowledge', icon: 'database',
    description: 'Review scoped memories, visibility, and long-term context.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    hasSubRoutes: true,
    component: lazy(() => import('./memory/MemoryModule')),
  },

  // ── Agents (execution & infrastructure) ─────────────────────────────────────
  {
    id: 'instance_settings', label: 'Instance Settings', path: '/instance-settings',
    section: 'dev', group: 'system', icon: 'server-cog',
    description: 'Manage server-wide instance configuration.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: false, planned: false,
    perspectiveType: 'neutral',
    component: lazy(() => import('./instance_settings/InstanceSettingsPage')),
  },
  {
    id: 'runtime_tools', label: 'Runtime Tools', path: '/runtime-tools',
    section: 'dev', group: 'system', icon: 'terminal',
    description: 'Install and update server-wide CLI runtime tools.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: false, planned: false,
    perspectiveType: 'neutral',
    component: lazy(() => import('./runtime_tools/RuntimeToolsPage')),
  },
  {
    id: 'cli_profiles', label: 'CLI Profiles', path: '/cli-profiles',
    section: 'dev', group: 'system', icon: 'terminal',
    description: 'Manage personal CLI login profiles and space grants.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'neutral',
    component: lazy(() => import('./cli_profiles/CliProfilesPage')),
  },
  {
    id: 'job_queue', label: 'Job Queue', path: '/jobs',
    section: 'agents', group: 'agents', icon: 'list-checks',
    description: 'Inspect infrastructure jobs, retries, and worker status.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    component: lazy(() => import('./job_queue/JobQueuePage')),
  },
  {
    id: 'evolution', label: 'Evolution', path: '/evolution',
    section: 'agents', group: 'agents', icon: 'git-branch',
    description: 'Review evolution targets, signals, runs, proposals, and validation metrics.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'neutral',
    component: lazy(() => import('./evolution/EvolutionPage')),
  },

  // ── Workspace ─────────────────────────────────────────────────────────────
  {
    id: 'workspaces', label: 'Workspaces', path: '/workspaces',
    section: 'agents', group: 'workspace', icon: 'folder', accent: true,
    description: 'Browse files, diffs, runs, artifacts, and workspace status.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    component: lazy(() => import('./workspaces/WorkspacesPage')),
  },
  {
    id: 'workspace_console', label: 'Console', path: '/workspace-console',
    section: 'agents', group: 'workspace', icon: 'terminal',
    description: 'Browse project files, inspect git changes, and run agent sessions.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    component: lazy(() => import('./workspace_console/WorkspaceConsolePage')),
  },

  // ── System ────────────────────────────────────────────────────────────────
  {
    id: 'settings', label: 'Settings', path: '/settings',
    section: 'dev', group: 'system', icon: 'settings', accent: true,
    description: 'Configure personal credentials, spaces, and preferences.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'neutral',
    component: lazy(() => import('./settings/SettingsPage')),
  },
  {
    id: 'space_settings', label: 'Space Settings', path: '/space-settings',
    section: 'dev', group: 'system', icon: 'settings',
    description: 'Manage members and space-level network settings.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: false, planned: false,
    perspectiveType: 'space-scoped',
    component: lazy(() => import('./space_settings/SpaceSettingsPage')),
  },
  {
    id: 'capabilities', label: 'Capabilities', path: '/capabilities',
    section: 'agents', group: 'system', icon: 'zap',
    description: 'Browse registered capability manifests and permissions.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    component: lazy(() => import('./capabilities/CapabilitiesPage')),
  },
  {
    id: 'agents_mgmt', label: 'Agents', path: '/agents',
    section: 'agents', group: 'agents', icon: 'bot',
    description: 'Create agents and configure default model providers.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    hasSubRoutes: true,
    component: lazy(() => import('./agents/AgentsModule')),
  },
  {
    id: 'providers', label: 'Providers', path: '/providers',
    section: 'dev', group: 'system', icon: 'key',
    description: 'Configure API keys for LLM model providers.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    component: lazy(() => import('./providers/ModelProvidersPage')),
  },
  {
    id: 'network_profiles', label: 'Network', path: '/network-profiles',
    section: 'dev', group: 'system', icon: 'globe',
    description: 'Configure direct and proxy routing profiles for providers and CLI runtimes.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: false, planned: false,
    perspectiveType: 'space-scoped',
    component: lazy(() => import('./network_profiles/NetworkProfilesPage')),
  },
  {
    id: 'automations', label: 'Automations', path: '/automations',
    section: 'agents', group: 'agents', icon: 'clock',
    description: 'Schedule agents to run on a cron, or trigger them manually.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    component: lazy(() => import('./automations/AutomationsPage')),
  },
  {
    id: 'context', label: 'Context Preview', path: '/context',
    section: 'dev', group: 'system', icon: 'code',
    description: 'Preview the assembled context package for a space.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    perspectiveType: 'space-scoped',
    component: lazy(() => import('./memory/ContextPreviewPage')),
  },
]

/**
 * Find the registered module that owns a path (used for route metadata lookups).
 * Navigation tiers live in `src/core/navigation.tsx`; the home/space scope split lives in
 * `routeScopeForPath`. The old "perspective" path classifier has been removed.
 */
export function moduleForPath(pathname: string): Module | undefined {
  return MODULE_REGISTRY.find(module => {
    if (pathname === module.path) return true
    return module.hasSubRoutes && pathname.startsWith(`${module.path}/`)
  })
}
