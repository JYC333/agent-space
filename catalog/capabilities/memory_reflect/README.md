# memory.reflect

A built-in capability that analyzes session messages and generates memory proposals for user review.

## How it works

1. Session messages are sent to the reflector
2. The reflector analyzes user messages for memory-worthy content
3. Structured proposals are generated (but not written to memory directly)
4. The user reviews and accepts or rejects each proposal
5. Accepted proposals become active long-term memories

## Capability Runtime

This catalog entry is metadata only; it ships no executable entrypoint. The TS
session reflection API owns the pattern/LLM proposal flow.

## Memory Access

- **Read**: user preferences, semantics, episodic; system policy
- **Write**: proposals only (user must approve before anything is written)
