/**
 * Dynamically loads the Mappls Vector Map SDK and returns a Promise that
 * resolves once `window.mappls` is available.
 *
 * If the Mappls SDK fails to load (401, network error, etc.), the loader
 * falls back to MapLibre GL JS — an open-source vector map library — so the
 * app always renders a working map.
 *
 * After this resolves, check `getMapEngine()` to know which engine loaded.
 */

let _promise: Promise<void> | null = null;
let _engine: 'mappls' | 'maplibre' = 'mappls';

/** Returns which map engine was successfully loaded. */
export function getMapEngine(): 'mappls' | 'maplibre' {
  return _engine;
}

export function loadMapplsSDK(): Promise<void> {
  if (_promise) return _promise;

  const key = import.meta.env.VITE_MAPPLS_KEY as string | undefined;

  _promise = new Promise<void>((resolve) => {
    // Already loaded (e.g. hot-reload)
    if ((window as any).mappls) {
      _engine = 'mappls';
      resolve();
      return;
    }

    if (!key) {
      console.warn('VITE_MAPPLS_KEY is not set — falling back to MapLibre GL');
      loadMapLibreFallback().then(resolve);
      return;
    }

    const script = document.createElement('script');
    script.src = `https://apis.mappls.com/advancedmaps/api/${key}/map_sdk?v=3.0&layer=vector`;
    script.async = true;

    let settled = false;

    script.onload = () => {
      // The SDK may need a micro-tick to register `window.mappls`
      const poll = setInterval(() => {
        if ((window as any).mappls) {
          clearInterval(poll);
          if (!settled) {
            settled = true;
            _engine = 'mappls';
            console.info('Mappls SDK loaded successfully');
            resolve();
          }
        }
      }, 50);

      // Timeout after 8 s — if mappls never appears, fall back
      setTimeout(() => {
        clearInterval(poll);
        if (!settled) {
          settled = true;
          console.warn('Mappls SDK loaded but window.mappls is undefined — falling back to MapLibre GL');
          loadMapLibreFallback().then(resolve);
        }
      }, 8_000);
    };

    script.onerror = () => {
      if (!settled) {
        settled = true;
        console.warn('Mappls SDK script failed to load — falling back to MapLibre GL');
        loadMapLibreFallback().then(resolve);
      }
    };

    document.head.appendChild(script);
  });

  return _promise;
}

// ── MapLibre GL JS fallback ──────────────────────────────────────────────

const MAPLIBRE_JS = 'https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js';
const MAPLIBRE_CSS = 'https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css';

function loadMapLibreFallback(): Promise<void> {
  _engine = 'maplibre';

  return new Promise<void>((resolve, reject) => {
    // Already loaded
    if ((window as any).maplibregl) {
      resolve();
      return;
    }

    // Load CSS
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = MAPLIBRE_CSS;
    document.head.appendChild(link);

    // Load JS
    const script = document.createElement('script');
    script.src = MAPLIBRE_JS;
    script.async = true;

    script.onload = () => {
      if ((window as any).maplibregl) {
        console.info('MapLibre GL loaded as fallback');
        resolve();
      } else {
        reject(new Error('MapLibre GL script loaded but maplibregl is undefined'));
      }
    };

    script.onerror = () =>
      reject(new Error('Failed to load MapLibre GL fallback'));

    document.head.appendChild(script);
  });
}
