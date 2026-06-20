import { expect, test, type Page, type Route, type WebSocketRoute } from "@playwright/test";

type JsonRecord = Record<string, unknown>;

type ChatThread = {
  thread_id: string;
  runtime_session_id: string;
  title: string;
  agent_label: string;
  agent_type_id: string;
  agent_role_id: string;
  source_app_id: string;
  system_prompt: string;
  project_id: string | null;
  archived: boolean;
  availability: string;
  created_at: string;
  updated_at: string;
  last_user_message_at?: string | null;
};

type RuntimeSession = {
  session_id: string;
  workspace_id: string;
  agent_id: string;
  status: string;
  effective_mode: string;
};

type RuntimeTurn = {
  turn_id: string;
  session_id: string;
  workspace_id: string;
  status: string;
  input_text: string | null;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
};

type RuntimeEvent = {
  event_id: string;
  session_id: string;
  turn_id: string | null;
  event_type: string;
  payload: JsonRecord;
  created_at: string;
};

type InterAgentRunDetail = {
  run: JsonRecord;
  participants: JsonRecord[];
  edges: JsonRecord[];
  budget_policy: JsonRecord | null;
  budget_ledger: JsonRecord | null;
  root_runtime_events?: RuntimeEvent[];
  root_runtime_turn?: RuntimeTurn;
};

type InterAgentEvent = {
  event_id: string;
  workspace_id: string;
  run_id: string;
  thread_id: string;
  root_runtime_session_id: string;
  participant_id: string | null;
  runtime_session_id: string | null;
  runtime_turn_id: string | null;
  runtime_event_id: string | null;
  event_type: string;
  visibility_plane: "summary" | "detail" | "debug";
  sequence: number;
  correlation_id: string;
  idempotency_key: string;
  payload: JsonRecord;
  created_at: string;
};

type MockState = {
  createRunBodies: JsonRecord[];
  createSessionBodies: JsonRecord[];
  executeRunBodies: JsonRecord[];
  interAgentSockets: WebSocketRoute[];
  runtimeSessionEvents: Record<string, RuntimeEvent[]>;
  runtimeSessionTurns: Record<string, RuntimeTurn[]>;
  threads: ChatThread[];
  runCreated: boolean;
  runDetail: InterAgentRunDetail;
  runEvents: InterAgentEvent[];
  runArtifacts: JsonRecord[];
};

const NOW = "2026-06-19T10:00:00.000Z";
const WORKSPACE_ID = "default";
const RUNTIME_SESSION_ID = "session-chat-e2e";
const THREAD_ID = RUNTIME_SESSION_ID;
const RUN_ID = "run-chat-e2e";
const RESEARCHER_AGENT_ID = "agent-type-researcher";

test.describe("Chat app browser smoke", () => {
  test("boots the full app shell with composer controls", async ({ page }) => {
    await installChatMocks(page);

    await page.goto("/apps/chat/");

    await expect(page.getByRole("heading", { name: "How can I help today?" })).toBeVisible();
    await expect(page.getByRole("textbox")).toBeEditable();
    await expect(page.getByRole("button", { name: "Send message" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Multi-agent mode: Off" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Agent runner: Default Chat" })).toBeVisible();
  });

  test("sends a normal chat message through runtime session APIs", async ({ page }) => {
    const state = await installChatMocks(page);

    await page.goto("/apps/chat/");
    await expect(page.getByRole("heading", { name: "How can I help today?" })).toBeVisible();

    await page.getByRole("textbox").fill("Summarize today's launch notes");
    await page.getByRole("button", { name: "Send message" }).click();

    await expect(page.getByText("Runtime answer from the browser harness.")).toBeVisible();
    expect(state.createRunBodies).toHaveLength(0);
    expect(state.createSessionBodies).toHaveLength(1);
    expect(state.createSessionBodies[0]).toMatchObject({
      input_text: "Summarize today's launch notes",
      source_app_id: "chat",
      title: "New chat",
    });
  });

  test("sends a selected-agent multi run and opens the live graph", async ({ page }) => {
    const state = await installChatMocks(page);

    await page.goto("/apps/chat/");
    await expect(page.getByRole("heading", { name: "How can I help today?" })).toBeVisible();

    await page.getByRole("button", { name: "Agent runner: Default Chat" }).click();
    await page.getByRole("option", { name: /Researcher/ }).click();
    await expect(page.getByRole("button", { name: "Agent runner: Researcher" })).toBeVisible();

    await page.getByRole("button", { name: "Multi-agent mode: Off" }).click();
    await page.getByRole("menuitemradio", { name: "Multi" }).click();
    await expect(page.getByRole("button", { name: "Multi-agent mode: Multi" })).toBeVisible();

    await page.getByRole("textbox").fill("Research the launch risks and review the answer");
    await page.getByRole("button", { name: "Send message" }).click();

    await expect(page.getByText("Staged multi-agent run started.")).toBeVisible();
    await expect(page.getByRole("button", { name: /Agent nodes/ })).toBeVisible();

    expect(state.createSessionBodies).toHaveLength(1);
    expect(state.createRunBodies).toHaveLength(1);
    expect(state.createRunBodies[0]).toMatchObject({
      mode: "sequential",
      thread_id: THREAD_ID,
      root_runtime_session_id: RUNTIME_SESSION_ID,
      visibility_level: "detail",
      budget: {
        max_participants: 3,
        max_concurrent_participants: 1,
        max_total_turns: 2,
        max_turns_per_participant: 1,
        max_tool_calls: 2,
      },
    });
    expect(state.createRunBodies[0].participants).toMatchObject([
      { participant_id: "orchestrator", kind: "orchestrator" },
      {
        participant_id: "implementer",
        kind: "agent",
        agent_type_id: RESEARCHER_AGENT_ID,
        agent_snapshot: {
          label: "Implementer",
          skill_ids: ["storage", "browser"],
          system_prompt: "Research with citations.",
        },
      },
      {
        participant_id: "reviewer",
        kind: "agent",
        agent_type_id: RESEARCHER_AGENT_ID,
        agent_snapshot: {
          label: "Reviewer",
          skill_ids: ["storage", "browser"],
          system_prompt: "Research with citations.",
        },
      },
    ]);
    expect(state.createRunBodies[0].edges).toMatchObject([
      { source_id: "orchestrator", target_id: "implementer", kind: "delegated", label: "Implementation" },
      { source_id: "implementer", target_id: "reviewer", kind: "reviewed_by", label: "Review" },
      { source_id: "reviewer", target_id: "orchestrator", kind: "produced", label: "Final review" },
    ]);

    await expect.poll(() => state.executeRunBodies.length).toBe(1);
    expect(state.executeRunBodies[0]).toMatchObject({
      input_text: "Research the launch risks and review the answer",
      participant_inputs: {
        implementer: "Act as the implementer. Produce the concrete answer or implementation plan for the user request.",
        reviewer: /Act as the reviewer/,
      },
      async: true,
    });

    await page.getByRole("button", { name: /Agent nodes/ }).click();
    await expect(page.getByRole("region", { name: "Agent nodes view" })).toBeVisible();
    await expect(page.getByText("3 nodes")).toBeVisible();
    await expect(page.getByText("Implementer")).toBeVisible();
    await expect(page.getByText("Reviewer")).toBeVisible();
    await expect(page.locator(".chatapp-inter-agent-graph__edge-path")).toHaveCount(3);

    await expect.poll(() => state.interAgentSockets.length).toBeGreaterThan(0);
    state.interAgentSockets.at(-1)?.send(
      JSON.stringify({
        type: "inter_agent.event",
        event: interAgentEvent({
          event_id: "event-live-review",
          event_type: "inter_agent.task.completed",
          participant_id: "reviewer",
          runtime_session_id: "child-reviewer",
          runtime_turn_id: "turn-reviewer",
          sequence: 3,
          payload: { summary: "Reviewer completed browser-observed final review." },
        }),
      }),
    );

    await expect(page.getByText("Reviewer completed browser-observed final review.")).toBeVisible();
    await page.getByRole("button", { name: /Stop/ }).click();
    await expect
      .poll(() => state.runDetail.run.status)
      .toBe("cancelled");
  });
});

async function installChatMocks(page: Page): Promise<MockState> {
  const state = createMockState();

  await page.route("https://fonts.googleapis.com/**", (route) => route.fulfill({ status: 200, contentType: "text/css", body: "" }));
  await page.route("https://fonts.gstatic.com/**", (route) => route.fulfill({ status: 204, body: "" }));
  await page.route("**/api/providers", (route) => fulfillJson(route, providerPayload()));
  await page.route("**/api/apps/dependencies?**", (route) => fulfillJson(route, dependencyPayload()));
  await page.route("**/api/apps", (route) => fulfillJson(route, appsPayload()));
  await page.route("**/api/apps/chat/backend", async (route) => handleChatBackend(route));
  await page.route("**/api/apps/agents/backend", async (route) => handleAgentsBackend(route));
  await page.route("**/api/apps/skills/backend", async (route) => handleSkillsBackend(route));
  await page.route("**/api/runtime/**", async (route) => handleRuntimeApi(route, state));
  await page.route("**/api/inter-agent/**", async (route) => handleInterAgentApi(route, state));
  await page.routeWebSocket("**/ws/runtime/threads", (ws) => {
    setTimeout(() => {
      ws.send(
        JSON.stringify({
          type: "runtime.thread.snapshot",
          workspace_id: WORKSPACE_ID,
          threads: state.threads,
          at: NOW,
        }),
      );
    }, 0);
  });
  await page.routeWebSocket(/\/ws\/runtime\/sessions\//, (ws) => {
    const sessionId = decodeURIComponent(new URL(ws.url()).pathname.split("/").at(-1) || RUNTIME_SESSION_ID);
    setTimeout(() => {
      ws.send(
        JSON.stringify({
          type: "runtime.snapshot",
          session: runtimeSession(sessionId),
          events: state.runtimeSessionEvents[sessionId] || [],
          turns: state.runtimeSessionTurns[sessionId] || [],
          last_event_id: lastRuntimeEventId(state.runtimeSessionEvents[sessionId] || []),
          has_more_before: false,
          oldest_event_id: firstRuntimeEventId(state.runtimeSessionEvents[sessionId] || []),
        }),
      );
    }, 0);
  });
  await page.routeWebSocket(/\/ws\/inter-agent\/runs\//, (ws) => {
    state.interAgentSockets.push(ws);
    ws.onMessage((message) => {
      const payload = typeof message === "string" ? safeJson(message) : null;
      if (payload?.type === "inter_agent.history.before") {
        ws.send(
          JSON.stringify({
            type: "inter_agent.history.page",
            events: [],
            artifacts: [],
            visibility_plane: "detail",
            before_event_id: typeof payload.before_event_id === "string" ? payload.before_event_id : null,
            oldest_event_id: null,
            newest_event_id: null,
            has_more_before: false,
          }),
        );
      }
    });
    setTimeout(() => {
      ws.send(
        JSON.stringify({
          type: "inter_agent.snapshot",
          run_detail: state.runDetail,
          approvals: [],
          artifacts: state.runArtifacts,
          events: state.runEvents,
          visibility_plane: "detail",
          last_event_id: lastInterAgentEventId(state.runEvents),
          has_more_before: false,
          oldest_event_id: firstInterAgentEventId(state.runEvents),
        }),
      );
    }, 0);
  });

  return state;
}

function createMockState(): MockState {
  return {
    createRunBodies: [],
    createSessionBodies: [],
    executeRunBodies: [],
    interAgentSockets: [],
    runtimeSessionEvents: {},
    runtimeSessionTurns: {},
    threads: [],
    runCreated: false,
    runDetail: interAgentRunDetail(),
    runEvents: [
      interAgentEvent({
        event_id: "event-plan",
        event_type: "inter_agent.plan.summary_created",
        visibility_plane: "summary",
        payload: { summary: "Staged multi-agent run started." },
        sequence: 1,
      }),
      interAgentEvent({
        event_id: "event-artifact",
        event_type: "inter_agent.artifact.created",
        participant_id: "reviewer",
        runtime_session_id: "child-reviewer",
        runtime_turn_id: "turn-reviewer",
        payload: {
          artifact_refs: [{ artifact_id: "artifact-final", label: "Final brief", workspace_relative_path: "storage/generated/final.md" }],
          partial_output: "Reviewer draft before final synthesis.",
          status: "created",
        },
        sequence: 2,
      }),
    ],
    runArtifacts: [
      {
        artifact_id: "artifact-final",
        event_id: "event-artifact",
        run_id: RUN_ID,
        participant_id: "reviewer",
        label: "Final brief",
        status: "created",
        created_at: NOW,
        workspace_relative_path: "storage/generated/final.md",
        partial_output: "Reviewer draft before final synthesis.",
      },
    ],
  };
}

async function handleChatBackend(route: Route) {
  const body = postBody(route);
  if (body.action === "projects.list") {
    expectPostBody(route, body, { action: "projects.list" });
    await fulfillJson(route, { projects: [], preferences: {} });
    return;
  }
  if (body.action === "view_filter") {
    expectPostBody(route, body, { action: "view_filter" });
    await fulfillJson(route, { state: { view_filter: { mode: "thread", query: "", entity_type: "thread", title: "" } } });
    return;
  }
  await fulfillUnhandledBackend(route, "Chat backend", body);
}

async function handleAgentsBackend(route: Route) {
  const body = postBody(route);
  if (body.action === "catalog.compact") {
    expectPostBody(route, body, { action: "catalog.compact", entity_type: "agent_type", limit: 100 });
    await fulfillJson(route, {
      workspace_id: WORKSPACE_ID,
      agent_types: [researcherAgentSummary()],
    });
    return;
  }
  if (body.action === "get_agent_definition") {
    expectPostBody(route, body, { action: "get_agent_definition", id: RESEARCHER_AGENT_ID });
    await fulfillJson(route, {
      exists: true,
      agent_definition: {
        ...researcherAgentSummary(),
        role_name: "Researcher",
        role_description: "Researches with citations.",
        instructions: "Research with citations.",
      },
    });
    return;
  }
  if (body.action === "preview_prompt") {
    expectPostBody(route, body, { action: "preview_prompt", agent_type_id: RESEARCHER_AGENT_ID });
    await fulfillJson(route, { rendered: "Research with citations." });
    return;
  }
  await fulfillUnhandledBackend(route, "Agents backend", body);
}

async function handleSkillsBackend(route: Route) {
  const body = postBody(route);
  if (body.action !== "catalog") {
    await fulfillUnhandledBackend(route, "Skills backend", body);
    return;
  }
  expectPostBody(route, body, { action: "catalog" });
  await fulfillJson(route, {
    skills: [
      { id: "storage", name: "Storage", description: "Use workspace files.", enabled: true },
      { id: "browser", name: "Browser", description: "Inspect web pages.", enabled: true },
    ],
  });
}

async function handleRuntimeApi(route: Route, state: MockState) {
  const request = route.request();
  const url = new URL(request.url());
  if (url.pathname === "/api/runtime/sessions" && request.method() === "POST") {
    const body = postBody(route);
    state.createSessionBodies.push(body);
    if (typeof body.input_text === "string") {
      const session = runtimeSession(RUNTIME_SESSION_ID);
      const turn = runtimeTurn("turn-normal", session.session_id, "completed", body.input_text);
      const events = runtimeTranscriptEvents(
        session.session_id,
        turn.turn_id,
        body.input_text,
        "Runtime answer from the browser harness.",
        typeof body.client_message_id === "string" ? body.client_message_id : undefined,
      );
      const thread = chatThread({
        availability: "free",
        last_user_message_at: NOW,
        runtime_session_id: session.session_id,
        thread_id: THREAD_ID,
        title: "Launch notes",
      });
      state.threads = [thread];
      state.runtimeSessionEvents[session.session_id] = events;
      state.runtimeSessionTurns[session.session_id] = [turn];
      await fulfillJson(route, { session, thread, turn, events });
      return;
    }
    const session = runtimeSession(RUNTIME_SESSION_ID, {
      agent_id: typeof body.agent_id === "string" && body.agent_id ? body.agent_id : "Researcher",
    });
    await fulfillJson(route, session);
    return;
  }
  if (url.pathname.endsWith("/read") && request.method() === "POST") {
    await fulfillJson(route, { thread: state.threads[0], threads: state.threads });
    return;
  }
  if (url.pathname.includes("/events") && request.method() === "GET") {
    const sessionId = decodeURIComponent(url.pathname.split("/")[4] || RUNTIME_SESSION_ID);
    await fulfillJson(route, { items: state.runtimeSessionEvents[sessionId] || [] });
    return;
  }
  if (url.pathname.includes("/turns") && request.method() === "POST") {
    const sessionId = decodeURIComponent(url.pathname.split("/")[4] || RUNTIME_SESSION_ID);
    const body = postBody(route);
    const turn = runtimeTurn("turn-followup", sessionId, "completed", typeof body.input_text === "string" ? body.input_text : "");
    const events = runtimeTranscriptEvents(
      sessionId,
      turn.turn_id,
      turn.input_text || "",
      "Follow-up answer from the browser harness.",
      typeof body.client_message_id === "string" ? body.client_message_id : undefined,
    );
    state.runtimeSessionEvents[sessionId] = [...(state.runtimeSessionEvents[sessionId] || []), ...events];
    state.runtimeSessionTurns[sessionId] = [...(state.runtimeSessionTurns[sessionId] || []), turn];
    await fulfillJson(route, { session: runtimeSession(sessionId), thread: state.threads[0], turn, events });
    return;
  }
  if (url.pathname.includes("/interrupt") && request.method() === "POST") {
    await fulfillJson(route, { interrupted: true, turn: runtimeTurn("turn-normal", RUNTIME_SESSION_ID, "cancelled", null) });
    return;
  }
  await fulfillJson(route, { detail: `Unhandled runtime mock: ${request.method()} ${url.pathname}` }, 404);
}

async function handleInterAgentApi(route: Route, state: MockState) {
  const request = route.request();
  const url = new URL(request.url());
  const parts = url.pathname.split("/").filter(Boolean);

  if (url.pathname === "/api/inter-agent/runs" && request.method() === "GET") {
    await fulfillJson(route, { items: state.runCreated ? [state.runDetail] : [] });
    return;
  }
  if (url.pathname === "/api/inter-agent/runs" && request.method() === "POST") {
    const body = postBody(route);
    state.createRunBodies.push(body);
    state.runCreated = true;
    state.runDetail = interAgentRunDetail({ run: { status: "created", mode: body.mode || "sequential" } });
    await fulfillJson(route, state.runDetail);
    return;
  }

  const runId = parts[3] || RUN_ID;
  const action = parts[4] || "";
  if (parts[0] === "api" && parts[1] === "inter-agent" && parts[2] === "runs" && runId === RUN_ID) {
    if (!action && request.method() === "GET") {
      await fulfillJson(route, state.runDetail);
      return;
    }
    if (action === "execute" && request.method() === "POST") {
      const body = postBody(route);
      state.executeRunBodies.push(body);
      state.runCreated = true;
      state.runDetail = interAgentRunDetail({
        run: { status: "running", mode: "sequential" },
        root_runtime_turn: runtimeTurn("turn-root", RUNTIME_SESSION_ID, "active", typeof body.input_text === "string" ? body.input_text : ""),
        root_runtime_events: runtimeTranscriptEvents(
          RUNTIME_SESSION_ID,
          "turn-root",
          typeof body.input_text === "string" ? body.input_text : "",
          "Root orchestrator accepted the multi-agent request.",
          typeof body.client_message_id === "string" ? body.client_message_id : undefined,
        ),
      });
      state.threads = [
        chatThread({
          availability: "active",
          runtime_session_id: RUNTIME_SESSION_ID,
          thread_id: THREAD_ID,
          title: "Multi-agent launch risks",
        }),
      ];
      state.runtimeSessionEvents[RUNTIME_SESSION_ID] = state.runDetail.root_runtime_events || [];
      state.runtimeSessionTurns[RUNTIME_SESSION_ID] = [state.runDetail.root_runtime_turn as RuntimeTurn];
      await fulfillJson(route, state.runDetail);
      return;
    }
    if (action === "events" && request.method() === "GET") {
      await fulfillJson(route, eventPage(state.runEvents, url.searchParams.get("visibility_plane") || "summary"));
      return;
    }
    if (action === "artifacts" && request.method() === "GET") {
      await fulfillJson(route, {
        items: state.runArtifacts,
        visibility_plane: url.searchParams.get("visibility_plane") || "detail",
        limit: 240,
        has_more_before: false,
        has_more_after: false,
        oldest_event_id: "event-artifact",
        newest_event_id: "event-artifact",
      });
      return;
    }
    if (action === "approvals" && request.method() === "GET") {
      await fulfillJson(route, { items: [] });
      return;
    }
    if (action === "interrupt" && request.method() === "POST") {
      state.runDetail = interAgentRunDetail({ run: { status: "paused" } });
      await fulfillJson(route, { run: state.runDetail.run, interrupted_sessions: [] });
      return;
    }
    if (action === "resume" && request.method() === "POST") {
      state.runDetail = interAgentRunDetail({ run: { status: "running" } });
      await fulfillJson(route, state.runDetail);
      return;
    }
    if (action === "close" && request.method() === "POST") {
      state.runDetail = interAgentRunDetail({ run: { status: "cancelled", ended_at: NOW } });
      await fulfillJson(route, { run: state.runDetail.run, participant_cleanups: [] });
      return;
    }
  }

  await fulfillJson(route, { detail: `Unhandled inter-agent mock: ${request.method()} ${url.pathname}` }, 404);
}

function providerPayload() {
  return {
    workspace_id: WORKSPACE_ID,
    configured: true,
    active_provider: {
      provider_id: "codex",
      label: "Codex",
      description: "Local test provider",
      status: "ready",
      default_model_family: "gpt",
    },
    items: [
      {
        provider_id: "codex",
        label: "Codex",
        description: "Local test provider",
        status: "ready",
        default_model_family: "gpt",
      },
    ],
  };
}

function dependencyPayload() {
  const agentsCandidate = {
    app_id: "agents",
    name: "Agents",
    version: "0.1.0",
    interface: "agent.catalog",
    interface_version: "1",
    description: "Agent catalog",
    surfaces: ["backend"],
  };
  return {
    workspace_id: WORKSPACE_ID,
    consumer_app_id: "chat",
    status: "resolved",
    dependencies: [
      {
        alias: "agent-catalog",
        interface: "agent.catalog",
        version: "^1",
        required: false,
        cardinality: "one",
        description: "Agent catalog",
        status: "resolved",
        candidates: [agentsCandidate],
        selected_provider_app_ids: ["agents"],
        stale_provider_app_ids: [],
        blocked_reason: null,
      },
      {
        alias: "agent-prompt-materializer",
        interface: "agent.prompt-materializer",
        version: "^1",
        required: false,
        cardinality: "one",
        description: "Agent prompt materializer",
        status: "resolved",
        candidates: [{ ...agentsCandidate, interface: "agent.prompt-materializer", description: "Agent prompt materializer" }],
        selected_provider_app_ids: ["agents"],
        stale_provider_app_ids: [],
        blocked_reason: null,
      },
      {
        alias: "text-to-speech",
        interface: "speech.synthesis",
        version: "^1",
        required: false,
        cardinality: "one",
        description: "Speech synthesis",
        status: "optional_unset",
        candidates: [],
        selected_provider_app_ids: [],
        stale_provider_app_ids: [],
        blocked_reason: null,
      },
      {
        alias: "speech-to-text",
        interface: "speech.transcription",
        version: "^1",
        required: false,
        cardinality: "one",
        description: "Speech transcription",
        status: "optional_unset",
        candidates: [],
        selected_provider_app_ids: [],
        stale_provider_app_ids: [],
        blocked_reason: null,
      },
    ],
  };
}

function appsPayload() {
  return {
    items: [
      { app_id: "chat", name: "Chat", description: "Workspace chat", status: "enabled", frontend_mount: "/apps/chat/", backend_mount: "/api/apps/chat/backend" },
      { app_id: "storage", name: "Storage", description: "Workspace files", status: "enabled", frontend_mount: "/apps/storage/", backend_mount: "/api/apps/storage/backend" },
      { app_id: "agents", name: "Agents", description: "Agent catalog", status: "enabled", frontend_mount: "/apps/agents/", backend_mount: "/api/apps/agents/backend" },
    ],
  };
}

function researcherAgentSummary() {
  return {
    id: RESEARCHER_AGENT_ID,
    name: "Researcher",
    description: "Researches with citations.",
    role_id: "researcher",
    skill_ids: ["storage", "browser"],
    trace_verbosity: "compact",
    enabled: true,
  };
}

function chatThread(overrides: Partial<ChatThread> = {}): ChatThread {
  return {
    thread_id: THREAD_ID,
    runtime_session_id: RUNTIME_SESSION_ID,
    title: "New chat",
    agent_label: "",
    agent_type_id: "",
    agent_role_id: "",
    source_app_id: "chat",
    system_prompt: "",
    project_id: null,
    archived: false,
    availability: "free",
    created_at: NOW,
    updated_at: NOW,
    last_user_message_at: null,
    ...overrides,
  };
}

function runtimeSession(sessionId: string, overrides: Partial<RuntimeSession> = {}): RuntimeSession {
  return {
    session_id: sessionId,
    workspace_id: WORKSPACE_ID,
    agent_id: "chat",
    status: "running",
    effective_mode: "sandbox",
    ...overrides,
  };
}

function runtimeTurn(turnId: string, sessionId: string, status: string, inputText: string | null): RuntimeTurn {
  return {
    turn_id: turnId,
    session_id: sessionId,
    workspace_id: WORKSPACE_ID,
    status,
    input_text: inputText,
    failure_reason: null,
    created_at: NOW,
    updated_at: NOW,
  };
}

function runtimeTranscriptEvents(sessionId: string, turnId: string, inputText: string, outputText: string, clientMessageId?: string): RuntimeEvent[] {
  return [
    {
      event_id: `${turnId}-queued`,
      session_id: sessionId,
      turn_id: turnId,
      event_type: "runtime.turn.queued",
      payload: { input_text: inputText, client_message_id: clientMessageId || `client-${turnId}` },
      created_at: NOW,
    },
    {
      event_id: `${turnId}-final`,
      session_id: sessionId,
      turn_id: turnId,
      event_type: "runtime.output.final",
      payload: { text: outputText },
      created_at: NOW,
    },
  ];
}

function interAgentRunDetail(overrides: { run?: JsonRecord; root_runtime_events?: RuntimeEvent[]; root_runtime_turn?: RuntimeTurn } = {}): InterAgentRunDetail {
  const run = {
    run_id: RUN_ID,
    workspace_id: WORKSPACE_ID,
    thread_id: THREAD_ID,
    root_runtime_session_id: RUNTIME_SESSION_ID,
    source_app_id: "chat",
    mode: "sequential",
    status: "running",
    created_by_user_id: "user:admin",
    orchestrator_participant_id: "orchestrator",
    budget_policy_id: "budget-chat-e2e",
    budget_ledger_id: "ledger-chat-e2e",
    visibility_level: "detail",
    created_at: NOW,
    updated_at: NOW,
    ended_at: null,
    ...(overrides.run || {}),
  };
  return {
    run,
    participants: [
      interAgentParticipant("orchestrator", "orchestrator", "root_orchestrator", "Orchestrator", null, "running", 0),
      interAgentParticipant("implementer", "agent", "child_runtime_session", "Implementer", "child-implementer", "completed", 1),
      interAgentParticipant("reviewer", "agent", "child_runtime_session", "Reviewer", "child-reviewer", "running", 2),
    ],
    edges: [
      interAgentEdge("edge-implementation", "orchestrator", "implementer", "delegated", "Implementation"),
      interAgentEdge("edge-review", "implementer", "reviewer", "reviewed_by", "Review"),
      interAgentEdge("edge-final-review", "reviewer", "orchestrator", "produced", "Final review"),
    ],
    budget_policy: {
      budget_policy_id: "budget-chat-e2e",
      workspace_id: WORKSPACE_ID,
      max_participants: 3,
      max_concurrent_participants: 1,
      max_handoffs: 3,
      max_rounds: 1,
      max_total_turns: 2,
      max_turns_per_participant: 1,
      max_tool_calls: 2,
      max_estimated_tokens: 0,
      max_estimated_cost: "0",
      max_idle_seconds: 60,
      max_stall_seconds: 120,
      approval_required_above_cost: "0",
      created_at: NOW,
    },
    budget_ledger: {
      budget_ledger_id: "ledger-chat-e2e",
      workspace_id: WORKSPACE_ID,
      run_id: RUN_ID,
      reserved_participants: 3,
      running_participants: 1,
      turns_used: 1,
      tool_calls_used: 0,
      handoffs_used: 2,
      estimated_tokens_used: 0,
      estimated_cost_used: "0",
      updated_at: NOW,
    },
    root_runtime_events: overrides.root_runtime_events,
    root_runtime_turn: overrides.root_runtime_turn,
  };
}

function interAgentParticipant(
  participantId: string,
  kind: string,
  executionMode: string,
  label: string,
  runtimeSessionId: string | null,
  status: string,
  sequenceIndex: number,
) {
  return {
    participant_id: participantId,
    workspace_id: WORKSPACE_ID,
    run_id: RUN_ID,
    kind,
    execution_mode: executionMode,
    agent_type_id: kind === "agent" ? RESEARCHER_AGENT_ID : null,
    label,
    runtime_session_id: runtimeSessionId,
    status,
    current_task_id: null,
    thread_visibility: kind === "agent" ? "hidden" : "user",
    created_at: NOW,
    updated_at: NOW,
    sequence_index: sequenceIndex,
  };
}

function interAgentEdge(edgeId: string, sourceId: string, targetId: string, kind: string, label: string) {
  return {
    edge_id: edgeId,
    workspace_id: WORKSPACE_ID,
    run_id: RUN_ID,
    source_id: sourceId,
    target_id: targetId,
    kind,
    label,
    status: "active",
    created_at: NOW,
  };
}

function interAgentEvent(overrides: Partial<InterAgentEvent> = {}): InterAgentEvent {
  return {
    event_id: "event-1",
    workspace_id: WORKSPACE_ID,
    run_id: RUN_ID,
    thread_id: THREAD_ID,
    root_runtime_session_id: RUNTIME_SESSION_ID,
    participant_id: "orchestrator",
    runtime_session_id: null,
    runtime_turn_id: null,
    runtime_event_id: null,
    event_type: "inter_agent.plan.summary_created",
    visibility_plane: "detail",
    sequence: 1,
    correlation_id: "event-1",
    idempotency_key: "event-1",
    payload: {},
    created_at: NOW,
    ...overrides,
  };
}

function eventPage(events: InterAgentEvent[], visibilityPlane: string) {
  const visibleEvents = visibilityPlane === "summary" ? events.filter((event) => event.visibility_plane === "summary") : events;
  return {
    items: visibleEvents,
    visibility_plane: visibilityPlane,
    limit: 240,
    has_more_before: false,
    has_more_after: false,
    oldest_event_id: firstInterAgentEventId(visibleEvents),
    newest_event_id: lastInterAgentEventId(visibleEvents),
  };
}

function firstRuntimeEventId(events: RuntimeEvent[]): string | null {
  return events[0]?.event_id || null;
}

function lastRuntimeEventId(events: RuntimeEvent[]): string | null {
  return events.at(-1)?.event_id || null;
}

function firstInterAgentEventId(events: InterAgentEvent[]): string | null {
  return events[0]?.event_id || null;
}

function lastInterAgentEventId(events: InterAgentEvent[]): string | null {
  return events.at(-1)?.event_id || null;
}

function postBody(route: Route): JsonRecord {
  return safeJson(route.request().postData() || "{}") || {};
}

function expectPostBody(route: Route, body: JsonRecord, expectedBody: JsonRecord) {
  expect(route.request().method()).toBe("POST");
  expect(body).toEqual(expectedBody);
}

async function fulfillUnhandledBackend(route: Route, backendName: string, body: JsonRecord) {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  const action = typeof body.action === "string" && body.action ? body.action : "<missing>";
  const detail = `Unhandled ${backendName} mock action: ${request.method()} ${path} action=${action}`;
  await fulfillJson(route, { detail }, 404);
  throw new Error(detail);
}

function safeJson(value: string): JsonRecord | null {
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" ? (parsed as JsonRecord) : null;
  } catch {
    return null;
  }
}

async function fulfillJson(route: Route, payload: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}
