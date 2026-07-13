# Runtime and Extension Glossary

This glossary records the vocabulary used by the execution, capability, and
workflow layers. It is a naming boundary, not a code-renaming plan.

| Term | Meaning and ownership |
|---|---|
| **RuntimeBinary** | A versioned executable installed and governed by `runtimeTools`. It is the physical CLI binary, not the adapter that invokes it. |
| **RuntimeAdapter** | The server-side execution implementation that turns a run into a managed API or local process invocation and materializes its result. Owned by `runs` and `runtimeAdapters`. |
| **RuntimeAdapterSpec** | The declarative catalog entry describing an adapter's executor family, invocation, credentials, sandbox, model, permissions, output, limits, and conservative runtime capability claims. The catalog is the source for adapter capabilities and dispatch selection. |
| **RuntimeExtension** | A future, separately governed extension point that augments a runtime with tools or protocol support. It is not synonymous with a runtime adapter or a product plugin. |
| **RuntimeToolBinding** | A binding that exposes a server-owned tool/action to a runtime under policy and capability checks. A binding grants exposure; it does not grant authorization by itself. |
| **RuntimeSkillBinding** | A binding that maps a canonical agent-space capability or imported skill to runtime-specific generated instructions or files. Generated files are adapter inputs, not source of truth. |
| **ProductPlugin** | An optional product module with its own module lifecycle and UI/backend surface. It is distinct from a runtime extension, skill package, or CLI binary. |
| **Open Skill** | Untrusted external skill source material that can be imported, normalized, reviewed, and converted into a capability candidate. It is never an implicit runtime permission grant. |

## Deliberate non-equivalences

- A RuntimeBinary is installed infrastructure; a RuntimeAdapter is server
  execution policy and lifecycle; a RuntimeAdapterSpec is its declaration.
- A RuntimeToolBinding and RuntimeSkillBinding are different: the former
  concerns callable tool exposure, while the latter concerns generated
  runtime instructions.
- A ProductPlugin is a product module. It must not be used as a catch-all name
  for a runtime, skill, tool, or adapter.

No source rename is implied by this document. New code should use the terms
above, and existing names should change only as part of an explicitly scoped
refactor.
