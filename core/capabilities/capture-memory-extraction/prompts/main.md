# Capture Memory Extraction

<!-- block_id: memory-classification -->
Classify capture content as one of: exploration, accepted_decision, stable_preference, rejected_option, unresolved_question.

<!-- rule_id: activity-first -->
Raw capture is Activity first. Do not create active Memory directly from capture.

<!-- rule_id: proposal-first -->
Memory create, update, and archive operations must be represented as proposals before activation.

<!-- rule_id: stable-preference-threshold -->
Stable preferences require repeated confirmation or an accepted proposal outcome.

<!-- rule_id: uncertainty -->
Conflicting or uncertain items should be marked unresolved rather than promoted.

<!-- block_id: write-boundary -->
Do not directly mutate memory, prompts, capabilities, policies, files, or code.

<!-- block_id: examples -->
Example input: "Maybe we should use SQLite for this prototype, but I am not sure."
Expected output: unresolved_question; no active memory; proposal only if the user accepts it later.

