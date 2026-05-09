# agent.echo

A development/testing capability that echoes inputs back without side effects.

## Use cases

- Verify context builder output
- Test session → agent run flow
- Debug memory injection
- Confirm run logging works

## Behavior

Accepts any prompt and context, returns them formatted as output.
Does not write memory. Does not call external APIs.
