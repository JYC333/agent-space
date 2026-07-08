import { customType } from "drizzle-orm/pg-core";

// Mirrors the `retrieval_object_type` Postgres DOMAIN declared in
// server/migrations/0001_baseline.sql (a closed varchar(64) enum enforced by
// a CHECK constraint). drizzle-kit's introspection can't parse DOMAIN types,
// so this customType only needs to report the domain's own SQL type name —
// the DOMAIN definition and its CHECK constraint stay baseline-owned and are
// not declared here.
export const retrievalObjectType = customType<{ data: string }>({
  dataType() {
    return "retrieval_object_type";
  },
});

// tsvector full-text search column (retrieval_chunks.tsv). Not a pgvector
// type — plain Postgres full-text search, which drizzle-orm/pg-core has no
// built-in helper for.
export const tsVector = customType<{ data: string }>({
  dataType() {
    return "tsvector";
  },
});

// retrieval_chunks.embedding is a deliberately unconstrained pgvector
// column (no fixed dimension — see the ck_retrieval_chunks_embedding_dimensions
// CHECK in 0001_baseline.sql, which ties embedding_dimensions to
// vector_dims(embedding) per row). drizzle-orm's built-in vector() helper
// always emits a fixed `vector(N)`, so it can't represent this column
// without producing a spurious ALTER COLUMN TYPE diff.
export const pgVector = customType<{ data: number[] }>({
  dataType() {
    return "vector";
  },
});
