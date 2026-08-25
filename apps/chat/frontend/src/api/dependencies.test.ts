import { afterEach, describe, expect, it, vi } from "vitest";
import { listAgentCatalog } from "./dependencies";

function okJson(payload: unknown): Response {
  return { ok: true, status: 200, json: async () => payload } as Response;
}

describe("agent catalog dependencies", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("preserves compact agent skill allowlists for a new specialized chat", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => okJson({
      workspace_id: "default",
      agent_types: [
        {
          id: "agent-type-storage-specialist",
          name: "Storage specialist",
          description: "Uses one skill.",
          role_id: "storage-specialist",
          skill_ids: ["storage-ops"],
          skill_activation_mode: "explicit",
          enabled: true,
        },
      ],
    })));

    const catalog = await listAgentCatalog("agents");

    expect(catalog.agent_types[0].skill_ids).toEqual(["storage-ops"]);
  });
});
