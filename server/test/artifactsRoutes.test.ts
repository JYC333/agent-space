import { afterEach, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import {
  __setArtifactIdentityForTests,
  __setArtifactRepositoryFactoryForTests,
} from "../src/modules/artifacts";
import {
  ArtifactNotExportableError,
  PgArtifactRepository,
  type ArtifactOut,
  type ArtifactPage,
} from "../src/modules/artifacts/repository";

let app: FastifyInstance;

afterEach(async () => {
  __setArtifactIdentityForTests(null);
  __setArtifactRepositoryFactoryForTests(null);
  await app?.close();
});

function config() {
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
  });
}

function artifact(overrides: Partial<ArtifactOut> = {}): ArtifactOut {
  return {
    id: "artifact-1",
    space_id: "space-1",
    run_id: "run-1",
    proposal_id: null,
    artifact_type: "summary",
    title: "Summary",
    mime_type: "text/plain",
    exportable: true,
    preview: false,
    storage_ref: null,
    storage_path: null,
    metadata_json: null,
    has_inline_content: true,
    visibility: "space_shared",
    owner_user_id: null,
    content: null,
    created_at: "2026-06-16T10:00:00.000Z",
    updated_at: "2026-06-16T10:00:00.000Z",
    project_id: null,
    ...overrides,
  };
}

describe("artifact routes", () => {
  it("lists and reads artifacts with public response shapes", async () => {
    __setArtifactIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    __setArtifactRepositoryFactoryForTests(() => ({
      async listVisible(spaceId, userId, filters) {
        return {
          items: [
            artifact({
              id: `${spaceId}:${userId}:${filters.artifactType ?? "all"}`,
            }),
          ],
          total: 1,
          limit: filters.limit,
          offset: filters.offset,
        } satisfies ArtifactPage;
      },
      async getVisible(_spaceId, _userId, artifactId, includeContent) {
        return artifact({ id: artifactId, content: includeContent ? "inline" : null });
      },
      async exportVisible() {
        throw new Error("export should not run");
      },
    }));
    app = buildServer(config(), { logger: false });

    const list = await app.inject({
      method: "GET",
      url: "/api/v1/artifacts?limit=25&offset=5&artifact_type=summary",
    });
    const get = await app.inject({ method: "GET", url: "/api/v1/artifacts/artifact-1" });

    expect(list.statusCode).toBe(200);
    expect(list.json()).toMatchObject({
      items: [{ id: "space-1:user-1:summary" }],
      total: 1,
      limit: 25,
      offset: 5,
    });
    expect(get.statusCode).toBe(200);
    expect(get.json()).toMatchObject({ id: "artifact-1", content: "inline" });
  });

  it("exports inline artifact content with an attachment disposition", async () => {
    __setArtifactIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    __setArtifactRepositoryFactoryForTests(() => ({
      async listVisible() {
        throw new Error("list should not run");
      },
      async getVisible() {
        throw new Error("get should not run");
      },
      async exportVisible(_spaceId, _userId, artifactId) {
        return {
          artifact: artifact({ id: artifactId, content: "download" }),
          filename: "Summary",
          mediaType: "text/plain",
          body: Buffer.from("download", "utf8"),
        };
      },
    }));
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/artifacts/artifact-1/export",
    });

    expect(res.statusCode).toBe(200);
    expect(res.headers["content-disposition"]).toBe('attachment; filename="Summary"');
    expect(res.payload).toBe("download");
  });

  it("rejects path traversal, absolute paths, null bytes, and sandbox paths in file-backed export", async () => {
    const baseRow = {
      id: "art-1",
      space_id: "space-1",
      run_id: null,
      proposal_id: null,
      artifact_type: "file",
      title: "Export Me",
      content: null,
      storage_ref: null,
      storage_path: "TBD",
      mime_type: "application/octet-stream",
      exportable: true,
      preview: false,
      metadata_json: null,
      visibility: "space_shared",
      owner_user_id: null,
      created_at: new Date("2026-06-16"),
      updated_at: new Date("2026-06-16"),
      project_id: null,
    };
    const config = {
      artifactStorageRoot: "/tmp/artifacts",
      sandboxRoot: "/tmp/artifacts/sandbox",
    };
    const badPaths = [
      "../../etc/passwd",        // path traversal
      "/absolute/path/file.txt", // absolute path
      "sub\0null",               // null byte
      "sandbox/secret.txt",      // resolves inside sandboxRoot
    ];
    for (const storagePath of badPaths) {
      const fakeDb = {
        query: async () => ({ rows: [{ ...baseRow, storage_path: storagePath }], rowCount: 1 }),
      };
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const repo = new PgArtifactRepository(fakeDb as any, config);
      await expect(
        repo.exportVisible("space-1", "user-1", "art-1"),
      ).rejects.toBeInstanceOf(ArtifactNotExportableError);
    }
  });
});
