import { describe, expect, it } from "vitest";
import type { ProviderItem } from "../api/client";
import { skillIdsVisibleInComposer } from "./skillMentionPolicy";

function provider({ supportsSkills = true, plainHosted = false } = {}): ProviderItem {
  return {
    provider_id: plainHosted ? "hosted" : "codex",
    label: plainHosted ? "Hosted" : "Codex",
    description: "test provider",
    kind: plainHosted ? "hosted_api" : "local_cli",
    provider_role: plainHosted ? "model_provider" : "runtime_engine",
    status: "active",
    default_model_family: null,
    capabilities: { supports_skills: supportsSkills },
    agentic_effective_capabilities: plainHosted ? null : {
      status: supportsSkills ? "active" : "blocked",
      reason_code: supportsSkills ? null : "agentic_skill_catalog_not_effective",
      snapshot_digest: "fixture-capability-snapshot",
      capabilities: {
        streaming: true,
        tool_orchestration: true,
        cli: true,
        mcp: true,
        skill_catalog: supportsSkills,
        filesystem_list: true,
        filesystem_read: true,
        filesystem_write: true,
        shell: true,
        interrupt: true,
        same_turn_steering: true,
        recovery: true,
        confirmation_resume: true,
        provider_private_state: false,
        attachment_modalities: ["file"],
        app_references: true,
        confirmations: true,
      },
    },
  };
}

describe("skill mention policy", () => {
  it("hides skills for plain hosted providers and providers without skill support", () => {
    const skillIds = ["storage-ops", "crm-search"];

    expect(skillIdsVisibleInComposer({
      activationMode: "explicit",
      availableSkillIds: skillIds,
      provider: provider({ plainHosted: true }),
    })).toEqual([]);
    expect(skillIdsVisibleInComposer({
      activationMode: "explicit",
      availableSkillIds: skillIds,
      provider: provider({ supportsSkills: false }),
    })).toEqual([]);
  });

  it("filters explicit skill mentions through the session or agent allowlist", () => {
    expect(skillIdsVisibleInComposer({
      activationMode: "explicit",
      allowedSkillIds: ["crm-search"],
      availableSkillIds: ["storage-ops", "crm-search"],
      provider: provider(),
    })).toEqual(["crm-search"]);
  });

  it("fails closed for every agentic runtime without a server snapshot", () => {
    const codex = provider();
    codex.agentic_effective_capabilities = null;
    const remote = { ...codex, provider_id: "hosted-agentic" };

    expect(skillIdsVisibleInComposer({
      activationMode: "explicit",
      availableSkillIds: ["storage-ops"],
      provider: codex,
    })).toEqual([]);
    expect(skillIdsVisibleInComposer({
      activationMode: "explicit",
      availableSkillIds: ["storage-ops"],
      provider: remote,
    })).toEqual([]);
  });

  it("treats an empty allowlist as all skills but hides implicit sessions", () => {
    const skillIds = ["storage-ops", "crm-search"];

    expect(skillIdsVisibleInComposer({
      activationMode: "explicit",
      allowedSkillIds: [],
      availableSkillIds: skillIds,
      provider: provider(),
    })).toEqual(skillIds);
    expect(skillIdsVisibleInComposer({
      activationMode: "implicit",
      allowedSkillIds: [],
      availableSkillIds: skillIds,
      provider: provider(),
    })).toEqual([]);
  });

  it("fails closed until a source app advertises structured skill invocation", () => {
    const base = {
      activationMode: "explicit" as const,
      availableSkillIds: ["storage-ops"],
      provider: provider(),
      sourceAppId: "design-studio",
    };

    expect(skillIdsVisibleInComposer(base)).toEqual([]);
    expect(skillIdsVisibleInComposer({ ...base, sourceAppSupportsSkillInvocations: true })).toEqual(["storage-ops"]);
  });
});
