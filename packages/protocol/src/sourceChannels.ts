import { z } from "zod";

export const SourceProviderStatusSchema = z.enum(["active", "disabled"]);
export type SourceProviderStatus = z.infer<typeof SourceProviderStatusSchema>;

export const SourceConnectorStatusSchema = z.enum(["active", "disabled"]);
export type SourceConnectorStatus = z.infer<typeof SourceConnectorStatusSchema>;

export const SourceChannelStatusSchema = z.enum(["active", "paused", "archived"]);
export type SourceChannelStatus = z.infer<typeof SourceChannelStatusSchema>;

export const SourceChannelTypeSchema = z.enum(["search", "feed", "web_page", "custom_source"]);
export type SourceChannelType = z.infer<typeof SourceChannelTypeSchema>;

export const SourceFetchFrequencySchema = z.enum(["manual", "hourly", "daily", "weekly"]);
export type SourceFetchFrequency = z.infer<typeof SourceFetchFrequencySchema>;

export const SourceProviderSchema = z.object({
  id: z.string().min(1),
  provider_key: z.string().min(1),
  display_name: z.string().min(1),
  provider_kind: z.enum(["named", "generic"]),
  category: z.string().min(1),
  status: SourceProviderStatusSchema,
  capabilities: z.record(z.unknown()),
  config_schema: z.record(z.unknown()).nullable(),
  setup_schema: z.record(z.unknown()).nullable().optional(),
}).passthrough();
export type SourceProvider = z.infer<typeof SourceProviderSchema>;

export const SourceConnectorSchema = z.object({
  id: z.string().min(1),
  connector_key: z.string().min(1),
  display_name: z.string().min(1),
  connector_type: z.string().min(1),
  ingestion_mode: z.enum(["pull", "manual", "internal"]),
  status: SourceConnectorStatusSchema,
  capabilities: z.record(z.unknown()),
  config_schema: z.record(z.unknown()).nullable(),
}).passthrough();
export type SourceConnector = z.infer<typeof SourceConnectorSchema>;

export const SourceProviderConnectorSchema = z.object({
  id: z.string().min(1),
  provider_id: z.string().min(1),
  connector_id: z.string().min(1),
  status: SourceConnectorStatusSchema,
  priority: z.number().int().nonnegative(),
  capabilities: z.record(z.unknown()),
  config_schema: z.record(z.unknown()).nullable(),
}).passthrough();
export type SourceProviderConnector = z.infer<typeof SourceProviderConnectorSchema>;

export const SourceChannelQuerySchema = z.record(z.unknown());
export type SourceChannelQuery = z.infer<typeof SourceChannelQuerySchema>;

export const SourceChannelCapabilitiesSchema = z.object({
  search: z.boolean().optional(),
  supports_full_history: z.boolean().optional(),
  supports_cursor: z.boolean().optional(),
  supports_conditional_fetch: z.boolean().optional(),
  date_fields: z.array(z.string()).optional(),
  dedupe_keys: z.array(z.string()).optional(),
}).passthrough();
export type SourceChannelCapabilities = z.infer<typeof SourceChannelCapabilitiesSchema>;

export const SourceChannelScanStateSchema = z.object({
  status: z.string().nullable(),
  cursor: z.record(z.unknown()),
  watermark: z.record(z.unknown()),
  next_run_at: z.string().nullable(),
  last_run_at: z.string().nullable(),
}).passthrough();
export type SourceChannelScanState = z.infer<typeof SourceChannelScanStateSchema>;

export const SourceChannelSchema = z.object({
  id: z.string().min(1),
  space_id: z.string().min(1),
  source_connection_id: z.string().min(1),
  source_name: z.string().min(1),
  name: z.string().min(1),
  channel_type: SourceChannelTypeSchema,
  endpoint_url: z.string().url().nullable(),
  query: SourceChannelQuerySchema,
  provider_query: SourceChannelQuerySchema,
  query_fingerprint: z.string().min(1),
  status: SourceChannelStatusSchema,
  fetch_frequency: SourceFetchFrequencySchema,
  schedule_rule: z.record(z.unknown()).nullable(),
  provider: z.object({ key: z.string().min(1), display_name: z.string().min(1) }),
  connection_status: z.string().min(1).nullable(),
  capture_policy: z.string().min(1).nullable(),
  scan_state: SourceChannelScanStateSchema,
}).passthrough();
export type SourceChannel = z.infer<typeof SourceChannelSchema>;

export const SourceChannelCreateRequestSchema = z.object({
  provider_key: z.string().trim().min(1),
  source_name: z.string().trim().min(1).max(512).optional(),
  name: z.string().trim().min(1).max(512).optional(),
  query: SourceChannelQuerySchema,
  endpoint_url: z.string().url().optional(),
  fetch_frequency: SourceFetchFrequencySchema.optional(),
  schedule_rule: z.record(z.unknown()).optional(),
  capture_policy: z.enum(["reference_only", "extract_text", "archive_original"]).optional(),
}).passthrough();
export type SourceChannelCreateRequest = z.infer<typeof SourceChannelCreateRequestSchema>;
