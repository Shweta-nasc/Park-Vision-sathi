import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';
// Vite config. Dev server runs on :5173 (per planner) and proxies API calls
// to the FastAPI backend on :8000 so the frontend can call relative paths.
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            '@': fileURLToPath(new URL('./src', import.meta.url)),
        },
    },
    server: {
        port: 5173,
        proxy: {
            // Proxy all known backend routes to FastAPI during development.
            '/health': 'http://localhost:8000',
            '/stations': 'http://localhost:8000',
            '/heatmap': 'http://localhost:8000',
            '/hotspots': 'http://localhost:8000',
            '/risk': 'http://localhost:8000',
            '/forecast': 'http://localhost:8000',
            '/game': 'http://localhost:8000',
            '/simulate': 'http://localhost:8000',
            '/explain': 'http://localhost:8000',
            '/traffic': 'http://localhost:8000',
        },
    },
    // Build into dist/ — backend serves this at /dashboard when present.
    build: {
        outDir: 'dist',
        emptyOutDir: true,
    },
    base: './',
});
