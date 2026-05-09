import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

export type NavSection = 'capture' | 'knowledge' | 'agents' | 'dev'
export type AppGroup   = 'daily' | 'knowledge' | 'agents' | 'workspace' | 'system'

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
  section: NavSection   // kept for backward compat

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
   * - false → card is hidden (e.g. deprecated capability, space policy).
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
    description: 'Daily overview, active items, and suggested actions.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    component: lazy(() => import('./today/TodayPage')),
  },
  {
    id: 'capture', label: 'Capture', path: '/capture',
    section: 'capture', group: 'daily', icon: 'plus',
    description: 'Quickly save thoughts, ideas, notes, and external content.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    component: lazy(() => import('./capture/CapturePage')),
  },
  {
    id: 'activity', label: 'Activity', path: '/activity',
    section: 'capture', group: 'daily', icon: 'inbox',
    description: 'Review raw captured records before they become proposals.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    component: lazy(() => import('./activity/ActivityInboxPage')),
  },
  {
    id: 'sessions', label: 'Sessions', path: '/sessions',
    section: 'capture', group: 'daily', icon: 'message-square',
    description: 'Manage and continue agent sessions and conversations.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    component: lazy(() => import('./sessions/SessionsPage')),
  },
  {
    id: 'time', label: 'Time', path: '/time',
    section: 'capture', group: 'daily', icon: 'clock',
    description: 'Track time records and convert them into activity summaries.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: true,
    component: lazy(() => import('./time/TimePage')),
  },

  // ── Knowledge ─────────────────────────────────────────────────────────────
  {
    id: 'wiki', label: 'LLM Wiki', path: '/wiki',
    section: 'knowledge', group: 'knowledge', icon: 'book-open', accent: true,
    description: 'Structured knowledge — concepts, claims, sources, questions.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: true,
    component: lazy(() => import('./wiki/WikiPage')),
  },
  {
    id: 'cards', label: 'Cards', path: '/cards',
    section: 'knowledge', group: 'knowledge', icon: 'layers',
    description: 'Review and manage spaced-repetition flashcards.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: true,
    component: lazy(() => import('./cards/CardReviewPage')),
  },
  {
    id: 'memory', label: 'Memory', path: '/memory',
    section: 'knowledge', group: 'knowledge', icon: 'database',
    description: 'Browse and manage scoped long-term memory records.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    component: lazy(() => import('./memory/MemoriesPage')),
  },

  // ── Agents ────────────────────────────────────────────────────────────────
  {
    id: 'runs', label: 'Agents', path: '/runs',
    section: 'agents', group: 'agents', icon: 'cpu', accent: true,
    description: 'Manage agent profiles, roles, tools, permissions, and runtimes.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    component: lazy(() => import('./agents/AgentRunsPage')),
  },
  {
    id: 'proposals', label: 'Proposals', path: '/proposals',
    section: 'knowledge', group: 'agents', icon: 'check-circle',
    description: 'Review memory, wiki, card, code, and system proposals.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    component: lazy(() => import('./memory/ProposalsPage')),
  },
  {
    id: 'cli_adapters', label: 'Runtime', path: '/cli-tools',
    section: 'agents', group: 'agents', icon: 'activity',
    description: 'Monitor CLI adapters, queues, sandboxes, and server state.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    component: lazy(() => import('./cli_adapters/CLIStatusPage')),
  },
  {
    id: 'job_queue', label: 'Job Queue', path: '/jobs',
    section: 'agents', group: 'agents', icon: 'list-checks',
    description: 'Inspect durable background jobs — status, events, retries, and cancellation.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    component: lazy(() => import('./job_queue/JobQueuePage')),
  },

  // ── Workspace ─────────────────────────────────────────────────────────────
  {
    id: 'workspaces', label: 'Workspaces', path: '/workspaces',
    section: 'agents', group: 'workspace', icon: 'folder', accent: true,
    description: 'Browse files, diffs, runs, artifacts, and workspace status.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    component: lazy(() => import('./workspaces/WorkspacesPage')),
  },
  {
    id: 'workspace_console', label: 'Console', path: '/workspace-console',
    section: 'agents', group: 'workspace', icon: 'terminal',
    description: 'Browse project files, inspect git changes, and run agent sessions.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    component: lazy(() => import('./workspace_console/WorkspaceConsolePage')),
  },

  // ── System ────────────────────────────────────────────────────────────────
  {
    id: 'settings', label: 'Settings', path: '/settings',
    section: 'dev', group: 'system', icon: 'settings', accent: true,
    description: 'Configure spaces, users, capabilities, memory, and policies.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    component: lazy(() => import('./settings/SettingsPage')),
  },
  {
    id: 'capabilities', label: 'Capabilities', path: '/capabilities',
    section: 'agents', group: 'system', icon: 'zap',
    description: 'Browse registered capability manifests and permissions.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    component: lazy(() => import('./capabilities/CapabilitiesPage')),
  },
  {
    id: 'context', label: 'Context Preview', path: '/context',
    section: 'dev', group: 'system', icon: 'code',
    description: 'Preview the assembled context package for a space.',
    source: 'built_in', capabilityId: undefined,
    enabled: true, visible: true, planned: false,
    component: lazy(() => import('./memory/ContextPreviewPage')),
  },
]

export const APP_GROUPS: { label: string; key: AppGroup }[] = [
  { label: 'Daily',     key: 'daily'     },
  { label: 'Knowledge', key: 'knowledge' },
  { label: 'Agents',    key: 'agents'    },
  { label: 'Workspace', key: 'workspace' },
  { label: 'System',    key: 'system'    },
]
