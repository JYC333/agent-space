import { PgJobQueueRepository } from "../jobs/repository";
import { RetrievalProjectionService } from "../retrieval";
import { enqueueRetrievalEmbeddingBackfillWithQueue } from "../retrieval/embedding/job";
import type { Queryable } from "../routeUtils/common";
import { intakeRetrievalRegistry } from "./retrievalAdapter";

export async function reindexIntakeItemAndEvidenceForRetrieval(
  db: Queryable,
  input: { spaceId: string; itemId: string; trigger: string },
): Promise<void> {
  const projection = new RetrievalProjectionService(db, intakeRetrievalRegistry);
  await projection.reindex(input.spaceId, "intake_item", input.itemId);
  for (const evidenceId of await evidenceIdsForItem(db, input.spaceId, input.itemId)) {
    await projection.reindex(input.spaceId, "extracted_evidence", evidenceId);
  }
  await enqueueIntakeRetrievalEmbeddings(db, input.spaceId, input.trigger);
}

export async function reindexExtractedEvidenceAndParentForRetrieval(
  db: Queryable,
  input: { spaceId: string; evidenceId: string; trigger: string },
): Promise<void> {
  const projection = new RetrievalProjectionService(db, intakeRetrievalRegistry);
  await projection.reindex(input.spaceId, "extracted_evidence", input.evidenceId);
  const itemId = await intakeItemIdForEvidence(db, input.spaceId, input.evidenceId);
  if (itemId) await projection.reindex(input.spaceId, "intake_item", itemId);
  await enqueueIntakeRetrievalEmbeddings(db, input.spaceId, input.trigger);
}

export async function enqueueIntakeRetrievalEmbeddings(
  db: Queryable,
  spaceId: string,
  trigger: string,
): Promise<void> {
  await enqueueRetrievalEmbeddingBackfillWithQueue(new PgJobQueueRepository(db), {
    spaceId,
    userId: null,
    trigger,
  }).catch((error) => {
    process.stderr.write(
      `[intake.retrieval] embedding backfill enqueue failed: ${String((error as Error)?.message ?? error)}\n`,
    );
    return null;
  });
}

async function evidenceIdsForItem(db: Queryable, spaceId: string, itemId: string): Promise<string[]> {
  const result = await db.query<{ id: string }>(
    `SELECT id
       FROM extracted_evidence
      WHERE space_id = $1
        AND intake_item_id = $2
        AND deleted_at IS NULL`,
    [spaceId, itemId],
  );
  return result.rows.map((row) => row.id);
}

async function intakeItemIdForEvidence(db: Queryable, spaceId: string, evidenceId: string): Promise<string | null> {
  const result = await db.query<{ intake_item_id: string | null }>(
    `SELECT intake_item_id
       FROM extracted_evidence
      WHERE space_id = $1 AND id = $2
      LIMIT 1`,
    [spaceId, evidenceId],
  );
  return result.rows[0]?.intake_item_id ?? null;
}
