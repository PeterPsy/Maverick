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

  it("uses the same material language glyph for the Browser app", () => {
    expect(renderedLogo("browser")).toContain(">language<");
  });
});
