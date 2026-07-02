export const SETTINGS_KEYS = {
  assistantDefault: "agent.default_assistant.settings",
  customSourceInstanceRunner: "intake.custom_source.runner",
  customSourceSpacePolicy: "intake.custom_source.space_policy",
  dailyCaptureReport: "daily_capture_report.settings",
  retrievalSpace: "retrieval.space.settings",
} as const;

export type SettingsKey = typeof SETTINGS_KEYS[keyof typeof SETTINGS_KEYS];
