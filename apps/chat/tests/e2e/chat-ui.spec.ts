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
  createOrchestrationBodies: JsonRecord[];
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

  test.describe("mobile composer", () => {
    test.use({ hasTouch: true });

    test("collapses controls into an upward utility panel", async ({ page }) => {
      await page.setViewportSize({ height: 844, width: 390 });
      await installChatMocks(page);

      await page.goto("/apps/chat/");

      const composer = page.locator(".chatapp-composer");
      const attachmentButton = composer.getByRole("button", { name: "Add attachments" });
      const utilityButton = composer.getByRole("button", { name: "Composer utilities" });
      const utilityPanel = composer.getByRole("group", { name: "Composer utility controls" });

      await expect(attachmentButton).toBeVisible();
      await expect(utilityButton).toBeVisible();
      await expect(composer.locator("button:visible")).toHaveCount(2);
      await expect(utilityPanel).toBeHidden();

      await composer.getByRole("textbox").fill("Mobile utility message");
      await expect(composer.locator("button:visible")).toHaveCount(2);

      await utilityButton.tap();

      await expect(utilityPanel).toBeVisible();
      await expect(composer.getByRole("button", { name: "Apps and references" })).toBeVisible();
      await expect(composer.getByRole("button", { name: "Multi-agent mode: Off" })).toBeVisible();
      await expect(composer.getByRole("button", { name: "Agent runner: Default Chat" })).toBeVisible();
      await expect(composer.getByRole("button", { name: "Send message" })).toBeEnabled();

      const utilityBox = await utilityButton.boundingBox();
      const panelBox = await utilityPanel.boundingBox();
      expect(utilityBox).not.toBeNull();
      expect(panelBox).not.toBeNull();
      expect((panelBox?.y || 0) + (panelBox?.height || 0)).toBeLessThan(utilityBox?.y || 0);
    });
  });

  test("coalesces structured goal progress without presenting telemetry as tool calls", async ({ page }) => {
    const state = await installChatMocks(page);
    const turn = runtimeTurn("turn-goal", RUNTIME_SESSION_ID, "completed", "Inspect the active goal");
    state.threads = [chatThread({ title: "Goal inspection", last_user_message_at: NOW })];
    state.runtimeSessionTurns[RUNTIME_SESSION_ID] = [turn];
    state.runtimeSessionEvents[RUNTIME_SESSION_ID] = [
      {
        event_id: "turn-goal-queued",
        session_id: RUNTIME_SESSION_ID,
        turn_id: turn.turn_id,
        event_type: "runtime.turn.queued",
        payload: { input_text: "Inspect the active goal", client_message_id: "client-turn-goal" },
        created_at: NOW,
      },
      {
        event_id: "turn-goal-active",
        session_id: RUNTIME_SESSION_ID,
        turn_id: turn.turn_id,
        event_type: "runtime.step.updated",
        payload: {
          label: "thread goal updated",
          provider_event_type: "thread.goal.updated",
          raw: {
            type: "thread.goal.updated",
            item: {
              threadId: "provider-thread-1",
              goal: { objective: "Inspect the active goal", status: "active", tokensUsed: 0, timeUsedSeconds: 0 },
            },
          },
        },
        created_at: NOW,
      },
      {
        event_id: "turn-goal-empty-update",
        session_id: RUNTIME_SESSION_ID,
        turn_id: turn.turn_id,
        event_type: "runtime.step.updated",
        payload: { label: "thread goal updated", provider_event_type: "thread.goal.updated" },
        created_at: NOW,
      },
      {
        event_id: "turn-goal-progress",
        session_id: RUNTIME_SESSION_ID,
        turn_id: turn.turn_id,
        event_type: "runtime.step.updated",
        payload: {
          label: "thread goal updated",
          provider_event_type: "thread.goal.updated",
          raw: {
            type: "thread.goal.updated",
            item: { threadId: "provider-thread-1", goal: { tokensUsed: 1892, timeUsedSeconds: 7 } },
          },
        },
        created_at: NOW,
      },
      {
        event_id: "turn-goal-final",
        session_id: RUNTIME_SESSION_ID,
        turn_id: turn.turn_id,
        event_type: "runtime.output.final",
        payload: { text: "Goal state inspected." },
        created_at: NOW,
      },
    ];

    await page.goto("/apps/chat/");

    const disclosure = page.getByRole("button", { name: /Goal status · Active/ });
    await expect(disclosure).toBeVisible();
    await expect(page.getByRole("button", { name: /Goal status/ })).toHaveCount(1);
    await expect(disclosure).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByRole("button", { name: /Tool Used/ })).toHaveCount(0);

    await disclosure.click();
    await expect(disclosure).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("region", { name: "Goal status details" })).toContainText("Inspect the active goal");
    await expect(page.getByRole("region", { name: "Goal status details" })).toContainText("1,892");
    await expect(page.getByRole("region", { name: "Goal status details" })).toContainText("7s");
    await page.getByText("Technical details", { exact: true }).click();
    await expect(page.getByRole("region", { name: "Goal status details" })).toContainText("provider-thread-1");
  });

  test("keeps composer undo and redo reliable across rich edits", async ({ page }) => {
    await installChatMocks(page);

    await page.goto("/apps/chat/");
    const composer = page.getByRole("textbox");
    await expect(page.getByRole("heading", { name: "How can I help today?" })).toBeVisible();
    await expect(composer).toBeEditable();

    await composer.click();
    await composer.pressSequentially("hello");
    await expectComposerText(page, "hello");

    await page.keyboard.press("ControlOrMeta+Z");
    await expectComposerText(page, "");

    await page.keyboard.press("ControlOrMeta+Shift+Z");
    await expectComposerText(page, "hello");

    await pasteComposerText(page, " pasted\r\nline");
    await expectComposerText(page, "hello pasted\nline");

    await page.keyboard.press("ControlOrMeta+Z");
    await expectComposerText(page, "hello");

    await page.keyboard.press("Control+Y");
    await expectComposerText(page, "hello pasted\nline");

    await page.keyboard.press("Shift+Enter");
    await expectComposerText(page, "hello pasted\nline\n");

    await page.keyboard.press("ControlOrMeta+Z");
    await expectComposerText(page, "hello pasted\nline");

    await page.keyboard.press("ControlOrMeta+Shift+Z");
    await expectComposerText(page, "hello pasted\nline\n");

    await page.keyboard.press("ControlOrMeta+Z");
    await expectComposerText(page, "hello pasted\nline");

    await composer.pressSequentially(" @Sto");
    await expect(page.getByRole("option", { name: /Storage/ })).toBeVisible();
    await page.keyboard.press("Enter");
    await expectComposerText(page, "hello pasted\nline @Storage ");

    await page.keyboard.press("ControlOrMeta+Z");
    await expectComposerText(page, "hello pasted\nline @Sto");

    await page.keyboard.press("ControlOrMeta+Shift+Z");
    await expectComposerText(page, "hello pasted\nline @Storage ");
  });

  test("keeps the composer caret after Shift+Enter in the middle of text", async ({ page }) => {
    await installChatMocks(page);

    await page.goto("/apps/chat/");
    const composer = page.getByRole("textbox");
    await expect(page.getByRole("heading", { name: "How can I help today?" })).toBeVisible();
    await expect(composer).toBeEditable();

    await composer.click();
    await pasteComposerText(page, "First sentence.\n\nSecond sentence");
    await expectComposerText(page, "First sentence.\n\nSecond sentence");
    await setComposerCaretOffset(page, "First sentence.\n".length);
    await page.keyboard.press("Shift+Enter");
    await expectComposerText(page, "First sentence.\n\n\nSecond sentence");

    await composer.pressSequentially("Inserted ");
    await expectComposerText(page, "First sentence.\n\nInserted \nSecond sentence");
  });

  test("sends a normal chat message through runtime session APIs", async ({ page }) => {
    const state = await installChatMocks(page);

    await page.goto("/apps/chat/");
    await expect(page.getByRole("heading", { name: "How can I help today?" })).toBeVisible();

    await page.getByRole("textbox").fill("Summarize today's launch notes");
    await page.getByRole("button", { name: "Send message" }).click();

    await expect(page.getByText(/^(?:Runtime|Follow-up) answer from the browser harness\.$/)).toBeVisible();
    expect(state.createOrchestrationBodies).toHaveLength(0);
    expect(state.createRunBodies).toHaveLength(0);
    expect(state.createSessionBodies).toContainEqual(expect.objectContaining({
      prepare_only: true,
      source_app_id: "chat",
      title: "New chat",
    }));
    expect(Object.values(state.runtimeSessionTurns).flat()).toContainEqual(
      expect.objectContaining({
        input_text: "Summarize today's launch notes",
      }),
    );
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

    await expect(page.getByText(/^(?:Runtime|Follow-up) answer from the browser harness\.$/)).toBeVisible();
    await expect(page.locator(".chatapp-chat-scroll").getByText("Final risk review ready.")).toHaveCount(0);
    const openAgentNodes = page.getByRole("button", { name: "Open multi-agent board" });
    await expect(openAgentNodes).toBeVisible();

    expect(state.createSessionBodies).toContainEqual(
      expect.objectContaining({
        agent_id: "Researcher",
        agent_type_id: RESEARCHER_AGENT_ID,
        source_app_id: "agents",
      }),
    );
    expect(state.createOrchestrationBodies).toHaveLength(1);
    expect(state.createOrchestrationBodies[0]).toMatchObject({
      root_runtime_session_id: RUNTIME_SESSION_ID,
      policy: "multi",
    });
    const multiGeneralistTurn = Object.values(state.runtimeSessionTurns)
      .flat()
      .find((turn) => turn.input_text === "Research the launch risks and review the answer");
    expect(state.createOrchestrationBodies[0].source_runtime_turn_id).toBe(multiGeneralistTurn?.turn_id);
    expect(Object.keys(state.createOrchestrationBodies[0]).sort()).toEqual([
      "idempotency_key",
      "policy",
      "root_runtime_session_id",
      "source_runtime_turn_id",
    ]);
    expect(state.createRunBodies).toHaveLength(0);
    expect(state.executeRunBodies).toHaveLength(0);

    await openAgentNodes.click();
    const agentNodesRegion = page.getByRole("region", { name: "Agent nodes view" });
    await expect(agentNodesRegion).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.fonts.check('12px "Material Symbols Rounded"'))).toBe(true);
    const agentNodesRegionBox = await agentNodesRegion.boundingBox();
    expect(agentNodesRegionBox?.width || 0).toBeGreaterThan(700);
    expect(agentNodesRegionBox?.height || 0).toBeGreaterThan(500);
    await expect(page.getByText("Implementer")).toBeVisible();
    await expect(page.getByText("Reviewer")).toBeVisible();
    await expectReactFlowGraphRendered(page, 3);
    await expectReactFlowPanMovesViewport(page);
    const reviewerNode = page.locator(".chatapp-inter-agent-graph__node").filter({
      has: page.locator('[data-participant-id="reviewer"]'),
    });
    await expect(reviewerNode).toHaveClass(/is-working/);
    await expect(reviewerNode.locator(".chatapp-live-border-glow")).toBeVisible();
    await expect(reviewerNode.getByText("Final risk review ready.")).toBeVisible();
    await expect(reviewerNode.locator(".chatapp-inter-agent-graph__node-activity-heading")).toHaveCount(0);
    await expect(reviewerNode.getByRole("button", { name: /Reviewer latest activity/ })).toHaveCount(0);
    await expect(reviewerNode.locator(".chatapp-inter-agent-graph__node-activity-caret")).toHaveCount(0);
    await expect(agentNodesRegion.getByText("Latest update")).toHaveCount(0);

    await page.locator('[data-participant-id="reviewer"]').click();
    const participantTranscript = page.getByRole("complementary", { name: "Reviewer transcript" });
    await expect(participantTranscript.getByText("Reviewing launch sources.")).toBeVisible();
    await expect(participantTranscript.getByText("Final risk review ready.")).toBeVisible();
    await expect(participantTranscript.getByText("Tool Used")).toBeVisible();
    await expect(participantTranscript.getByText("Web search")).toBeVisible();
    await expect(participantTranscript.locator(".chatapp-tool-inline__row")).toBeVisible();
    await expect(participantTranscript.locator(".chatapp-agent-block")).toHaveCount(2);
    const participantHeaderBox = await participantTranscript.locator(".chatapp-inter-agent-graph__transcript-title summary").boundingBox();
    expect(participantHeaderBox?.height || 0).toBeGreaterThanOrEqual(68);
    await participantTranscript.locator(".chatapp-inter-agent-graph__transcript-title summary").click();
    await expect(participantTranscript.getByText("Reviewer accepted browser-observed task.")).toBeVisible();
  });

  test("exposes gated group chat mode and opens its graph", async ({ page }) => {
    const state = await installChatMocks(page);

    await page.goto("/apps/chat/");
    await expect(page.getByRole("heading", { name: "How can I help today?" })).toBeVisible();

    await page.getByRole("button", { name: "Agent runner: Default Chat" }).click();
    await page.getByRole("option", { name: /Researcher/ }).click();
    await page.getByRole("button", { name: "Multi-agent mode: Off" }).click();
    await page.getByRole("menuitemradio", { name: "Group chat" }).click();
    await expect(page.getByRole("button", { name: "Multi-agent mode: Group chat" })).toBeVisible();

    await page.getByRole("textbox").fill("Compare the rollout options as a group");
    await page.getByRole("button", { name: "Send message" }).click();

    await expect(page.getByText(/^(?:Runtime|Follow-up) answer from the browser harness\.$/)).toBeVisible();
    await expect(page.locator(".chatapp-chat-scroll").getByText("Final risk review ready.")).toHaveCount(0);
    const openAgentNodes = page.getByRole("button", { name: "Open multi-agent board" });
    await expect(openAgentNodes).toBeVisible();
    expect(state.createOrchestrationBodies).toHaveLength(1);
    expect(state.createOrchestrationBodies[0]).toMatchObject({
      root_runtime_session_id: RUNTIME_SESSION_ID,
      policy: "group_chat",
    });
    const groupGeneralistTurn = Object.values(state.runtimeSessionTurns)
      .flat()
      .find((turn) => turn.input_text === "Compare the rollout options as a group");
    expect(state.createOrchestrationBodies[0].source_runtime_turn_id).toBe(groupGeneralistTurn?.turn_id);
    expect(state.createRunBodies).toHaveLength(0);
    expect(state.executeRunBodies).toHaveLength(0);

    await openAgentNodes.click();
    await expect(page.getByRole("region", { name: "Agent nodes view" })).toBeVisible();
    await expect(page.locator("[data-participant-id]")).toHaveCount(4);
    await expect(page.locator('[data-participant-id="analyst"]')).toBeVisible();
    await expect(page.locator('[data-participant-id="synthesizer"]')).toBeVisible();
  });

  test("renders React Flow Agent nodes on mobile and loads transcript on node click", async ({ page }) => {
    const state = await installChatMocks(page);
    state.runCreated = true;
    state.runDetail = interAgentRunDetail({ run: { status: "running", orchestration_policy: "multi" } });
    state.runEvents = interAgentEventsForMode("multi");
    state.runArtifacts = interAgentArtifactsForMode("multi");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/apps/chat/");
    await expect(page.getByRole("heading", { name: "How can I help today?" })).toBeVisible();
    await page.evaluate((runId) => {
      window.postMessage(
        {
          type: "maverick.app.navigate",
          app_id: "chat",
          params: { app_page: `graph/${runId}` },
        },
        window.location.origin,
      );
    }, RUN_ID);

    const mobileAgentNodesRegion = page.getByRole("region", { name: "Agent nodes view" });
    await expect(mobileAgentNodesRegion).toBeVisible();
    const mobileAgentNodesRegionBox = await mobileAgentNodesRegion.boundingBox();
    expect(mobileAgentNodesRegionBox?.width || 0).toBeGreaterThan(320);
    expect(mobileAgentNodesRegionBox?.height || 0).toBeGreaterThan(600);
    await expect(page.locator('[data-react-flow-agent-graph="true"]')).toBeVisible();
    await expect(page.locator("[data-participant-id]")).toHaveCount(3);
    await expectReactFlowGraphRendered(page, 3);
    await expect(page.locator(".chatapp-inter-agent-graph__node.is-working .chatapp-live-border-glow")).toHaveCount(2);
    await expect(page.getByText("Final risk review ready.")).toBeVisible();

    await page.locator('[data-participant-id="implementer"]').click();
    await expect(page.getByText("Implementer accepted browser-observed task.")).toBeHidden();
    await expect(page.getByText("Implementer produced a safe participant summary.")).toBeVisible();
    await page.locator(".chatapp-inter-agent-graph__transcript-title summary").click();
    await expect(page.getByText("Implementer accepted browser-observed task.")).toBeVisible();
    await expect(page.getByText("child-implementer")).toHaveCount(0);
    await expect(page.getByRole("complementary", { name: "Implementer transcript" })).toBeVisible();
  });
});

async function expectReactFlowGraphRendered(page: Page, expectedEdges: number) {
  const board = page.locator('[data-react-flow-agent-graph="true"]');
  await expect(board).toBeVisible();
  await expect(page.locator(".react-flow")).toBeVisible();
  await expect(page.locator(".react-flow__edge-path")).toHaveCount(expectedEdges);
  const boardBox = await board.boundingBox();
  expect(boardBox?.width || 0).toBeGreaterThan(250);
  expect(boardBox?.height || 0).toBeGreaterThan(250);

  const nodeBoxes = await page.locator("[data-participant-id]").evaluateAll((nodes) =>
    nodes.map((node) => {
      const rect = node.getBoundingClientRect();
      return { height: rect.height, width: rect.width };
    }),
  );
  expect(nodeBoxes.length).toBeGreaterThan(0);
  expect(nodeBoxes.every((box) => box.width > 70 && box.height > 24)).toBe(true);
}

async function expectReactFlowPanMovesViewport(page: Page) {
  const board = page.locator('[data-react-flow-agent-graph="true"]');
  const viewport = page.locator(".react-flow__viewport");
  const boardBox = await board.boundingBox();
  expect(boardBox).not.toBeNull();
  if (!boardBox) {
    return;
  }

  const before = await viewport.evaluate((element) => getComputedStyle(element).transform);
  const startX = boardBox.x + 42;
  const startY = boardBox.y + boardBox.height - 52;

  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.mouse.move(startX + 78, startY + 34, { steps: 6 });
  await page.mouse.up();

  await expect.poll(() => viewport.evaluate((element) => getComputedStyle(element).transform)).not.toBe(before);
}

async function expectComposerText(page: Page, expected: string) {
  await expect.poll(() => readComposerText(page)).toBe(expected);
}

async function readComposerText(page: Page): Promise<string> {
  return page.getByRole("textbox").evaluate((root) => {
    function textFromNode(node: ChildNode): string {
      if (node instanceof HTMLElement && node.dataset.mentionText) {
        return node.dataset.mentionText;
      }
      if (node.nodeType === Node.TEXT_NODE) {
        return node.textContent || "";
      }
      if (node instanceof HTMLElement && node.tagName === "BR") {
        return "\n";
      }
      return Array.from(node.childNodes)
        .map((child) => textFromNode(child))
        .join("");
    }

    return Array.from(root.childNodes)
      .map((node) => textFromNode(node))
      .join("");
  });
}

async function pasteComposerText(page: Page, text: string) {
  await page.getByRole("textbox").evaluate((root, pastedText) => {
    const dataTransfer = new DataTransfer();
    dataTransfer.setData("text/plain", pastedText);
    root.dispatchEvent(
      new ClipboardEvent("paste", {
        bubbles: true,
        cancelable: true,
        clipboardData: dataTransfer,
      }),
    );
  }, text);
}

async function setComposerCaretOffset(page: Page, offset: number) {
  await page.getByRole("textbox").evaluate((root, targetOffset) => {
    const range = document.createRange();
    let remaining = Math.max(0, targetOffset);
    let placed = false;

    function placeBefore(node: ChildNode) {
      range.setStartBefore(node);
      range.collapse(true);
      placed = true;
    }

    function placeAfter(node: ChildNode) {
      range.setStartAfter(node);
      range.collapse(true);
      placed = true;
    }

    function visit(node: ChildNode): void {
      if (placed) {
        return;
      }
      const tokenText = node instanceof HTMLElement ? node.dataset.mentionText || null : null;
      if (tokenText !== null) {
        if (remaining <= 0) {
          placeBefore(node);
          return;
        }
        if (remaining <= tokenText.length) {
          placeAfter(node);
          return;
        }
        remaining -= tokenText.length;
        return;
      }
      if (node.nodeType === Node.TEXT_NODE) {
        const textLength = (node.textContent || "").length;
        if (remaining <= textLength) {
          range.setStart(node, remaining);
          range.collapse(true);
          placed = true;
          return;
        }
        remaining -= textLength;
        return;
      }
      if (node instanceof HTMLElement && node.tagName === "BR") {
        if (remaining <= 0) {
          placeBefore(node);
          return;
        }
        if (remaining <= 1) {
          placeAfter(node);
          return;
        }
        remaining -= 1;
        return;
      }
      Array.from(node.childNodes).forEach((child) => visit(child));
    }

    Array.from(root.childNodes).forEach((node) => visit(node));
    if (!placed) {
      range.selectNodeContents(root);
      range.collapse(false);
    }
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    (root as HTMLElement).focus();
  }, offset);
}

async function installChatMocks(page: Page): Promise<MockState> {
  const state = createMockState();

  await page.route("**/material-symbols-rounded.woff2", (route) =>
    route.fulfill({
      path: "../base-shell/frontend/public/material-symbols-rounded.woff2",
      contentType: "font/woff2",
    }),
  );
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
    createOrchestrationBodies: [],
    createRunBodies: [],
    createSessionBodies: [],
    executeRunBodies: [],
    interAgentSockets: [],
    runtimeSessionEvents: {},
    runtimeSessionTurns: {},
    threads: [],
    runCreated: false,
    runDetail: interAgentRunDetail(),
    runEvents: interAgentEventsForMode("multi"),
    runArtifacts: interAgentArtifactsForMode("multi"),
  };
}

function interAgentEventsForMode(mode: string): InterAgentEvent[] {
  const groupChat = mode === "group_chat";
  const artifactParticipantId = groupChat ? "synthesizer" : "reviewer";
  const artifactSessionId = groupChat ? "child-synthesizer" : "child-reviewer";
  const artifactTurnId = groupChat ? "turn-synthesizer" : "turn-reviewer";
  return [
    interAgentEvent({
      event_id: "event-plan",
      event_type: "inter_agent.plan.summary_created",
      visibility_plane: "summary",
      payload: { summary: groupChat ? "Group chat run started." : "Staged multi-agent run started." },
      sequence: 1,
    }),
    interAgentEvent({
      event_id: "event-artifact",
      event_type: "inter_agent.artifact.created",
      participant_id: artifactParticipantId,
      runtime_session_id: artifactSessionId,
      runtime_turn_id: artifactTurnId,
      payload: {
        artifact_refs: [{ artifact_id: "artifact-final", label: "Final brief", workspace_relative_path: "storage/generated/final.md" }],
        partial_output: groupChat ? "Synthesizer draft before final answer." : "Reviewer draft before final synthesis.",
        status: "created",
      },
      sequence: 2,
    }),
    interAgentEvent({
      event_id: "event-final-review",
      event_type: "inter_agent.task.completed",
      participant_id: artifactParticipantId,
      runtime_session_id: artifactSessionId,
      runtime_turn_id: artifactTurnId,
      payload: {
        output_text: groupChat ? "Final group synthesis ready." : "Final risk review ready.",
        status: "completed",
      },
      sequence: 3,
    }),
  ];
}

function interAgentArtifactsForMode(mode: string): JsonRecord[] {
  const groupChat = mode === "group_chat";
  return [
    {
      artifact_id: "artifact-final",
      event_id: "event-artifact",
      run_id: RUN_ID,
      participant_id: groupChat ? "synthesizer" : "reviewer",
      label: "Final brief",
      status: "created",
      created_at: NOW,
      workspace_relative_path: "storage/generated/final.md",
      partial_output: groupChat ? "Synthesizer draft before final answer." : "Reviewer draft before final synthesis.",
    },
  ];
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
    const inputText = typeof body.input_text === "string" ? body.input_text : "";
    const turn = runtimeTurn("turn-followup", sessionId, "completed", inputText);
    const events = runtimeTranscriptEvents(
      sessionId,
      turn.turn_id,
      inputText,
      "Follow-up answer from the browser harness.",
      typeof body.client_message_id === "string" ? body.client_message_id : undefined,
    );
    const thread =
      state.threads.find((item) => item.runtime_session_id === sessionId) ||
      chatThread({
        availability: "free",
        last_user_message_at: NOW,
        runtime_session_id: sessionId,
        thread_id: sessionId,
        title: "Launch notes",
      });
    state.threads = [thread, ...state.threads.filter((item) => item.thread_id !== thread.thread_id)];
    state.runtimeSessionEvents[sessionId] = [...(state.runtimeSessionEvents[sessionId] || []), ...events];
    state.runtimeSessionTurns[sessionId] = [...(state.runtimeSessionTurns[sessionId] || []), turn];
    await fulfillJson(route, { session: runtimeSession(sessionId), thread, turn, events });
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
  if (url.pathname === "/api/inter-agent/orchestrations" && request.method() === "POST") {
    const body = postBody(route);
    const policy = typeof body.policy === "string" ? body.policy : "auto";
    const sourceTurnId = typeof body.source_runtime_turn_id === "string" ? body.source_runtime_turn_id : "turn-normal";
    state.createOrchestrationBodies.push(body);
    state.runCreated = true;
    const initialDetail = interAgentRunDetail({
      materialized: false,
      run: { status: "planning", orchestration_policy: policy, source_runtime_turn_id: sourceTurnId },
    });
    state.runDetail = interAgentRunDetail({
      run: { status: "running", orchestration_policy: policy, source_runtime_turn_id: sourceTurnId },
    });
    state.runEvents = interAgentEventsForMode(policy);
    state.runArtifacts = interAgentArtifactsForMode(policy);
    await fulfillJson(route, initialDetail, 202);
    return;
  }
  if (url.pathname === "/api/inter-agent/runs" && request.method() === "POST") {
    const body = postBody(route);
    state.createRunBodies.push(body);
    await fulfillJson(route, { error: "legacy_static_run_api_forbidden" }, 410);
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
      await fulfillJson(route, { error: "root_projection_execution_forbidden" }, 410);
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
    if (action === "participants" && parts[6] === "transcript" && request.method() === "GET") {
      const participantId = decodeURIComponent(parts[5] || "orchestrator");
      await fulfillJson(route, participantTranscriptPayload(state, participantId));
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

function interAgentRunDetail(overrides: { materialized?: boolean; run?: JsonRecord } = {}): InterAgentRunDetail {
  const run = {
    run_id: RUN_ID,
    workspace_id: WORKSPACE_ID,
    thread_id: THREAD_ID,
    root_runtime_session_id: RUNTIME_SESSION_ID,
    source_runtime_turn_id: "turn-normal",
    source_app_id: "chat",
    mode: "orchestrated",
    orchestration_policy: "multi",
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
  const groupChat = run.orchestration_policy === "group_chat";
  const orchestrator = interAgentParticipant(
    "orchestrator",
    "orchestrator",
    "child_runtime_session",
    "Orchestrator",
    overrides.materialized === false ? null : "child-orchestrator",
    "running",
    0,
  );
  return {
    run,
    participants: overrides.materialized === false
      ? [orchestrator]
      : groupChat
      ? [
          orchestrator,
          interAgentParticipant("analyst", "agent", "child_runtime_session", "Analyst", "child-analyst", "completed", 1),
          interAgentParticipant("reviewer", "agent", "child_runtime_session", "Reviewer", "child-reviewer", "completed", 2),
          interAgentParticipant("synthesizer", "agent", "child_runtime_session", "Synthesizer", "child-synthesizer", "running", 3),
        ]
      : [
          orchestrator,
          interAgentParticipant("implementer", "agent", "child_runtime_session", "Implementer", "child-implementer", "completed", 1),
          interAgentParticipant("reviewer", "agent", "child_runtime_session", "Reviewer", "child-reviewer", "running", 2),
        ],
    edges: overrides.materialized === false
      ? []
      : groupChat
      ? [
          interAgentEdge("edge-analysis", "orchestrator", "analyst", "delegated", "Analysis"),
          interAgentEdge("edge-review", "orchestrator", "reviewer", "delegated", "Review"),
          interAgentEdge("edge-analyst-synth", "analyst", "synthesizer", "depends_on", "Contribution"),
          interAgentEdge("edge-reviewer-synth", "reviewer", "synthesizer", "depends_on", "Correction"),
          interAgentEdge("edge-final-synthesis", "synthesizer", "orchestrator", "produced", "Final synthesis"),
        ]
      : [
          interAgentEdge("edge-implementation", "orchestrator", "implementer", "delegated", "Implementation"),
          interAgentEdge("edge-review", "implementer", "reviewer", "reviewed_by", "Review"),
          interAgentEdge("edge-final-review", "reviewer", "orchestrator", "produced", "Final review"),
        ],
    budget_policy: {
      budget_policy_id: "budget-chat-e2e",
      workspace_id: WORKSPACE_ID,
      max_participants: groupChat ? 9 : 7,
      max_concurrent_participants: groupChat ? 3 : 2,
      max_handoffs: 3,
      max_rounds: 3,
      max_total_turns: groupChat ? 14 : 12,
      max_turns_per_participant: 4,
      max_tool_calls: groupChat ? 24 : 20,
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
    thread_visibility: executionMode === "child_runtime_session" ? "hidden" : "user",
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

function participantTranscriptPayload(state: MockState, participantId: string) {
  const participant =
    state.runDetail.participants.find((item) => item.participant_id === participantId) ||
    interAgentParticipant(participantId, "agent", "child_runtime_session", participantId, null, "running", 99);
  const label = String(participant.label || participantId);
  const outputItems = participantId === "reviewer"
    ? [
        {
          message_id: `${participantId}:output:research`,
          kind: "output",
          role: "participant",
          text: "Reviewing launch sources.",
          status: "completed",
          created_at: "2026-06-18T10:00:01Z",
        },
        {
          message_id: `${participantId}:tool:web-search`,
          kind: "tool",
          role: "tool",
          text: "Tool Used",
          status: "completed",
          created_at: "2026-06-18T10:00:02Z",
          tool_call: {
            id: "tool-1",
            name: "web_search",
            status: "completed",
            detail: { tool_kind: "web_search", query: "launch risks", summary: "Web search" },
          },
        },
        {
          message_id: `${participantId}:output:final`,
          kind: "output",
          role: "participant",
          text: "Final risk review ready.",
          status: "completed",
          created_at: "2026-06-18T10:00:03Z",
        },
      ]
    : [
        {
          message_id: `${participantId}:output`,
          kind: "output",
          role: "participant",
          text: `${label} produced a safe participant summary.`,
          status: "completed",
          created_at: NOW,
        },
      ];
  const items = [
    {
      message_id: `${participantId}:input`,
      kind: "input",
      role: "user",
      text: `${label} accepted browser-observed task.`,
      status: "completed",
      created_at: NOW,
    },
    ...outputItems,
  ];
  return {
    run_id: RUN_ID,
    participant: {
      participant_id: participantId,
      kind: participant.kind,
      label,
      status: participant.status,
    },
    visibility_plane: "detail",
    items,
    item_count: items.length,
    truncated: false,
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
