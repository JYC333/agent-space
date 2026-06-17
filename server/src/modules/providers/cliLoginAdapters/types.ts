import type { LoginRuntimeConfig } from "../cliLoginEngine";

export interface CliLoginAdapter extends LoginRuntimeConfig {
  runtime: string;
  target_path: string;
}
