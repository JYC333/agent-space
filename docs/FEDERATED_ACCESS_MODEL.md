# Federated Access Model (Deferred)

Multi-deployment federation is not implemented. The application has no remote
pointer, remote fetch, synchronization, distributed identity, or cross-instance
authorization API.

Local cross-Space transfer uses targeted immutable publications documented in
`docs/CONTENT_PUBLICATIONS.md`. That mechanism copies a snapshot into an explicit
target Space and cannot be used to read the live source resource.

Any future federation design must define distributed identity, origin-side
authorization, target-side validation, revocation, audit, cache policy, and
credential isolation. It must not reuse content visibility or create a direct
cross-Space read path.
