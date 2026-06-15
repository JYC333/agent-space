import { claudeCodeLoginAdapter } from "./claudeCodeLoginAdapter";
import { codexLoginAdapter } from "./codexLoginAdapter";
import { geminiLoginAdapter } from "./geminiLoginAdapter";
import { opencodeLoginAdapter } from "./opencodeLoginAdapter";
import type { CliLoginAdapter } from "./types";

export type { CliLoginAdapter } from "./types";

export const CLI_LOGIN_ADAPTERS: CliLoginAdapter[] = [
  claudeCodeLoginAdapter,
  codexLoginAdapter,
  opencodeLoginAdapter,
  geminiLoginAdapter,
];

export const CLI_LOGIN_ADAPTERS_BY_RUNTIME: Record<string, CliLoginAdapter> = Object.fromEntries(
  CLI_LOGIN_ADAPTERS.map((adapter) => [adapter.runtime, adapter]),
);

export function cliLoginAdapterFor(runtime: string): CliLoginAdapter | undefined {
  return CLI_LOGIN_ADAPTERS_BY_RUNTIME[runtime];
}
