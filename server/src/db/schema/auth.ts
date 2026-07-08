import { pgTable, index, uniqueIndex, unique, foreignKey, varchar, text, timestamp, type PgTableExtraConfigValue } from "drizzle-orm/pg-core";

export const users = pgTable("users", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	email: varchar({ length: 256 }),
	displayName: varchar("display_name", { length: 256 }).notNull(),
	avatarUrl: text("avatar_url"),
	status: varchar({ length: 32 }).notNull(),
	lastLoginAt: timestamp("last_login_at", { withTimezone: true, mode: 'string' }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	uniqueIndex("ix_users_email").using("btree", table.email.asc().nullsLast()),
	index("ix_users_status").using("btree", table.status.asc().nullsLast()),
]);

export const authAccounts = pgTable("auth_accounts", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	userId: varchar("user_id", { length: 36 }).notNull(),
	provider: varchar({ length: 32 }).notNull(),
	providerUserId: varchar("provider_user_id", { length: 256 }).notNull(),
	email: varchar({ length: 256 }).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_auth_accounts_user_id").using("btree", table.userId.asc().nullsLast()),
	foreignKey({
			columns: [table.userId],
			foreignColumns: [users.id],
			name: "auth_accounts_user_id_fkey"
		}),
	unique("uq_auth_accounts_provider_user").on(table.provider, table.providerUserId),
]);

export const userSessions = pgTable("user_sessions", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	userId: varchar("user_id", { length: 36 }).notNull(),
	tokenHash: varchar("token_hash", { length: 128 }).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	expiresAt: timestamp("expires_at", { withTimezone: true, mode: 'string' }).notNull(),
	lastSeenAt: timestamp("last_seen_at", { withTimezone: true, mode: 'string' }),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_user_sessions_user_id").using("btree", table.userId.asc().nullsLast()),
	foreignKey({
			columns: [table.userId],
			foreignColumns: [users.id],
			name: "user_sessions_user_id_fkey"
		}),
	unique("user_sessions_token_hash_key").on(table.tokenHash),
]);
