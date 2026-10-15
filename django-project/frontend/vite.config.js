import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import basicSsl from '@vitejs/plugin-basic-ssl';

export default defineConfig({
    base: './',
    plugins: [react(), {
        name: 'development-runtime-config',
        transformIndexHtml(html, context) {
            if (!context.server) return html;
            return html.replace('{{ app_prefix }}', '').replace('{{ csrf_cookie_name }}', 'csrftoken')
                .replace('{{ app_base }}', '/');
        },
    }],
    //plugins: [react(), basicSsl()],
    server: {
        host: '127.0.0.1',
        proxy: {
            '/hpc-files': {
                target: 'http://127.0.0.1:8000',
                changeOrigin: true,
            },
            '/active-transcription': {
                target: 'http://127.0.0.1:8000',
                changeOrigin: true,
            },
            // Proxying API requests to avoid CORS issues during development
            '/upload': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                secure: false,
            },
            '/poll-transcription-status': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                secure: false,
            },
            '/stop_transcription_task': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                secure: false,
            },
            '/get-completed-transcriptions': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                secure: false,
            },
            '/get-initialization-data': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                secure: false,
            },
            '/link-files': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                secure: false,
            },
            '/remove-link': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                secure: false,
            },
            '/convert-audio': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                secure: false,
            },
            '/edit-transcription-segment': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                secure: false,
            },
            '/get-notes': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                secure: false,
            },
            '/save-note': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                secure: false,
            },
            '/delete-note': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                secure: false,
            },
            '/export-file': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                secure: false,
            },
            // Proxy media file requests to the Django/Daphne server.
            // Match any URL that contains '/media/'
            '^.*(/media/.*)$': {
                target: 'http://localhost:8000',
                //target: 'http://10.49.223.156:8000',
                changeOrigin: true,
            },
        },
    },
    build: {
        // This is the folder where the build will be generated
        outDir: 'build',
        // This is the folder where the assets will be generated
        assetsDir: 'static',
        // This is the base url of the assets
        // It should match Django's STATIC_URL
        base: '/static/',
    }
});