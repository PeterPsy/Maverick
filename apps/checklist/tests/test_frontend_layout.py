from __future__ import annotations

import re
from pathlib import Path
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]


def css_block(styles: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}", styles)
    if not match:
        raise AssertionError(f"Missing CSS block for {selector}")
    return match.group("body")


class ChecklistFrontendLayoutTest(unittest.TestCase):
    def test_main_view_scrolls_as_one_surface(self) -> None:
        styles = (APP_ROOT / "frontend" / "src" / "styles" / "main.css").read_text(encoding="utf-8")

        body = css_block(styles, "body")
        app = css_block(styles, ".checklist-app")
        plans_view = css_block(styles, ".checklist-plans-view")
        plans_grid = css_block(styles, ".checklist-plans-grid")
        detail_board = css_block(styles, ".checklist-detail-board")

        self.assertIn("scrollbar-width: none;", body)
        self.assertIn("body::-webkit-scrollbar", styles)
        self.assertIn("overflow: auto;", app)
        self.assertIn("scrollbar-width: none;", app)
        self.assertIn(".checklist-app::-webkit-scrollbar", styles)
        self.assertNotIn("height: 100%;", plans_view)
        self.assertNotIn("grid-template-rows: auto minmax(0, 1fr);", plans_view)
        self.assertIn("overflow: visible;", plans_grid)
        self.assertNotIn("overflow-y: auto;", plans_grid)
        self.assertIn("overflow: visible;", detail_board)

    def test_plan_component_does_not_create_full_height_scroll_area(self) -> None:
        source = (
            APP_ROOT / "frontend" / "src" / "components" / "ui" / "agent-plan.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("agent-plan-frame bg-background text-foreground min-h-0 p-2", source)
        self.assertIn('compact ? "is-compact" : ""', source)
        self.assertNotIn("h-full overflow-auto", source)

    def test_chat_widget_owns_transient_overlay_scrolling(self) -> None:
        styles = (APP_ROOT / "frontend" / "src" / "styles" / "main.css").read_text(encoding="utf-8")
        source = (APP_ROOT / "frontend" / "src" / "widget.tsx").read_text(encoding="utf-8")
        scrollbar_source = (
            APP_ROOT / "frontend" / "src" / "components" / "useTransientOverlayScrollbar.ts"
        ).read_text(encoding="utf-8")

        widget_root = css_block(styles, ".checklist-widget-body,\n.checklist-widget-body #root")
        widget_frame = css_block(styles, ".checklist-widget-frame")
        widget_scroll = css_block(styles, ".checklist-widget-scroll")
        compact_plan = css_block(styles, ".agent-plan-frame.is-compact .agent-plan-frame__surface")

        self.assertIn("height: 100%;", widget_root)
        self.assertIn("overflow: hidden;", widget_root)
        self.assertIn("height: 100%;", widget_frame)
        self.assertIn("overflow: hidden;", widget_frame)
        self.assertIn("overflow-y: auto;", widget_scroll)
        self.assertIn("scrollbar-width: none;", widget_scroll)
        self.assertIn(".checklist-widget-scrollbar.is-scrolling", styles)
        self.assertIn(".checklist-widget-scrollbar__thumb", styles)
        self.assertIn("border: 0;", compact_plan)
        self.assertIn("background: transparent;", compact_plan)
        self.assertIn("onScroll={handleScroll}", source)
        self.assertIn("useTransientOverlayScrollbar", source)
        self.assertIn("setIsScrolling(false)", scrollbar_source)
        self.assertIn("SCROLL_IDLE_DELAY_MS", scrollbar_source)

    def test_loading_skeleton_uses_same_whole_surface_scroll_model(self) -> None:
        styles = (APP_ROOT / "frontend" / "src" / "styles" / "skeleton.css").read_text(encoding="utf-8")

        detail_skeleton = css_block(styles, ".checklist-detail-skeleton")
        detail_board = css_block(styles, ".checklist-loading-skeleton__detail-board")
        plan_skeleton = css_block(styles, ".checklist-plan-skeleton")

        self.assertNotIn("height: 100%;", detail_skeleton)
        self.assertNotIn("grid-template-rows: auto minmax(0, 1fr);", detail_skeleton)
        self.assertIn("overflow: visible;", detail_board)
        self.assertIn("height: auto;", plan_skeleton)
        self.assertIn("overflow: visible;", plan_skeleton)
