import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import { AppStateProvider } from './state/AppState';
import { ToastProvider } from './components/Toast';
import { loadMapplsSDK } from './utils/loadMapplsSDK';
import './styles/index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

function renderApp() {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <AppStateProvider>
            <App />
          </AppStateProvider>
        </ToastProvider>
      </QueryClientProvider>
    </React.StrictMode>,
  );
}

// Load the map SDK (Mappls or MapLibre fallback) before mounting the React tree.
// Show a brief loading message while it downloads.
const root = document.getElementById('root')!;
root.innerHTML =
  '<style>@keyframes _spin{to{transform:rotate(360deg)}}</style>' +
  '<div style="display:flex;align-items:center;justify-content:center;height:100vh;font-family:Inter,sans-serif;color:#94a3b8;gap:12px">' +
  '<div style="width:18px;height:18px;border:2px solid #e2e8f0;border-top-color:#0d9488;border-radius:50%;animation:_spin .7s linear infinite"></div>' +
  '<span>Loading map engine…</span>' +
  '</div>';

loadMapplsSDK()
  .then(renderApp)
  .catch((err) => {
    console.error(err);
    root.innerHTML =
      '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;font-family:Inter,sans-serif;color:#ef4444;gap:8px;padding:24px;text-align:center">' +
      '<p style="font-size:16px;font-weight:700">Map Engine Failed to Load</p>' +
      `<p style="font-size:13px;color:#94a3b8">${err.message}</p>` +
      '<p style="font-size:12px;color:#64748b">Check your API key and network connection.</p>' +
      '</div>';
  });
