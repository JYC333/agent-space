import type { CliLoginAdapter } from "./types";

export const claudeCodeLoginAdapter: CliLoginAdapter = {
  runtime: "claude_code",
  method: "cli",
  command: ["claude", "/login"],
  home_subdir: ".claude",
  // `claude /login` exits non-zero from its REPL; the credential file is the
  // reliable success signal the sync step keys on.
  credential_file: ".credentials.json",
  label: "Claude Code",
  target_path: "/home/agent/.claude",
  hint_cli: "A browser URL will appear - open it to authorize your Claude.ai account.",
};
