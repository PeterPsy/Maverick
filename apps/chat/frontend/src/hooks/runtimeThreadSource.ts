import type { RuntimeThreadWebSocketFrame } from "../api/client";
import { runtimeThreadWebSocketUrl } from "../api/client";

type RuntimeThreadSourceMessage =
  | { kind: "hello"; client_id: string; tab_id: string }
  | { kind: "source-claim"; client_id: string; tab_id: string }
  | { kind: "source-ready"; client_id: string; tab_id: string }
  | { kind: "source-closed"; client_id: string; tab_id: string }
  | { kind: "frame"; client_id: string; tab_id: string; frame: RuntimeThreadWebSocketFrame };

type RuntimeThreadSourceSubscriber = {
  onError: (message: string | null) => void;
  onFrame: (frame: RuntimeThreadWebSocketFrame) => void;
};

type RuntimeThreadSourceOptions = {
  followerTimeoutMs?: number;
  leaderElectionDelayMs?: number;
};

const CHANNEL_NAME = "maverick.chat.runtime-thread-source.v1";
const TAB_ID_STORAGE_KEY = "maverick.chat.runtime-thread-tab-id";
const INITIAL_RECONNECT_DELAY_MS = 500;
const MAX_RECONNECT_DELAY_MS = 10000;
const DEFAULT_LEADER_ELECTION_DELAY_MS = 80;
const DEFAULT_FOLLOWER_TIMEOUT_MS = 65000;

function randomId(prefix: string): string {
  const random = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : Math.random().toString(36).slice(2);
  return `${prefix}-${Date.now().toString(36)}-${random}`;
}

function runtimeThreadTabId(): string {
  try {
    const existing = window.sessionStorage.getItem(TAB_ID_STORAGE_KEY);
    if (existing) {
      return existing;
    }
    const tabId = randomId("tab");
    window.sessionStorage.setItem(TAB_ID_STORAGE_KEY, tabId);
    return tabId;
  } catch {
    return "";
  }
}

function hasBroadcastChannel(): boolean {
  return typeof BroadcastChannel !== "undefined";
}

export class RuntimeThreadSource {
  private readonly clientId = randomId("runtime-thread-source");
  private readonly followerTimeoutMs: number;
  private readonly leaderElectionDelayMs: number;
  private readonly subscribers = new Map<number, RuntimeThreadSourceSubscriber>();
  private channel: BroadcastChannel | null = null;
  private followerWatchdogTimer: number | null = null;
  private heartbeatTimer: number | null = null;
  private isLeader = false;
  private knownClientIds = new Set<string>();
  private lastFrameAt = Date.now();
  private leaderElectionTimer: number | null = null;
  private nextSubscriberId = 1;
  private reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS;
  private reconnectTimer: number | null = null;
  private socket: WebSocket | null = null;
  private sourceClientId: string | null = null;
  private started = false;
  private stopped = true;
  private tabId = "";

  constructor(options: RuntimeThreadSourceOptions = {}) {
    this.followerTimeoutMs = options.followerTimeoutMs ?? DEFAULT_FOLLOWER_TIMEOUT_MS;
    this.leaderElectionDelayMs = options.leaderElectionDelayMs ?? DEFAULT_LEADER_ELECTION_DELAY_MS;
  }

  subscribe(subscriber: RuntimeThreadSourceSubscriber): () => void {
    const subscriberId = this.nextSubscriberId;
    this.nextSubscriberId += 1;
    this.subscribers.set(subscriberId, subscriber);
    if (!this.started) {
      this.start();
    }
    return () => {
      this.subscribers.delete(subscriberId);
      if (!this.subscribers.size) {
        this.stop();
      }
    };
  }

  private start() {
    this.started = true;
    this.stopped = false;
    this.isLeader = false;
    this.sourceClientId = null;
    this.knownClientIds = new Set([this.clientId]);
    this.tabId = runtimeThreadTabId();
    if (this.tabId && hasBroadcastChannel()) {
      this.channel = new BroadcastChannel(CHANNEL_NAME);
      this.channel.onmessage = (event: MessageEvent<RuntimeThreadSourceMessage>) => this.handleChannelMessage(event.data);
      this.post({ kind: "hello" });
      this.scheduleLeaderElection();
      return;
    }
    this.becomeLeader();
  }

  private stop() {
    this.stopped = true;
    this.started = false;
    this.clearLeaderElection();
    this.clearFollowerWatchdog();
    this.clearReconnect();
    this.stopHeartbeatWatchdog();
    if (this.isLeader) {
      this.post({ kind: "source-closed" });
    }
    this.isLeader = false;
    this.sourceClientId = null;
    this.socket?.close();
    this.socket = null;
    this.channel?.close();
    this.channel = null;
  }

  private handleChannelMessage(message: RuntimeThreadSourceMessage | unknown) {
    if (!this.isRuntimeThreadSourceMessage(message) || message.client_id === this.clientId || message.tab_id !== this.tabId) {
      return;
    }
    const knownPeer = this.knownClientIds.has(message.client_id);
    this.knownClientIds.add(message.client_id);
    if (message.kind === "hello") {
      if (!knownPeer) {
        this.post({ kind: "hello" });
      }
      if (this.isLeader) {
        this.post({ kind: "source-ready" });
      }
      return;
    }
    if (message.kind === "source-claim" || message.kind === "source-ready") {
      this.acceptSourceCandidate(message.client_id);
      return;
    }
    if (message.kind === "source-closed") {
      if (this.sourceClientId === message.client_id) {
        this.sourceClientId = null;
        this.scheduleLeaderElection();
      }
      return;
    }
    if (message.kind === "frame" && !this.isLeader) {
      this.sourceClientId = message.client_id;
      this.lastFrameAt = Date.now();
      this.clearLeaderElection();
      this.startFollowerWatchdog();
      this.notifyFrame(message.frame);
    }
  }

  private acceptSourceCandidate(clientId: string) {
    if (this.isLeader) {
      if (clientId < this.clientId) {
        this.becomeFollower(clientId);
        return;
      }
      this.post({ kind: "source-ready" });
      return;
    }
    this.sourceClientId = clientId;
    this.clearLeaderElection();
    this.startFollowerWatchdog();
  }

  private becomeFollower(sourceClientId: string) {
    this.isLeader = false;
    this.sourceClientId = sourceClientId;
    this.clearReconnect();
    this.stopHeartbeatWatchdog();
    this.socket?.close();
    this.socket = null;
    this.startFollowerWatchdog();
  }

  private scheduleLeaderElection() {
    if (this.stopped || !this.subscribers.size) {
      return;
    }
    this.clearLeaderElection();
    this.leaderElectionTimer = window.setTimeout(() => this.electLeader(), this.leaderElectionDelayMs);
  }

  private electLeader() {
    this.leaderElectionTimer = null;
    if (this.stopped || !this.subscribers.size) {
      return;
    }
    if (this.sourceClientId && this.sourceClientId !== this.clientId) {
      this.startFollowerWatchdog();
      return;
    }
    const leaderId = Array.from(this.knownClientIds).sort()[0] || this.clientId;
    if (leaderId === this.clientId) {
      this.becomeLeader();
      return;
    }
    this.sourceClientId = leaderId;
    this.startFollowerWatchdog();
  }

  private becomeLeader() {
    if (this.isLeader || this.stopped) {
      return;
    }
    this.isLeader = true;
    this.sourceClientId = this.clientId;
    this.clearFollowerWatchdog();
    this.post({ kind: "source-claim" });
    this.connect();
  }

  private connect() {
    if (this.stopped || !this.isLeader) {
      return;
    }
    if (typeof WebSocket === "undefined") {
      this.notifyError("Runtime thread WebSocket is unavailable.");
      this.post({ kind: "source-closed" });
      this.isLeader = false;
      return;
    }
    let socketOpened = false;
    const socket = new WebSocket(runtimeThreadWebSocketUrl());
    this.socket = socket;
    socket.onopen = () => {
      if (this.socket !== socket || !this.isLeader) {
        return;
      }
      socketOpened = true;
      this.lastFrameAt = Date.now();
      this.reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS;
      this.startHeartbeatWatchdog();
      this.notifyError(null);
      this.post({ kind: "source-ready" });
    };
    socket.onmessage = (event) => {
      if (this.socket !== socket || !this.isLeader) {
        return;
      }
      this.lastFrameAt = Date.now();
      try {
        const frame = JSON.parse(event.data) as RuntimeThreadWebSocketFrame;
        this.notifyFrame(frame);
        this.post({ kind: "frame", frame });
      } catch (parseError) {
        this.notifyError(parseError instanceof Error ? parseError.message : "Unable to parse runtime thread WebSocket frame.");
      }
    };
    socket.onerror = () => {
      if (!socketOpened) {
        this.notifyError("Runtime thread WebSocket is unavailable.");
      }
    };
    socket.onclose = (event) => {
      if (this.socket !== socket) {
        return;
      }
      this.stopHeartbeatWatchdog();
      this.socket = null;
      if (this.stopped || !this.isLeader) {
        return;
      }
      if (event.code === 4401 || event.code === 4404) {
        this.notifyError(event.code === 4401 ? "Runtime thread stream is not authorized." : "Runtime thread stream is unavailable.");
        this.post({ kind: "source-closed" });
        this.isLeader = false;
        return;
      }
      this.reconnectTimer = window.setTimeout(() => this.connect(), this.reconnectDelayMs);
      this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, MAX_RECONNECT_DELAY_MS);
    };
  }

  private startHeartbeatWatchdog() {
    this.stopHeartbeatWatchdog();
    this.heartbeatTimer = window.setInterval(() => {
      if (Date.now() - this.lastFrameAt > 60000) {
        this.socket?.close();
      }
    }, 10000);
  }

  private stopHeartbeatWatchdog() {
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private startFollowerWatchdog() {
    this.clearFollowerWatchdog();
    this.followerWatchdogTimer = window.setTimeout(() => {
      if (this.stopped || this.isLeader) {
        return;
      }
      this.sourceClientId = null;
      this.scheduleLeaderElection();
    }, this.followerTimeoutMs);
  }

  private clearFollowerWatchdog() {
    if (this.followerWatchdogTimer !== null) {
      window.clearTimeout(this.followerWatchdogTimer);
      this.followerWatchdogTimer = null;
    }
  }

  private clearLeaderElection() {
    if (this.leaderElectionTimer !== null) {
      window.clearTimeout(this.leaderElectionTimer);
      this.leaderElectionTimer = null;
    }
  }

  private clearReconnect() {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private notifyError(message: string | null) {
    for (const subscriber of this.subscribers.values()) {
      subscriber.onError(message);
    }
  }

  private notifyFrame(frame: RuntimeThreadWebSocketFrame) {
    for (const subscriber of this.subscribers.values()) {
      subscriber.onFrame(frame);
    }
  }

  private post(
    message:
      | { kind: "hello" }
      | { kind: "source-claim" }
      | { kind: "source-ready" }
      | { kind: "source-closed" }
      | { kind: "frame"; frame: RuntimeThreadWebSocketFrame },
  ) {
    if (!this.channel || !this.tabId) {
      return;
    }
    this.channel.postMessage({ ...message, client_id: this.clientId, tab_id: this.tabId });
  }

  private isRuntimeThreadSourceMessage(message: RuntimeThreadSourceMessage | unknown): message is RuntimeThreadSourceMessage {
    if (!message || typeof message !== "object") {
      return false;
    }
    const candidate = message as Partial<RuntimeThreadSourceMessage>;
    return typeof candidate.kind === "string" && typeof candidate.client_id === "string" && typeof candidate.tab_id === "string";
  }
}

let runtimeThreadSource: RuntimeThreadSource | null = null;

export function getRuntimeThreadSource(): RuntimeThreadSource {
  if (runtimeThreadSource === null) {
    runtimeThreadSource = new RuntimeThreadSource();
  }
  return runtimeThreadSource;
}

export function resetRuntimeThreadSourceForTests() {
  runtimeThreadSource = null;
}
