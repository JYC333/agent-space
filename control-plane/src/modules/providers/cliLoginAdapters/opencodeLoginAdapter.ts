import type { CliLoginAdapter } from "./types";

export const opencodeLoginAdapter: CliLoginAdapter = {
  runtime: "opencode",
  method: "cli",
  command: ["opencode", "auth", "login"],
  home_subdir: ".opencode",
  label: "OpenCode",
  target_path: "/home/agent/.opencode",
  hint_cli: "Follow the prompts to complete login.",
};
