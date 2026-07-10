import { contentReadSql } from "../access/contentAccessSql";

export function sourceItemReadableClause(itemAlias: string, userParam: string, libraryOnly: boolean): string {
  return `(
    ${contentReadSql("source_item", itemAlias, userParam)}
    AND ${sourceItemConnectionGateClause(itemAlias, userParam, libraryOnly)}
  )`;
}

export function sourceItemConnectionGateClause(itemAlias: string, userParam: string, libraryOnly: boolean): string {
  return `(
    ${itemAlias}.connection_id IS NULL
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
