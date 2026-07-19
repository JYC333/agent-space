# Shared Reader

The Reader is an independent document interaction domain. It owns generic
document payloads, selection anchors, highlights, comments, bookmarks, comment
threads, keyboard behavior, and the inspector. It does not own source ingestion
or Project Research synthesis.

The server entry points are `/api/v1/reader/*`. Document resolvers are supplied
by Sources for `source_item` and `source_snapshot`, and by Project Research for
`research_report`. Every resolver applies its domain permission checks before
returning content. Research reference resolution additionally applies source
consent and returns only `unavailable` for inaccessible references.

`reader_annotations` targets `document_type + document_id`; supported types are
`source_item`, `source_snapshot`, and `research_report`. Annotation visibility,
ownership, and document access are checked independently. Artifact annotations
and `/api/v1/sources/reader/*` do not exist.

The frontend `ReaderWorkspace` owns the document canvas, annotation layer,
selection toolbar, inspector, comment threads, shortcuts, and interaction
states. Library and Project Research are thin wrappers that supply their own
navigation, metadata, and domain actions.
