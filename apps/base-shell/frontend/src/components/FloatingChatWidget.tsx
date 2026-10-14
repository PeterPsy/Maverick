import { useMemo, type ComponentProps } from "react";
import type { FloatingChatHost } from "./FloatingChatHost";
import { WidgetSlot } from "./WidgetSlot";
import { appLogoPresentation } from "./AppLogo";

export type FloatingChatPlacement = "overlay" | "fixed-right" | "mobile-fullscreen";

type Props = Pick<ComponentProps<typeof FloatingChatHost>,
  "activeApp" | "activeAppParams" | "activeWorkspaceId" | "frameScope" | "navigationScope" |
  "onActiveThreadChange" | "onCloseDock" | "onCloseMobileChat" | "onOpenApp" | "onOpenDock" |
  "shellTheme" | "threadId" | "user"
> & { placement: FloatingChatPlacement; visible: boolean };

/** Placement changes update context without replacing the app-owned document. */
export function FloatingChatWidget({ placement, visible, ...props }: Props) {
  const isDockMode = placement === "fixed-right";
  const isMobileMode = placement === "mobile-fullscreen";
  const content = useMemo(() => ({
    active_app: props.activeApp ? {
      app_id: props.activeApp.app_id,
      description: props.activeApp.description,
      logo: appLogoPresentation(props.activeApp),
      name: props.activeApp.name,
      params: props.activeAppParams,
      views: props.activeApp.views,
    } : null,
    mode: placement,
    navigation_scope: props.navigationScope || "",
    placement: isDockMode ? "right" : isMobileMode ? "mobile-fullscreen" : "bottom-right",
    thread_id: props.threadId || "",
    user: props.user?.username || null,
  }), [props.activeApp, props.activeAppParams, props.navigationScope, props.threadId, props.user?.username, placement]);

  return <div className="bs-floating-chat-host__widget" data-placement={placement} hidden={!visible} inert={!visible}>
    <WidgetSlot
      activeWorkspaceId={props.activeWorkspaceId}
      content={content}
      contentKind="shell.contextual.chat"
      frameScope={props.frameScope}
      hostAppId="base-shell"
      label={isDockMode ? "Right dock widget" : isMobileMode ? "Mobile chat widget" : "Floating chat widget"}
      isActive={visible}
      onActiveThreadChange={({ navigationScope, threadId }) => {
        if (visible) props.onActiveThreadChange({ navigationScope: navigationScope || props.navigationScope, threadId });
      }}
      onCloseDock={() => { if (visible) (isMobileMode ? props.onCloseMobileChat : props.onCloseDock)(); }}
      onOpenApp={(appId, params) => { if (visible) props.onOpenApp(appId, params); }}
      onOpenDock={(request) => { if (visible) props.onOpenDock(request); }}
      preferredOwnerAppId="chat"
      shellTheme={props.shellTheme}
      size={isDockMode || isMobileMode ? "fill" : "overlay"}
    />
  </div>;
}
