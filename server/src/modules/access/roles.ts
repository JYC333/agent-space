export type SpaceRole = "owner" | "admin" | "reviewer" | "member" | "guest";

export function isKnownSpaceRole(value: string | null | undefined): value is SpaceRole {
  return value === "owner" || value === "admin" || value === "reviewer" || value === "member" || value === "guest";
}

export function isSpaceOwnerOrAdmin(role: string | null | undefined): boolean {
  return role === "owner" || role === "admin";
}
