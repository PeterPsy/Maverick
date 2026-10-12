import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AppRegistryItem } from "../src/api";
import { AppLogo } from "../src/components/AppLogo";

function app(app_id: string): AppRegistryItem {
  return {
    app_id,
    backend_mount: "",
    description: "",
    distribution_mode: "sealed",
    frontend_mount: `/apps/${app_id}/`,
    frontend_role: "workspace",
    frontend_launchable: true,
    logo: null,
    name: app_id,
    publisher: "maverick",
    source_access: "none",
    status: "enabled",
    version: "1.0.0",
    provides: [],
    requires: [],
    views: [],
  };
}

function renderedLogo(appId: string): string {
  return renderToStaticMarkup(<AppLogo app={app(appId)} />);
}

describe("AppLogo", () => {
  it("uses an app-owned compact silhouette with the native theme colour", () => {
    const custom = { ...app("example"), logo: { kind: "image" as const, value: "/apps/example/maverick-icon-compact.png" } };
    const markup = renderToStaticMarkup(<AppLogo app={custom} className="bs-app-logo--rail" />);
    expect(markup).toContain("is-glyph");
    expect(markup).toContain("bs-app-logo__compact");
    expect(markup).toContain("background-color:currentColor");
    expect(markup).toContain("mask:");
    expect(markup).toContain("/apps/example/maverick-icon-compact.png");
    expect(markup).not.toContain("<img");
  });

  it("preserves full-colour external image logos", () => {
    const custom = { ...app("example"), logo: { kind: "image" as const, value: "https://cdn.example/logo.png" } };
    const markup = renderToStaticMarkup(<AppLogo app={custom} />);
    expect(markup).toContain("is-image");
    expect(markup).toContain('<img');
    expect(markup).toContain('src="https://cdn.example/logo.png"');
  });

  it("uses the document glyph for Docs Studio and Document Generator", () => {
    expect(renderedLogo("docs-studio")).toBe(renderedLogo("document-generator"));
    expect(renderedLogo("docs-studio")).toContain(">description<");
  });

  it("uses a speech glyph for the Speech provider app", () => {
    expect(renderedLogo("speech")).toContain(">record_voice_over<");
  });

  it("uses the same material mail glyph for the Mail app", () => {
    expect(renderedLogo("mail")).toContain(">mail<");
  });

  it("uses the kanban glyph for Marta Ops", () => {
    expect(renderedLogo("marta-ops")).toContain(">view_kanban<");
  });

  it("uses the same material language glyph for the Browser app", () => {
    expect(renderedLogo("browser")).toContain(">language<");
  });

  it("uses the fitness glyph for Fitness Coach", () => {
    expect(renderedLogo("fitness-coach")).toContain(">fitness_center<");
  });

  it("uses the design services glyph for Design Studio", () => {
    expect(renderedLogo("design-studio")).toContain(">design_services<");
  });

  it("uses the sensors glyph for Senses", () => {
    expect(renderedLogo("senses")).toContain(">sensors<");
  });
});
