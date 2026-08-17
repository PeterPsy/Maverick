"""Tests for admin identity surfaces and app visibility."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import parse_app_contract_file
from core.apps.models import WorkspaceAppBindingRecord, WorkspaceLocalAppProjectRecord
from tests.support.markers import slow_test_class


class SettingsFrontendDistTests(unittest.TestCase):
    """Verify the bundled Settings frontend keeps the Maverick glass theme."""

    def test_frontend_dist_uses_maverick_glass_theme(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        css_files = sorted((app_root / "frontend" / "dist" / "assets").glob("*.css"))
        self.assertTrue(css_files)
        frontend_css = "\n".join(path.read_text(encoding="utf-8") for path in css_files)
        frontend_html = (app_root / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")

        self.assertIn("Settings", frontend_html)
        self.assertIn("color-scheme:dark", frontend_css)
        self.assertIn("--maverick-glass-surface", frontend_css)
        self.assertIn("backdrop-filter:blur(26px)", frontend_css)
        self.assertIn("@keyframes settings-progress-sheen", frontend_css)
        self.assertIn("@keyframes settings-loading-skeleton-shimmer", frontend_css)
        self.assertIn(".settings-platform", frontend_css)
        self.assertNotIn("--settings-primary:#d72451", frontend_css)

    def test_settings_declares_shell_sidebar_widget(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        widgets = {widget.widget_id: widget for widget in parsed.contract.widgets}
        sidebar_widget = widgets["settings-sidebar"]
        vite_source = (app_root / "vite.config.ts").read_text(encoding="utf-8")
        sidebar_source = (app_root / "frontend" / "src" / "widgets" / "settings-sidebar" / "main.ts").read_text(encoding="utf-8")

        self.assertIn("widget", parsed.contract.provides[0].surfaces)
        self.assertEqual(sidebar_widget.host, "base-shell")
        self.assertEqual(sidebar_widget.content_kinds, ["shell.sidebar.primary"])
        self.assertEqual(sidebar_widget.frontend.mount, "frontend/dist/widgets/settings-sidebar")
        self.assertTrue((app_root / "frontend" / "dist" / "widgets" / "settings-sidebar" / "index.html").is_file())
        self.assertIn("'widgets/settings-sidebar/index': 'frontend/widgets/settings-sidebar/index.html'", vite_source)
        self.assertIn("maverick.widget.open-app", sidebar_source)
        self.assertIn("maverick.shell.sidebar.close", sidebar_source)

    def test_settings_sidebar_uses_page_navigation(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        main_source = (app_root / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")
        pages_source = (app_root / "frontend" / "src" / "pages.ts").read_text(encoding="utf-8")
        sidebar_source = (app_root / "frontend" / "src" / "widgets" / "settings-sidebar" / "main.ts").read_text(encoding="utf-8")

        self.assertIn("SETTINGS_PAGES", sidebar_source)
        self.assertIn("Search pages", sidebar_source)
        self.assertIn("page_id", sidebar_source)
        self.assertNotIn("loadUsers", sidebar_source)
        self.assertIn("workspace-access", pages_source)
        self.assertIn("selectedPageId", main_source)
        self.assertIn("activePageHtml(page, user)", main_source)

    def test_app_links_copy_covers_speech_provider_interfaces(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        repo_root = app_root.parents[1]
        app_links_source = (app_root / "frontend" / "src" / "appLinksPage.ts").read_text(encoding="utf-8")
        pages_source = (app_root / "frontend" / "src" / "pages.ts").read_text(encoding="utf-8")
        chat_contract = parse_app_contract_file(repo_root / "apps" / "chat")
        speech_contract = parse_app_contract_file(repo_root / "apps" / "speech")
        chat_requirements = {item.alias: item for item in chat_contract.contract.requires}
        speech_interfaces = {item.interface for item in speech_contract.contract.provides}

        self.assertEqual(chat_requirements["text-to-speech"].interface, "speech.synthesis")
        self.assertIn("speech.synthesis", speech_interfaces)
        self.assertIn("speech: 'record_voice_over'", app_links_source)
        self.assertIn("Provider app links", app_links_source)
        self.assertIn("shared capabilities", pages_source)
        self.assertNotIn("Intra-app catalogs", app_links_source)

    def test_app_links_render_crm_mail_calendar_storage_dependencies(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        typescript_root = app_root / "node_modules" / "typescript"
        if not typescript_root.exists():
            self.skipTest("settings frontend dependencies are not installed")
        node_script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require(process.argv[2]);

const appRoot = process.argv[3];
const outDir = process.argv[4];

function transpile(sourcePath, outFile) {
  const source = fs.readFileSync(sourcePath, 'utf8');
  const result = ts.transpileModule(source, {
    fileName: sourcePath,
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
      moduleResolution: ts.ModuleResolutionKind.Node10,
      esModuleInterop: true,
      strict: true,
      skipLibCheck: true
    }
  });
  fs.writeFileSync(outFile, result.outputText);
}

transpile(path.join(appRoot, 'frontend/src/html.ts'), path.join(outDir, 'html.js'));
transpile(path.join(appRoot, 'frontend/src/appLinksPage.ts'), path.join(outDir, 'appLinksPage.js'));

const { appLinksPageHtml } = require(path.join(outDir, 'appLinksPage.js'));
const registry = [
  { app_id: 'agents', name: 'Agents', views: ['agents'], logo: { kind: 'glyph', value: 'smart_toy' } },
  { app_id: 'crm', name: 'CRM', views: ['crm'], logo: { kind: 'glyph', value: 'contacts' } },
  { app_id: 'mail', name: 'Mail', views: ['mail'], logo: { kind: 'glyph', value: 'mail' } },
  { app_id: 'calendar', name: 'Calendar', views: ['calendar'], logo: { kind: 'glyph', value: 'event' } },
  { app_id: 'storage', name: 'Storage', views: ['storage'], logo: { kind: 'glyph', value: 'cloud' } }
];
const workspaceApps = registry.map((item) => ({
  workspace_id: 'default',
  workspace_name: 'Default',
  app_id: item.app_id,
  name: item.name,
  description: '',
  version: '1.0.0',
  source_id: item.app_id,
  installed: true,
  status: 'enabled'
}));

function dependency(alias, providerAppId, providerName, providerInterface, description) {
  return {
    alias,
    interface: providerInterface,
    version: '^1.0.0',
    required: false,
    cardinality: 'one',
    description,
    status: 'optional_unset',
    selected_provider_app_ids: [],
    stale_provider_app_ids: [],
    blocked_reason: null,
    candidates: [{
      app_id: providerAppId,
      name: providerName,
      version: '1.0.0',
      interface: providerInterface,
      interface_version: '1.0.0',
      description,
      surfaces: ['cli', 'mcp']
    }]
  };
}

const html = appLinksPageHtml({
  appRegistry: registry,
  dependencies: [{
    workspace_id: 'default',
    consumer_app_id: 'agents',
    status: 'resolved',
    dependencies: [
      dependency('runtime-skills', 'agents', 'Agents', 'skill.catalog', 'Pick runtime skills.')
    ]
  }, {
    workspace_id: 'default',
    consumer_app_id: 'crm',
    status: 'resolved',
    dependencies: [
      dependency('mail', 'mail', 'Mail', 'mail.workspace', 'Search linked customer mail.'),
      dependency('calendar', 'calendar', 'Calendar', 'calendar.events', 'Create and link meetings.'),
      dependency('files', 'storage', 'Storage', 'file.catalog', 'Find linked files.'),
      dependency('file-preview', 'storage', 'Storage', 'file.preview', 'Open file previews.'),
      dependency('file-write', 'storage', 'Storage', 'file.content.write', 'Save generated briefs.')
    ]
  }],
  error: '',
  isLoading: false,
  loadErrors: [],
  page: {
    id: 'app-links',
    title: 'App links',
    summary: 'Choose provider apps for app interfaces and shared capabilities.',
    icon: 'hub'
  },
  savingKeys: new Set(),
  workspaceApps
});

for (const expected of [
  'CRM',
  'crm - resolved',
  'href="#settings-app-link-consumer-crm"',
  'id="settings-app-link-consumer-crm"',
  'mail.workspace',
  'calendar.events',
  'file.catalog',
  'file.preview',
  'file.content.write',
  'data-dependency-choice="crm:mail:mail"',
  'data-dependency-choice="crm:calendar:calendar"',
  'data-dependency-choice="crm:files:storage"',
  'data-dependency-choice="crm:file-preview:storage"',
  'data-dependency-choice="crm:file-write:storage"',
  'Mail',
  'Calendar',
  'Storage'
]) {
  assert.ok(html.includes(expected), `missing ${expected}`);
}
assert.equal((html.match(/storage - 1\.0\.0/g) || []).length, 3);
assert.ok((html.match(/auto default/g) || []).length >= 5);
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "app_links_crm_render_test.cjs"
            script_path.write_text(node_script, encoding="utf-8")
            result = subprocess.run(
                [
                    "node",
                    str(script_path),
                    str(typescript_root),
                    str(app_root),
                    temp_dir,
                ],
                cwd=app_root,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_settings_embeds_platform_settings_panel(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        main_source = (app_root / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")
        settings_source = (app_root / "frontend" / "src" / "settingsPanel.ts").read_text(encoding="utf-8")
        styles_source = (app_root / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        api_source = (app_root / "frontend" / "src" / "adminApi.ts").read_text(encoding="utf-8")

        self.assertIn("settingsPanelHtml(platformSettings, settingsPanelState)", main_source)
        self.assertIn("Platform settings", settings_source)
        self.assertIn("settings-user-settings-card", settings_source)
        self.assertIn("settings-hosted-text-model-settings-card", settings_source)
        self.assertIn("settings-agentic-model-settings-card", settings_source)
        self.assertIn("settings-speech-model-settings-card", settings_source)
        self.assertIn("settings-runtime-settings-card", settings_source)
        self.assertIn("configureActiveProvider", api_source)
        self.assertIn("configureHostedProvider", api_source)
        self.assertIn("/api/providers/hosted/selection", api_source)
        self.assertIn("speech_stt", api_source)
        self.assertIn("Hosted text model settings", settings_source)
        self.assertIn("Agentic model settings", settings_source)
        self.assertIn("Speech model settings", settings_source)
        self.assertIn("saveHostedProviderSettingsFromPanel", main_source)
        self.assertIn("data-agentic-provider-accordion", settings_source)
        self.assertIn("data-settings-model-accordion", settings_source)
        self.assertIn("data-hosted-model-accordion", settings_source)
        self.assertIn("data-hosted-provider-save", settings_source)
        self.assertNotIn("settings-hosted-provider-model", settings_source)
        self.assertIn("settings-model-card-heading", settings_source)
        self.assertIn(".settings-speech-model-settings-card .settings-hosted-models + .settings-hosted-models", styles_source)
        self.assertNotIn("Hosted text models", settings_source)
        self.assertNotIn("Chat only uses text-output fast models", settings_source)
        self.assertNotIn("Audio transcription uses Nova-3", settings_source)
        self.assertNotIn("OpenRouter governs", settings_source)
        self.assertIn("runtime engine remains Codex", settings_source)
        self.assertIn("/api/settings/runtime-sessions", api_source)
        self.assertIn("/api/settings/runtime-sessions/clear", api_source)

    def test_settings_panel_renders_openrouter_hosted_models_separately_from_codex(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        typescript_root = app_root / "node_modules" / "typescript"
        if not typescript_root.exists():
            self.skipTest("settings frontend dependencies are not installed")
        node_script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require(process.argv[2]);

const appRoot = process.argv[3];
const outDir = process.argv[4];

function transpile(relativePath) {
  const sourcePath = path.join(appRoot, relativePath);
  const outputPath = path.join(outDir, path.basename(relativePath).replace(/\.ts$/, '.js'));
  const source = fs.readFileSync(sourcePath, 'utf8');
  const result = ts.transpileModule(source, {
    fileName: sourcePath,
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
      moduleResolution: ts.ModuleResolutionKind.Node10,
      esModuleInterop: true,
      strict: true,
      skipLibCheck: true
    }
  });
  fs.writeFileSync(outputPath, result.outputText);
}

transpile('frontend/src/adminApi.ts');
transpile('frontend/src/providerModelOptions.ts');
transpile('frontend/src/settingsPanel.ts');

const {
  createSettingsPanelState,
  hostedProviderRoutingDraft,
  settingsPanelHtml,
  syncSettingsPanelDraft,
  updateHostedProviderRoutingDraft
} = require(path.join(outDir, 'settingsPanel.js'));

const openrouterModels = [
  {
    model_id: 'google/gemma-4-31b-it:free',
    label: 'Gemma 4 31B (free)',
    description: null,
    default_reasoning_effort: null,
    supported_reasoning_efforts: [],
    upstream_provider_options: [
      { provider_id: 'google-ai-studio', label: 'Google AI Studio', tag: 'google-ai-studio', quantization: 'unknown' },
      { provider_id: 'open-inference', label: 'OpenInference', tag: 'open-inference/bf16', quantization: 'bf16' }
    ]
  },
  {
    model_id: 'nvidia/nemotron-3-ultra-550b-a55b:free',
    label: 'Nemotron 3 Ultra (free)',
    description: null,
    default_reasoning_effort: null,
    supported_reasoning_efforts: [],
    upstream_provider_options: [
      { provider_id: 'nvidia', label: 'Nvidia', tag: 'nvidia', quantization: 'unknown' }
    ]
  },
  {
    model_id: 'deepseek/deepseek-v4-flash',
    label: 'DeepSeek V4 Flash',
    description: null,
    default_reasoning_effort: null,
    supported_reasoning_efforts: [],
    upstream_provider_options: [
      { provider_id: 'deepinfra/fp8', label: 'DeepInfra', tag: 'deepinfra/fp8', quantization: 'fp8' }
    ]
  },
  {
    model_id: 'hexgrad/kokoro-82m',
    label: 'Kokoro 82M',
    description: null,
    default_reasoning_effort: null,
    supported_reasoning_efforts: [],
    input_modalities: ['text'],
    output_modalities: ['speech'],
    upstream_provider_options: [
      { provider_id: 'deepinfra', label: 'DeepInfra', tag: 'deepinfra', quantization: 'unknown' }
    ]
  }
];

const googleModels = [
  {
    model_id: 'gemini-3.5-flash',
    label: 'Gemini 3.5 Flash',
    description: null,
    default_reasoning_effort: null,
    supported_reasoning_efforts: [],
    input_modalities: ['text', 'image'],
    output_modalities: ['text']
  },
  {
    model_id: 'gemini-3.1-flash-lite',
    label: 'Gemini 3.1 Flash-Lite',
    description: null,
    default_reasoning_effort: null,
    supported_reasoning_efforts: [],
    input_modalities: ['text', 'image'],
    output_modalities: ['text']
  }
];

const settings = {
  user: { username: 'admin', display_name: 'Admin', platform_role: 'admin' },
  workspace: { workspace_id: 'default', name: 'Default' },
  provider: {
    active_provider: {
      provider_id: 'codex',
      label: 'Codex',
      capabilities: { supports_subscription_usage: true },
      default_model_family: 'gpt-5.5',
      model_options: [{
        model_id: 'gpt-5.5',
        label: 'GPT-5.5',
        description: null,
        default_reasoning_effort: 'medium',
        supported_reasoning_efforts: [{ effort: 'medium', label: 'medium', description: null }]
      }]
    },
    model_settings: {
      selected_model_id: 'gpt-5.5',
      selected_reasoning_effort: 'medium',
      available_models: []
    },
    hosted_text: {
      profile: 'fast_model',
      active_provider: {
        provider_id: 'openrouter',
        label: 'OpenRouter',
        status: 'active',
        default_model_family: 'google/gemma-4-31b-it:free',
        model_options: openrouterModels
      },
      selection: {
        workspace_id: 'default',
        profile: 'fast_model',
        provider_id: 'openrouter',
        selection_reason: 'configured by hosted model settings',
        updated_at: '2026-06-23T00:00:00Z',
        model_id: 'nvidia/nemotron-3-ultra-550b-a55b:free',
        openrouter_provider_routing_by_model: {
          'nvidia/nemotron-3-ultra-550b-a55b:free': {
            mode: 'prefer',
            provider_id: 'nvidia',
            allow_fallbacks: true
          }
        }
      },
      model_settings: {
        selected_model_id: 'nvidia/nemotron-3-ultra-550b-a55b:free',
        selected_reasoning_effort: null,
        available_models: openrouterModels
      },
      available_providers: [
        {
          provider_id: 'openrouter',
          label: 'OpenRouter',
          status: 'active',
          default_model_family: 'google/gemma-4-31b-it:free',
          model_options: openrouterModels
        },
        {
          provider_id: 'google-ai-studio',
          label: 'Google AI Studio',
          status: 'disabled',
          default_model_family: 'gemini-3.5-flash',
          model_options: googleModels
        }
      ]
    },
    speech_stt: {
      profile: 'speech_stt',
      active_provider: {
        provider_id: 'deepgram',
        label: 'Deepgram',
        default_model_family: 'nova-3',
        model_options: [
          {
            model_id: 'nova-3',
            label: 'Nova-3',
            description: 'Deepgram transcription model.',
            default_reasoning_effort: null,
            supported_reasoning_efforts: [],
            input_modalities: ['audio'],
            output_modalities: ['text', 'events'],
            metadata: { purpose: 'prerecorded_transcription', endpoint: 'https://api.deepgram.com/v1/listen?model=nova-3' }
          },
          {
            model_id: 'flux-general-multi',
            label: 'Flux General Multilingual',
            description: 'Deepgram realtime conversation model.',
            default_reasoning_effort: null,
            supported_reasoning_efforts: [],
            input_modalities: ['audio'],
            output_modalities: ['text', 'events'],
            metadata: { purpose: 'conversational_streaming', endpoint: 'wss://api.deepgram.com/v2/listen?model=flux-general-multi' }
          }
        ]
      },
      credential_binding: {
        binding_id: 'deepgram:default',
        provider_id: 'deepgram',
        workspace_id: 'default',
        label: 'Deepgram speech-to-text',
        status: 'active',
        created_at: '2026-06-24T00:00:00Z',
        updated_at: '2026-06-24T00:00:00Z'
      },
      selection: {
        workspace_id: 'default',
        profile: 'speech_stt',
        provider_id: 'deepgram',
        selection_reason: 'configured by speech provider settings',
        updated_at: '2026-06-24T00:00:00Z',
        audio_transcription_model_id: 'nova-3',
        conversation_model_id: 'flux-general-multi'
      },
      model_settings: {
        audio_transcription_model_id: 'nova-3',
        conversation_model_id: 'flux-general-multi',
        available_audio_transcription_models: [{
          model_id: 'nova-3',
          label: 'Nova-3',
          description: 'Deepgram transcription model.',
          default_reasoning_effort: null,
          supported_reasoning_efforts: [],
          input_modalities: ['audio'],
          output_modalities: ['text', 'events'],
          metadata: { purpose: 'prerecorded_transcription', endpoint: 'https://api.deepgram.com/v1/listen?model=nova-3' }
        }],
        available_conversation_models: [{
          model_id: 'flux-general-multi',
          label: 'Flux General Multilingual',
          description: 'Deepgram realtime conversation model.',
          default_reasoning_effort: null,
          supported_reasoning_efforts: [],
          input_modalities: ['audio'],
          output_modalities: ['text', 'events'],
          metadata: { purpose: 'conversational_streaming', endpoint: 'wss://api.deepgram.com/v2/listen?model=flux-general-multi' }
        }],
        available_models: [],
        endpoints: {
          audio_transcription: 'https://api.deepgram.com/v1/listen?model=nova-3',
          conversation: 'wss://api.deepgram.com/v2/listen?model=flux-general-multi'
        }
      },
      available_providers: []
    }
  },
  runtime: { cleanup_allowed: false, cleanup_scope: 'none', sessions: [], all_sessions: [] },
  recovery: {}
};

const state = createSettingsPanelState();
syncSettingsPanelDraft(state, settings);
state.providerUsageItems = [{
  provider_id: 'codex',
  provider_label: 'Codex',
  available: true,
  fetched_at: '2026-08-12T16:30:00Z',
  plan_type: 'pro',
  unavailable_reason: null,
  credits_balance: 0,
  credits_unlimited: false,
  limits: [{
    limit_id: 'codex',
    label: 'Codex',
    metered_feature: null,
    limit_reached: false,
    primary_window: {
      used_percent: 11,
      limit_window_seconds: 604800,
      reset_after_seconds: 86400,
      reset_at_epoch_seconds: null
    },
    secondary_window: null
  }]
}];
const html = settingsPanelHtml(settings, state);

assert.ok(html.includes('settings-user-settings-card'));
assert.ok(html.includes('settings-hosted-text-model-settings-card'));
assert.ok(html.includes('settings-agentic-model-settings-card'));
assert.ok(html.includes('settings-speech-model-settings-card'));
assert.ok(html.includes('settings-runtime-settings-card'));
assert.ok(html.includes('Hosted text model settings'));
assert.ok(html.includes('Agentic model settings'));
assert.ok(html.includes('Speech model settings'));
assert.ok(html.indexOf('settings-agentic-model-settings-card') < html.indexOf('settings-hosted-text-model-settings-card'));
assert.ok(html.indexOf('settings-hosted-text-model-settings-card') < html.indexOf('settings-speech-model-settings-card'));
assert.ok(html.includes('Agentic provider'));
assert.ok(html.includes('data-agentic-provider-accordion'));
assert.ok(!html.includes('data-settings-model-accordion="agentic-provider" data-agentic-provider-accordion open'));
assert.ok(html.includes('Codex tools/filesystem/MCP'));
assert.ok(html.includes('Subscription usage'));
assert.ok(html.includes('data-provider-usage-gauge="11"'));
assert.ok(html.includes('11%'));
assert.ok(html.includes('7-day window'));
assert.ok(html.includes('settings-refresh-provider-usage'));
assert.ok(html.includes('Hosted chat / fast model'));
assert.ok(!html.includes('Hosted text models'));
assert.ok(!html.includes('Chat only uses text-output fast models'));
assert.ok(html.includes('data-hosted-provider-group="openrouter"'));
assert.ok(html.includes('data-hosted-provider-group="google-ai-studio"'));
assert.ok(html.includes('data-speech-provider-group="deepgram"'));
assert.ok(html.includes('Active provider'));
assert.ok(html.includes('Inactive provider'));
assert.ok(html.includes('OpenRouter'));
assert.ok(html.includes('Gemma 4 31B (free)'));
assert.ok(html.includes('Nemotron 3 Ultra (free)'));
assert.ok(html.includes('DeepSeek V4 Flash - OpenRouter'));
assert.ok(html.includes('Gemini 3.5 Flash - Google AI Studio'));
assert.ok(html.includes('Gemini 3.1 Flash-Lite - Google AI Studio'));
assert.ok(!html.includes('<span class="settings-pill">Inactive</span>'));
assert.ok(html.includes('Kokoro 82M'));
assert.ok(html.includes('Hosted speech model'));
assert.ok(html.includes('speech synthesis metadata · not used by plain hosted chat'));
assert.ok(!html.includes('Hosted speech models'));
assert.ok(!html.includes('Audio transcription uses Nova-3'));
const hostedTextSection = html.slice(
  html.indexOf('settings-hosted-text-model-settings-card'),
  html.indexOf('settings-speech-model-settings-card')
);
const speechSection = html.slice(
  html.indexOf('settings-speech-model-settings-card'),
  html.indexOf('settings-runtime-settings-card')
);
assert.ok(hostedTextSection.includes('DeepSeek V4 Flash - OpenRouter'));
assert.ok(!hostedTextSection.includes('Kokoro 82M'));
assert.ok(speechSection.includes('Kokoro 82M - OpenRouter'));
assert.ok(speechSection.includes('data-hosted-provider-group="openrouter"'));
assert.ok(html.includes('Nova-3'));
assert.ok(html.includes('Flux General Multilingual'));
assert.ok(html.includes('https://api.deepgram.com/v1/listen?model=nova-3'));
assert.ok(html.includes('wss://api.deepgram.com/v2/listen?model=flux-general-multi'));
assert.ok(!html.includes('id="settings-speech-save"'));
assert.equal((html.match(/data-speech-save=/g) || []).length, 2);
assert.equal((html.match(/Save speech model/g) || []).length, 2);
assert.equal((html.match(/data-settings-model-accordion=/g) || []).length, 7);
assert.equal((html.match(/data-hosted-model-accordion=/g) || []).length, 6);
assert.equal((html.match(/<span class="settings-pill">Active provider<\/span>/g) || []).length, 3);
assert.equal((html.match(/<span class="settings-pill">Inactive provider<\/span>/g) || []).length, 1);
assert.ok(html.includes('data-hosted-provider-save="google/gemma-4-31b-it:free"'));
assert.ok(html.includes('data-hosted-provider-save="nvidia/nemotron-3-ultra-550b-a55b:free"'));
assert.ok(html.includes('data-hosted-provider-save="deepseek/deepseek-v4-flash"'));
assert.ok(html.includes('data-hosted-provider-save="hexgrad/kokoro-82m"'));
assert.ok(html.includes('data-hosted-provider-save="gemini-3.5-flash"'));
assert.ok(html.includes('data-hosted-provider-save="gemini-3.1-flash-lite"'));
assert.ok(!html.includes('settings-hosted-provider-model'));
assert.ok(html.includes('OpenRouter upstream'));
assert.ok(html.includes('data-openrouter-routing="mode"'));
assert.ok(html.includes('data-openrouter-routing="zdr"'));
assert.ok(html.includes('Require zero data retention'));
assert.ok(html.includes('data-hosted-model-id="nvidia/nemotron-3-ultra-550b-a55b:free"'));
assert.ok(html.includes('Nvidia'));
assert.ok(html.includes('runtime engine remains Codex'));

updateHostedProviderRoutingDraft(state, settings, 'google/gemma-4-31b-it:free', 'mode', 'only');
updateHostedProviderRoutingDraft(state, settings, 'google/gemma-4-31b-it:free', 'provider_id', 'open-inference');
updateHostedProviderRoutingDraft(state, settings, 'google/gemma-4-31b-it:free', 'zdr', true);
assert.equal(hostedProviderRoutingDraft(state, 'google/gemma-4-31b-it:free').mode, 'only');
assert.equal(hostedProviderRoutingDraft(state, 'google/gemma-4-31b-it:free').provider_id, 'open-inference');
assert.equal(hostedProviderRoutingDraft(state, 'google/gemma-4-31b-it:free').zdr, true);
assert.equal(hostedProviderRoutingDraft(state, 'nvidia/nemotron-3-ultra-550b-a55b:free').mode, 'prefer');
assert.equal(hostedProviderRoutingDraft(state, 'nvidia/nemotron-3-ultra-550b-a55b:free').provider_id, 'nvidia');
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "settings_openrouter_render_test.cjs"
            script_path.write_text(node_script, encoding="utf-8")
            result = subprocess.run(
                [
                    "node",
                    str(script_path),
                    str(typescript_root),
                    str(app_root),
                    temp_dir,
                ],
                cwd=app_root,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_persistence_migration_requires_dry_run_and_explicit_cleanup(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        main_source = (app_root / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")
        api_source = (app_root / "frontend" / "src" / "adminApi.ts").read_text(encoding="utf-8")
        bindings_source = (app_root / "frontend" / "src" / "bindEvents.ts").read_text(encoding="utf-8")
        controller_source = (app_root / "frontend" / "src" / "persistenceController.ts").read_text(encoding="utf-8")
        persistence_source = (app_root / "frontend" / "src" / "persistencePage.ts").read_text(encoding="utf-8")

        self.assertIn("/api/admin/persistence/migrations/dry-run", api_source)
        self.assertIn("/api/admin/persistence/migrations/apply", api_source)
        self.assertIn("dryRunPersistenceMigration(payload)", controller_source)
        self.assertIn("applyPersistenceMigrationRequest({", controller_source)
        self.assertIn("delete_source: deleteSourceAfterMigration", controller_source)
        self.assertNotIn("delete_source: true", main_source)
        self.assertNotIn("delete_source: true", controller_source)
        self.assertIn('id="settings-delete-source"', persistence_source)
        self.assertIn('id="validate-migration"', persistence_source)
        self.assertIn('data-migration-field="mongodb_username"', persistence_source)
        self.assertIn('data-migration-field="mongodb_password_ref"', persistence_source)
        self.assertIn("mongodb_username: draft.mongodb_username?.trim() || undefined", controller_source)
        self.assertIn("mongodb_password_ref: draft.mongodb_password_ref?.trim() || undefined", controller_source)
        self.assertIn("Schedule source cleanup after restart health check", persistence_source)
        self.assertIn("input', () => updateMigrationDraft(false)", bindings_source)
        self.assertIn("markMigrationDraftStale", bindings_source)

    def test_persistence_controller_requires_reviewed_dry_run_before_apply(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        typescript_root = app_root / "node_modules" / "typescript"
        if not typescript_root.exists():
            self.skipTest("settings frontend dependencies are not installed")
        node_script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require(process.argv[2]);

const appRoot = process.argv[3];
const outDir = process.argv[4];

function transpile(sourcePath, outFile) {
  const source = fs.readFileSync(sourcePath, 'utf8');
  const result = ts.transpileModule(source, {
    fileName: sourcePath,
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
      moduleResolution: ts.ModuleResolutionKind.Node10,
      esModuleInterop: true,
      strict: true,
      skipLibCheck: true
    }
  });
  fs.writeFileSync(outFile, result.outputText);
}

transpile(path.join(appRoot, 'frontend/src/adminApi.ts'), path.join(outDir, 'adminApi.js'));
transpile(path.join(appRoot, 'frontend/src/persistenceController.ts'), path.join(outDir, 'persistenceController.js'));

const { createPersistenceController } = require(path.join(outDir, 'persistenceController.js'));
const sourceAdapter = {
  kind: 'json',
  json_root: 'data/control-plane/json',
  mongo_uri: null,
  mongo_database: 'maverick'
};
const calls = [];

function jsonResponse(payload) {
  return {
    ok: true,
    status: 200,
    json: async () => payload
  };
}

global.fetch = async (url, options = {}) => {
  const body = options.body ? JSON.parse(options.body) : {};
  calls.push({ url, body });
  if (url.endsWith('/dry-run')) {
    return jsonResponse({
      status: 'dry_run',
      source_adapter: sourceAdapter,
      target_adapter: {
        kind: body.kind,
        json_root: body.json_root,
        mongo_uri: body.mongodb_uri,
        mongo_database: body.mongodb_database
      },
      collections: [{ name: 'users', count: 2 }],
      target_collections: [],
      same_adapter: false,
      restart_required_for_cutover: true,
      env_file: '.env'
    });
  }
  if (url.endsWith('/apply')) {
    return jsonResponse({
      status: 'applied',
      source_adapter: sourceAdapter,
      target_adapter: {
        kind: body.kind,
        json_root: body.json_root,
        mongo_uri: body.mongodb_uri,
        mongo_database: body.mongodb_database
      },
      collections: [{ name: 'users', count: 2 }],
      target_collections: [],
      same_adapter: false,
      restart_required_for_cutover: true,
      backend_restart: { restarted: false, scheduled: true, detail: 'scheduled', method: 'signal', healthy: true },
      source_cleanup: { scheduled: body.delete_source, mode: body.delete_source ? 'post_health_check' : 'preserved' }
    });
  }
  throw new Error(`unexpected request ${url}`);
};
global.window = { setTimeout };

function requestCount(suffix) {
  return calls.filter((call) => call.url.endsWith(suffix)).length;
}

function lastRequest(suffix) {
  return calls.filter((call) => call.url.endsWith(suffix)).at(-1);
}

function makeController() {
  let activeAdapter = sourceAdapter;
  return createPersistenceController({
    getPersistence: () => ({
      active_adapter: activeAdapter,
      collections: [{ name: 'users', count: 2 }],
      restart_required_for_cutover: false
    }),
    render: () => {},
    requestPersistenceStatusQuiet: async () => ({
      active_adapter: {
        kind: 'mongo',
        json_root: 'data/control-plane/json',
        mongo_uri: 'mongodb://newhost:27017/maverick',
        mongo_database: 'maverick'
      },
      collections: [{ name: 'users', count: 2 }],
      restart_required_for_cutover: false
    }),
    setNotice: () => {},
    setPersistence: (status) => {
      activeAdapter = status.active_adapter;
    }
  });
}

(async () => {
  const controller = makeController();
  await controller.prepare('mongo');
  assert.equal(requestCount('/dry-run'), 0, 'opening the dialog must not dry-run immediately');
  assert.equal(controller.viewState().migrationTarget, 'mongo');
  assert.equal(controller.viewState().migrationPlan, null);

  await controller.validateDraft();
  assert.equal(requestCount('/dry-run'), 1);
  assert.equal(controller.viewState().migrationPlan.same_adapter, false);

  controller.updateDraft('mongodb_uri', 'mongodb://newhost:27017/maverick');
  assert.equal(controller.viewState().migrationPlan, null, 'editing the draft invalidates the reviewed plan');

  await controller.apply();
  assert.equal(requestCount('/dry-run'), 2, 'stale apply validates a fresh dry-run');
  assert.equal(requestCount('/apply'), 0, 'stale apply must not continue into apply in the same call');
  assert.equal(controller.viewState().migrationPlan.same_adapter, false);

  await controller.apply();
  assert.equal(requestCount('/apply'), 1);
  assert.equal(lastRequest('/apply').body.delete_source, false, 'source cleanup is opt-in');

  const cleanupController = makeController();
  await cleanupController.prepare('mongo');
  await cleanupController.validateDraft();
  cleanupController.setDeleteSource(true);
  await cleanupController.apply();
  assert.equal(requestCount('/apply'), 2);
  assert.equal(lastRequest('/apply').body.delete_source, true, 'checkbox enables source cleanup');
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "persistence_controller_test.cjs"
            script_path.write_text(node_script, encoding="utf-8")
            result = subprocess.run(
                [
                    "node",
                    str(script_path),
                    str(typescript_root),
                    str(app_root),
                    temp_dir,
                ],
                cwd=app_root,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_settings_frontend_splits_page_renderers(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        main_source = (app_root / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")

        for module_name in ("userPages.ts", "workspaceAppsPage.ts", "persistencePage.ts", "adminActions.ts", "persistenceController.ts", "providerSettingsActions.ts", "providerUsageController.ts", "notice.ts", "bindEvents.ts"):
            self.assertTrue((app_root / "frontend" / "src" / module_name).is_file())
        self.assertLess(len(main_source.splitlines()), 600)
        self.assertNotIn("function persistenceHtml(", main_source)
        self.assertNotIn("function workspaceAppHtml(", main_source)
        self.assertNotIn("function membershipHtml(", main_source)
        self.assertNotIn("document.querySelectorAll<HTMLInputElement>('[data-app-toggle]')", main_source)

    def test_settings_app_uses_initial_skeleton_loader(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        main_source = (app_root / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")
        skeleton_source = (app_root / "frontend" / "src" / "appSkeleton.ts").read_text(encoding="utf-8")
        skeleton_css = (app_root / "frontend" / "src" / "styles" / "skeleton.css").read_text(encoding="utf-8")

        self.assertIn("settingsAppSkeletonHtml(page)", main_source)
        self.assertIn("let isLoading = true", main_source)
        self.assertIn('role="status"', skeleton_source)
        self.assertIn('aria-hidden="true"', skeleton_source)
        self.assertIn("@keyframes settings-loading-skeleton-shimmer", skeleton_css)

    def test_platform_settings_renders_themed_subscription_usage_gauges(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        gauge_source = (app_root / "frontend" / "src" / "components" / "ui" / "gauge-1.tsx").read_text(encoding="utf-8")
        usage_source = (app_root / "frontend" / "src" / "components" / "usageLimitGauges.tsx").read_text(encoding="utf-8")
        panel_source = (app_root / "frontend" / "src" / "settingsPanel.ts").read_text(encoding="utf-8")
        styles_source = (app_root / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        components = json.loads((app_root / "components.json").read_text(encoding="utf-8"))

        self.assertIn('export const Gauge', gauge_source)
        self.assertIn('role="progressbar"', gauge_source)
        self.assertIn("var(--maverick-accent)", usage_source)
        self.assertIn("data-provider-usage-gauge", panel_source)
        self.assertIn("Subscription usage", panel_source)
        self.assertIn("settings-refresh-provider-usage", panel_source)
        self.assertIn('@import "tailwindcss"', styles_source)
        self.assertEqual(components["aliases"]["ui"], "@/components/ui")


@slow_test_class("slow settings app integration suite; run with scripts/test_suite.py --level slow")
class SettingsApiTestCase(unittest.TestCase):
    """Verify the core exposes app-agnostic administration APIs."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "docs", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        source_apps_root = Path(__file__).resolve().parents[3] / "apps"
        for app_id in ("base-shell", "chat", "agents", "settings"):
            source = source_apps_root / app_id
            if source.exists():
                shutil.copytree(source, repo_root / "apps" / app_id, ignore=shutil.ignore_patterns("node_modules"))
        return repo_root

    def invoke(
        self,
        app: PlatformHost,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str | None = None,
    ) -> tuple[int, dict, dict[str, str]]:
        payload = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "wsgi.input": BytesIO(payload),
        }
        if cookie is not None:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        body_bytes = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), json.loads(body_bytes.decode("utf-8")), headers

    def invoke_raw(
        self,
        app: PlatformHost,
        *,
        path: str,
        cookie: str | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": "GET",
            "CONTENT_LENGTH": "0",
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "wsgi.input": BytesIO(b""),
        }
        if cookie is not None:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        body_bytes = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), body_bytes, headers

    def login(self, app: PlatformHost, username: str | None = None, password: str | None = None) -> str:
        status, _payload, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={
                "username": username or os.environ.get("MAVERICK_ADMIN_USERNAME", "admin"),
                "password": password or os.environ.get("MAVERICK_ADMIN_PASSWORD", "maverick"),
            },
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_admin_can_create_user_and_assign_workspace(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        status_workspace, workspace, _headers = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Client Ops"},
            cookie=admin_cookie,
        )

        status_create, created, _create_headers = self.invoke(
            app,
            path="/api/admin/users",
            method="POST",
            body={
                "username": "operator",
                "password": "operator-password",
                "display_name": "Operator",
                "platform_role": "member",
            },
            cookie=admin_cookie,
        )
        status_assign, assigned, _assign_headers = self.invoke(
            app,
            path="/api/admin/users/user:operator/workspaces",
            method="PUT",
            body={"memberships": [{"workspace_id": workspace["workspace_id"], "role": "member"}]},
            cookie=admin_cookie,
        )

        self.assertEqual(status_workspace, 201)
        self.assertEqual(status_create, 201)
        self.assertEqual(created["username"], "operator")
        self.assertEqual(status_assign, 200)
        self.assertIn(workspace["workspace_id"], {item["workspace_id"] for item in assigned["memberships"]})

    def test_admin_can_reset_another_users_password(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        status_create, created, _create_headers = self.invoke(
            app,
            path="/api/admin/users",
            method="POST",
            body={"username": "forgotten", "password": "initial-password", "platform_role": "member"},
            cookie=admin_cookie,
        )
        self.invoke(
            app,
            path=f"/api/admin/users/{created['user_id']}/workspaces",
            method="PUT",
            body={"memberships": [{"workspace_id": "default", "role": "member"}]},
            cookie=admin_cookie,
        )

        status_reset, reset, _reset_headers = self.invoke(
            app,
            path=f"/api/admin/users/{created['user_id']}/password",
            method="POST",
            body={"password": "replacement-password"},
            cookie=admin_cookie,
        )
        status_old, old_login, _old_headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": "forgotten", "password": "initial-password"},
        )
        replacement_cookie = self.login(app, username="forgotten", password="replacement-password")
        status_session, session, _session_headers = self.invoke(app, path="/api/session", cookie=replacement_cookie)

        self.assertEqual(status_create, 201)
        self.assertEqual(status_reset, 200)
        self.assertEqual(reset["status"], "updated")
        self.assertEqual(status_old, 401)
        self.assertEqual(old_login["error"], "invalid_credentials")
        self.assertEqual(status_session, 200)
        self.assertEqual(session["user"]["username"], "forgotten")

    def test_admin_can_delete_user_and_core_access_state(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        status_workspace, workspace, _workspace_headers = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Delete Target"},
            cookie=admin_cookie,
        )
        status_create, created, _create_headers = self.invoke(
            app,
            path="/api/admin/users",
            method="POST",
            body={"username": "delete-me", "password": "delete-password", "platform_role": "member"},
            cookie=admin_cookie,
        )
        self.invoke(
            app,
            path=f"/api/admin/users/{created['user_id']}/workspaces",
            method="PUT",
            body={"memberships": [{"workspace_id": workspace["workspace_id"], "role": "member"}]},
            cookie=admin_cookie,
        )
        deleted_user_cookie = self.login(app, username="delete-me", password="delete-password")

        status_delete, deleted, _delete_headers = self.invoke(
            app,
            path=f"/api/admin/users/{created['user_id']}",
            method="DELETE",
            cookie=admin_cookie,
        )
        status_session, session, _session_headers = self.invoke(app, path="/api/session", cookie=deleted_user_cookie)
        status_login, login_payload, _login_headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": "delete-me", "password": "delete-password"},
        )

        self.assertEqual(status_workspace, 201)
        self.assertEqual(status_create, 201)
        self.assertEqual(status_delete, 200)
        self.assertEqual(deleted["status"], "deleted")
        self.assertEqual(state.workspace_store.list_memberships_for_user(created["user_id"]), [])
        self.assertIsNone(state.workspace_store.get_active_workspace(created["user_id"]))
        self.assertEqual(status_session, 200)
        self.assertFalse(session["authenticated"])
        self.assertEqual(status_login, 401)
        self.assertEqual(login_payload["error"], "invalid_credentials")

    def test_admin_cannot_delete_self_or_final_active_admin(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)

        status_self, self_delete, _self_headers = self.invoke(
            app,
            path="/api/admin/users/user:admin",
            method="DELETE",
            cookie=admin_cookie,
        )
        self.invoke(
            app,
            path="/api/admin/users",
            method="POST",
            body={"username": "member-to-promote", "password": "member-password", "platform_role": "member"},
            cookie=admin_cookie,
        )
        status_demote, _demote, _demote_headers = self.invoke(
            app,
            path="/api/admin/users/user:admin",
            method="PATCH",
            body={"platform_role": "member"},
            cookie=admin_cookie,
        )

        self.assertEqual(status_self, 400)
        self.assertEqual(self_delete["error"], "cannot_delete_current_user")
        self.assertEqual(status_demote, 400)
        self.assertEqual(_demote["error"], "cannot_remove_last_admin")

    def test_member_cannot_use_admin_api_or_see_admin_app(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        self.invoke(
            app,
            path="/api/admin/users",
            method="POST",
            body={"username": "viewer", "password": "viewer-password", "platform_role": "member"},
            cookie=admin_cookie,
        )
        self.invoke(
            app,
            path="/api/admin/users/user:viewer/workspaces",
            method="PUT",
            body={"memberships": [{"workspace_id": "default", "role": "member"}]},
            cookie=admin_cookie,
        )
        member_cookie = self.login(app, username="viewer", password="viewer-password")

        status_admin_api, forbidden, _forbidden_headers = self.invoke(app, path="/api/admin/users", cookie=member_cookie)
        status_apps, apps, _apps_headers = self.invoke(app, path="/api/apps", cookie=member_cookie)
        status_direct, direct, _direct_headers = self.invoke(app, path="/apps/settings/", cookie=member_cookie)

        self.assertEqual(status_admin_api, 403)
        self.assertEqual(forbidden["error"], "admin_required")
        self.assertEqual(status_apps, 200)
        self.assertNotIn("settings", {item["app_id"] for item in apps["items"]})
        self.assertEqual(status_direct, 403)
        self.assertEqual(direct["error"], "app_forbidden")

    def test_local_identity_and_workspace_state_survives_bootstrap(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        self.invoke(
            app,
            path="/api/admin/users",
            method="POST",
            body={"username": "persistent", "password": "persistent-password"},
            cookie=admin_cookie,
        )
        self.invoke(
            app,
            path="/api/admin/users/user:persistent/workspaces",
            method="PUT",
            body={"memberships": [{"workspace_id": "default", "role": "member"}]},
            cookie=admin_cookie,
        )

        restarted_state = bootstrap_platform_state(start_path=repo_root)
        restarted_app = PlatformHost(restarted_state, start_path=restarted_state.repository_root)
        persistent_cookie = self.login(restarted_app, username="persistent", password="persistent-password")
        status_session, session, _headers = self.invoke(restarted_app, path="/api/session", cookie=persistent_cookie)

        self.assertEqual(status_session, 200)
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["user"]["username"], "persistent")

    def test_persisted_active_workspace_gets_builtin_apps_after_restart(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        status_workspace, workspace, _headers = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "CEIDA"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_workspace, 201)

        restarted_state = bootstrap_platform_state(start_path=repo_root)
        restarted_app = PlatformHost(restarted_state, start_path=restarted_state.repository_root)
        status_apps, apps, _apps_headers = self.invoke(restarted_app, path="/api/apps", cookie=admin_cookie)
        status_admin_app, admin_body, _admin_headers = self.invoke_raw(restarted_app, path="/apps/settings/", cookie=admin_cookie)

        self.assertEqual(status_apps, 200)
        self.assertEqual(workspace["workspace_id"], "ceida")
        self.assertIn("settings", {item["app_id"] for item in apps["items"]})
        self.assertEqual(status_admin_app, 200)
        self.assertIn(b"Settings", admin_body)

    def test_admin_can_disable_and_enable_workspace_app_visibility(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)

        status_list, installed_apps, _list_headers = self.invoke(
            app,
            path="/api/admin/workspace-apps",
            cookie=admin_cookie,
        )
        status_disable, disabled, _disable_headers = self.invoke(
            app,
            path="/api/admin/workspace-apps/default/chat",
            method="PATCH",
            body={"status": "disabled"},
            cookie=admin_cookie,
        )
        status_apps_after_disable, visible_after_disable, _apps_disable_headers = self.invoke(
            app,
            path="/api/apps",
            cookie=admin_cookie,
        )
        status_direct_after_disable, direct_after_disable, _direct_disable_headers = self.invoke_raw(
            app,
            path="/apps/chat/",
            cookie=admin_cookie,
        )
        status_enable, enabled, _enable_headers = self.invoke(
            app,
            path="/api/admin/workspace-apps/default/chat",
            method="PATCH",
            body={"status": "enabled"},
            cookie=admin_cookie,
        )
        status_apps_after_enable, visible_after_enable, _apps_enable_headers = self.invoke(
            app,
            path="/api/apps",
            cookie=admin_cookie,
        )

        self.assertEqual(status_list, 200)
        self.assertIn(("default", "chat"), {(item["workspace_id"], item["app_id"]) for item in installed_apps["items"]})
        self.assertEqual(status_disable, 200)
        self.assertEqual(disabled["status"], "disabled")
        self.assertEqual(status_apps_after_disable, 200)
        self.assertNotIn("chat", {item["app_id"] for item in visible_after_disable["items"]})
        self.assertEqual(status_direct_after_disable, 404)
        self.assertIn(b"app_not_installed", direct_after_disable)
        self.assertEqual(status_enable, 200)
        self.assertEqual(enabled["status"], "enabled")
        self.assertEqual(status_apps_after_enable, 200)
        self.assertIn("chat", {item["app_id"] for item in visible_after_enable["items"]})

    def test_workspace_apps_include_enabled_workspace_local_bindings_without_app_source(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(
            start_path=repo_root,
            install_builtin_apps=False,
            register_builtin_provider_definitions=False,
        )
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        parsed = parse_app_contract_file(repo_root / "apps" / "chat")
        now = "2026-05-29T00:00:00Z"
        state.app_store.save_workspace_local_app_project(
            WorkspaceLocalAppProjectRecord(
                project_id="default:local-crm",
                workspace_id="default",
                app_id="local-crm",
                name="Local CRM",
                version="0.4.1",
                description="Workspace-local CRM app.",
                publisher="workspace",
                project_root="workspaces/default/apps/local-crm",
                contract=parsed.contract,
                created_at=now,
                updated_at=now,
                local_app_id="local-crm",
                public_app_id="crm",
            )
        )
        state.app_store.save_workspace_app_binding(
            WorkspaceAppBindingRecord(
                binding_id="default:local-crm",
                workspace_id="default",
                app_id="local-crm",
                source_record_id="default:local-crm",
                source_kind="workspace_local_project",
                status="enabled",
                active_version="0.4.1",
                data_root="workspaces/default/data/local-crm",
                installed_at=now,
                updated_at=now,
                local_app_id="local-crm",
                public_app_id="crm",
                mount_app_id="local-crm",
            )
        )

        status_list, workspace_apps, _headers = self.invoke(app, path="/api/admin/workspace-apps", cookie=admin_cookie)
        local_item = next((item for item in workspace_apps["items"] if item["workspace_id"] == "default" and item["app_id"] == "local-crm"), None)

        self.assertEqual(status_list, 200)
        self.assertIsNotNone(local_item)
        self.assertEqual(local_item["name"], "Local CRM")
        self.assertEqual(local_item["source_id"], "default:local-crm")
        self.assertEqual(local_item["source_kind"], "workspace_local_project")
        self.assertEqual(local_item["status"], "enabled")
        self.assertTrue(local_item["installed"])


if __name__ == "__main__":
    unittest.main()
