import { useEffect, useState } from "react";
import { getRuntimeThread, type ChatThread, type DeviceUseThreadBinding } from "../api/client";

function completeBinding(binding: DeviceUseThreadBinding | null | undefined): boolean {
  return Boolean(binding?.activation_id && binding.mode === "full");
}

// Older cached display catalogs contain only the Device Use classifier. Read
// the authorized thread detail before selecting its immutable native mode.
export function useDeviceUseThreadBinding(thread: ChatThread | null) {
  const key = `${thread?.thread_id || ""}:${thread?.runtime_session_id || ""}`;
  const projected = thread?.device_use_enabled ? thread.device_use : null;
  const hasProjection = completeBinding(projected);
  const [resolved, setResolved] = useState<{
    key: string; binding: DeviceUseThreadBinding | null; error: string | null;
  } | null>(null);

  useEffect(() => {
    if (!thread?.device_use_enabled || hasProjection) return;
    let cancelled = false;
    setResolved(null);
    void getRuntimeThread(thread.thread_id).then((detail) => {
      if (cancelled) return;
      if (detail.thread_id !== thread.thread_id
          || detail.runtime_session_id !== thread.runtime_session_id
          || !detail.device_use_enabled || !completeBinding(detail.device_use)) {
        throw new Error("Modalità Device Use originale non disponibile. Riapri questa chat.");
      }
      setResolved({ key, binding: detail.device_use!, error: null });
    }).catch(() => {
      if (!cancelled) setResolved({ key, binding: null,
        error: "Impossibile leggere la modalità Device Use originale. Riapri questa chat." });
    });
    return () => { cancelled = true; };
  }, [key, thread?.device_use_enabled, hasProjection]);

  return {
    binding: hasProjection ? projected! : resolved?.key === key ? resolved.binding : null,
    error: resolved?.key === key && !hasProjection ? resolved.error : null,
  };
}
