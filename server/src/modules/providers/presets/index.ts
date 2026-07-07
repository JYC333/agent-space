import { COHERE_PRESETS } from "./cohere";
import { MINIMAX_PRESETS } from "./minimax";
import { OLLAMA_PRESETS } from "./ollama";
import { OPENAI_PRESETS } from "./openai";
import { ZEROENTROPY_PRESETS } from "./zeroentropy";
import type { ProviderPreset } from "./types";

export const PROVIDER_PRESETS: ProviderPreset[] = [
  ...OPENAI_PRESETS,
  ...COHERE_PRESETS,
  ...ZEROENTROPY_PRESETS,
  ...OLLAMA_PRESETS,
  ...MINIMAX_PRESETS,
];

export function listProviderPresets(): ProviderPreset[] {
  return PROVIDER_PRESETS.map((preset) => ({ ...preset }));
}

export function providerPresetById(id: string): ProviderPreset | null {
  const preset = PROVIDER_PRESETS.find((candidate) => candidate.id === id);
  return preset ? { ...preset } : null;
}

export type { ProviderPreset, ProviderPresetMode } from "./types";

