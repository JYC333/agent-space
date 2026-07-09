export function sourceItemReadableClause(itemAlias: string, userParam: string, libraryOnly: boolean): string {
  return `(
    (${itemAlias}.connection_id IS NULL AND ${itemAlias}.created_by_user_id = ${userParam})
    OR EXISTS (
      SELECT 1
        FROM source_connection_user_subscriptions scus_read
       WHERE scus_read.space_id = ${itemAlias}.space_id
         AND scus_read.source_connection_id = ${itemAlias}.connection_id
         AND scus_read.user_id = ${userParam}
         AND scus_read.status = 'subscribed'
         ${libraryOnly ? "AND scus_read.library_enabled = true" : ""}
    )
  )`;
}
