# memory.reflect

A built-in capability that analyzes session messages and generates memory proposals for user review.

## How it works

1. Session messages are sent to the reflector
2. The reflector analyzes user messages for memory-worthy content
3. Structured proposals are generated (but not written to memory directly)
4. The user reviews and accepts or rejects each proposal
5. Accepted proposals become active long-term memories

## Modes

- **placeholder** (default): pattern-matching, no API key needed
- **llm**: uses Claude to produce higher-quality proposals (requires `ANTHROPIC_API_KEY`)

Set `REFLECTOR_MODE=llm` in your `.env` to enable LLM mode.

## Memory Access

- **Read**: user preferences, semantics, episodic; system policy
- **Write**: proposals only (user must approve before anything is written)
