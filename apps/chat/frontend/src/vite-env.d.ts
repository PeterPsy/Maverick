/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_LOOPINO_FEATURE_GROUP_CHAT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
