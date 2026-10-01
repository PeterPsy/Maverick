import { useCallback, useEffect, useRef, useState } from "react";
import { connectAppEventSocket } from "@maverick/pwa-cache";
import { mountedAppIdFromPath } from "./lib/shellNavigation";
import { callBackend } from "./api";
import type { BackendPayload, MartaOpsState } from "./types";

const EMPTY_STATE: MartaOpsState = {
  schema_version: "3",
  collaborations: [],
  ideas: [],
  contacts: [],
  tasks: [],
  activity: [],
  integration_options: {
    mail_provider_app_id: "",
    calendar_provider_app_id: "",
    storage_provider_app_id: "",
    mail_connections: [],
    calendar_connections: [],
    calendar_calendars: [],
    refreshed_at: "",
  },
  integration_preferences: {
    mail_connection_id: "",
    calendar_connection_id: "",
    calendar_id: "",
  },
};

export function useMartaOps() {
  const [state, setState] = useState<MartaOpsState>(EMPTY_STATE);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const revision = useRef(0);
  const reads = useRef(0);
  const pending = useRef(false);
  const queuedRefresh = useRef(false);

  const refresh = useCallback(async () => {
    if (pending.current) {
      queuedRefresh.current = true;
      return;
    }
    queuedRefresh.current = false;
    const version = revision.current;
    const request = ++reads.current;
    try {
      const payload = await callBackend<BackendPayload>({
        action: "bootstrap",
      });
      if (
        version === revision.current &&
        request === reads.current &&
        !pending.current
      )
        setState(payload.state);
    } catch (loadError) {
      if (version === revision.current && request === reads.current)
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Impossibile caricare Marta Ops.",
        );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    return connectAppEventSocket<{
      type?: string;
      owner_app_id?: string;
      resource?: string;
    }>(
      (message) => {
        if (
          message.type === "maverick.app.data-changed" &&
          message.owner_app_id === mountedAppIdFromPath() &&
          message.resource === "state"
        ) {
          void refresh();
        }
      },
      () => {
        void refresh();
      },
    );
  }, [refresh]);

  const mutate = useCallback(
    async (body: Record<string, unknown>) => {
      if (pending.current) throw new Error("Attendi il salvataggio in corso.");
      pending.current = true;
      revision.current += 1;
      setSaving(true);
      try {
        const payload = await callBackend<BackendPayload>(body);
        setState(payload.state);
        setError("");
        return payload;
      } catch (mutationError) {
        const message =
          mutationError instanceof Error
            ? mutationError.message
            : "Operazione non riuscita.";
        setError(message);
        throw mutationError;
      } finally {
        pending.current = false;
        revision.current += 1;
        setSaving(false);
        if (queuedRefresh.current) void refresh();
      }
    },
    [refresh],
  );

  const integrate = useCallback(
    async (body: Record<string, unknown>) => {
      if (pending.current) throw new Error("Attendi il salvataggio in corso.");
      pending.current = true;
      revision.current += 1;
      setSaving(true);
      try {
        const payload = await callBackend<BackendPayload>(body);
        const results = payload.dependency_backend_request_results || [];
        const failed = results.find(
          (result) =>
            result.status !== "completed" ||
            result.status_code >= 400 ||
            (result.callback_status_code !== undefined &&
              result.callback_status_code !== 200),
        );
        if (!results.length || failed) {
          const isMail = body.action === "create_mail_draft";
          const isStorage = body.action === "link_storage_file";
          const isRefresh = body.action === "refresh_integrations";
          throw new Error(
            isMail
              ? "Impossibile creare la bozza. Apri Mail, verifica l’account e riprova."
              : isStorage
                ? "Impossibile collegare il file. Verifica Storage e riprova."
                : isRefresh
                  ? "Impossibile aggiornare le connessioni Mail, Calendario e Storage."
                  : "Impossibile aggiornare l’evento. Verifica Calendario e riprova.",
          );
        }
        setState(payload.state);
        setError("");
        return results;
      } catch (integrationError) {
        const message =
          integrationError instanceof Error
            ? integrationError.message
            : "Integrazione non riuscita.";
        setError(message);
        throw integrationError;
      } finally {
        pending.current = false;
        revision.current += 1;
        setSaving(false);
        if (queuedRefresh.current) void refresh();
      }
    },
    [refresh],
  );

  return {
    state,
    loading,
    saving,
    error,
    clearError: () => setError(""),
    integrate,
    mutate,
    refresh,
  };
}
