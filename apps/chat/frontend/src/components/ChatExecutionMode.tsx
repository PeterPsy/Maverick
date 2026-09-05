import { useEffect, useState, type ReactNode } from "react";
import { requestLocalRuntime } from "../lib/localRuntime";
import { LocalMacChat } from "./LocalMacChat";

export function ChatExecutionMode({ children }: { children: ReactNode }) {
  const [available, setAvailable] = useState(false);
  const [local, setLocal] = useState(false);
  useEffect(() => {
    let live = true;
    void requestLocalRuntime("status").then((value) => { if (live) setAvailable(value.available); }).catch(() => undefined);
    return () => { live = false; };
  }, []);
  return <div className="chatapp-execution-mode">
    {available ? <nav className="chatapp-local-mode" aria-label="Esecuzione">
      <button type="button" aria-pressed={!local} onClick={() => setLocal(false)}>Sul server</button>
      <button type="button" aria-pressed={local} onClick={() => setLocal(true)}>Su questo Mac</button>
    </nav> : null}
    {local ? <LocalMacChat /> : children}
  </div>;
}
