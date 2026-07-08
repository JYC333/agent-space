import { sourcesApi } from '../../api/client'
import type { ExtractionJob } from '../../types/api'

export async function runPendingItemJob(
  itemId: string,
  jobType: string,
): Promise<ExtractionJob | null> {
  const page = await sourcesApi.jobs({
    source_item_id: itemId,
    job_type: jobType,
    status: 'pending',
    limit: 1,
  })
  const job = page.items[0]
  return job ? sourcesApi.runJob(job.id) : null
}
