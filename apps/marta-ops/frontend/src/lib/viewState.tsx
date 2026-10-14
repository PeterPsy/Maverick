import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";

type ViewState = Record<string, unknown>;
const Context = createContext<{
  values: ViewState;
  setValues: Dispatch<SetStateAction<ViewState>>;
} | null>(null);

// Keep filters in this app mount only; a workspace remount starts fresh.
export function ViewStateProvider({ children }: { children: ReactNode }) {
  const [values, setValues] = useState<ViewState>({});
  const context = useMemo(() => ({ values, setValues }), [values]);
  return <Context.Provider value={context}>{children}</Context.Provider>;
}

export function useViewState<T>(
  key: string,
  initial: T,
): [T, Dispatch<SetStateAction<T>>] {
  const context = useContext(Context);
  const [local, setLocal] = useState(initial);
  const setValues = context?.setValues;
  const setValue = useCallback(
    (next: SetStateAction<T>) => {
      if (!setValues) {
        setLocal(next);
        return;
      }
      setValues((values) => {
        const current = key in values ? (values[key] as T) : initial;
        const updated =
          typeof next === "function"
            ? (next as (previous: T) => T)(current)
            : next;
        return Object.is(current, updated)
          ? values
          : { ...values, [key]: updated };
      });
    },
    [key, initial, setValues],
  );
  const value =
    context && key in context.values
      ? (context.values[key] as T)
      : context
        ? initial
        : local;
  return [value, setValue];
}
