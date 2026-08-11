export type SourceAppPresentation = {
  icon: string;
  kind: "opendesign" | "senses" | "source_app";
  label: string;
};

export function isOpenDesignSourceApp(sourceAppId: string | null | undefined): boolean {
  return sourceAppId === "design-studio" || Boolean(sourceAppId?.endsWith("-design-studio"));
}

export function sourceAppPresentation(sourceAppId: string | null | undefined): SourceAppPresentation | null {
  const normalized = String(sourceAppId || "").trim();
  if (!normalized || normalized === "chat") {
    return null;
  }
  if (isOpenDesignSourceApp(normalized)) {
    return { icon: "design_services", kind: "opendesign", label: "OpenDesign" };
  }
  if (normalized === "senses" || normalized.endsWith("-senses")) {
    return { icon: "sensors", kind: "senses", label: "Senses" };
  }
  return {
    icon: "apps",
    kind: "source_app",
    label: humanizeAppId(normalized),
  };
}

function humanizeAppId(appId: string): string {
  return appId
    .split(/[-_]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}
