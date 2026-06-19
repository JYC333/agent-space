import type { OfficialPluginDescriptor } from "@agent-space/protocol" with { "resolution-mode": "import" };

export const DAIRY_PLUGIN_ID = "dairy";
export const DAIRY_PLUGIN_VERSION = "0.1.0";

/**
 * dairy — official optional module descriptor.
 *
 * This descriptor is pure metadata for the official plugin control plane.
 * Runtime behavior lives in the package under `plugins/official/dairy/` and is
 * loaded from the compiled official plugin artifact at server startup.
 * Memory/context extraction remains opt-in and must go through proposal/intake
 * boundaries; normal dairy editing writes the plugin-owned diary tables
 * directly.
 */
export const dairyDescriptor: OfficialPluginDescriptor = {
  id: DAIRY_PLUGIN_ID,
  name: "Dairy",
  description:
    "A personal diary that shows entries from the same day across multiple years. Supports AI reflection, daily reminders, and opt-in memory proposals.",
  version: DAIRY_PLUGIN_VERSION,
  category: "personal",
  default_enabled: false,
  default_visible: true,
  scope: "user",
  lifecycle_status: "available",
  frontend_entries: [
    {
      module_id: "dairy",
      label: "Dairy",
      path: "/dairy",
      icon: "book",
      section: "capture",
      group: "daily",
    },
  ],
  backend_feature_ids: ["dairy_entries", "dairy_reflections"],
  permissions: {
    creates_activity: false,
    can_propose_memory: true,
    can_contribute_context: "opt_in",
    uses_ai: true,
    uses_scheduler: true,
  },
  settings_defaults: {
    daily_reminder_enabled: false,
    ai_reflection_enabled: false,
    memory_proposal_enabled: false,
    include_in_context: false,
    default_visibility: "private",
  },
};
