import type { LoginRuntimeConfig } from "../loginEngine";

export interface CliLoginAdapter extends LoginRuntimeConfig {
  runtime: string;
  target_path: string;
}
