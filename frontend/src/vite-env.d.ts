/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE: string;
  readonly VITE_MAPPLS_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// leaflet.heat has no bundled types
declare module 'leaflet.heat';
