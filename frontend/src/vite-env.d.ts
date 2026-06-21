/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE: string;
  readonly VITE_MAPPLS_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// Mappls SDK is loaded via <script> tag at runtime and attaches to `window`.
// The MapView component uses a local `declare const mappls: any` where needed.
