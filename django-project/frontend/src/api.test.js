import test from 'node:test';
import assert from 'node:assert/strict';
import { appUrl, apiFetch, api } from './api.js';

function configure(prefix) {
    globalThis.document = {
        cookie: 'csrftoken_test=example-token',
        querySelector(selector) {
            return {content: selector.includes('csrf') ? 'csrftoken_test' : prefix};
        },
    };
}

test('prefixes API requests without double-prefixing or changing absolute URLs', () => {
    configure('/pun/dev/transcriber');
    assert.equal(appUrl('/upload/'), '/pun/dev/transcriber/upload/');
    assert.equal(appUrl('/pun/dev/transcriber/media/file.wav'), '/pun/dev/transcriber/media/file.wav');
    assert.equal(appUrl('https://example.org/file'), 'https://example.org/file');
    configure('');
    assert.equal(appUrl('/upload/'), '/upload/');
});

test('fetch mutations use scoped CSRF cookie and preserve supplied headers', async () => {
    configure('/pun/dev/transcriber');
    globalThis.fetch = async (url, options) => ({url, options});
    const response = await apiFetch('/save-note/', {method:'POST', headers:{'Content-Type':'application/json'}});
    assert.equal(response.url, '/pun/dev/transcriber/save-note/');
    assert.equal(response.options.headers.get('X-CSRFToken'), 'example-token');
    assert.equal(response.options.headers.get('Content-Type'), 'application/json');
    const get = await apiFetch('/hpc-files/');
    assert.equal(get.options.headers.has('X-CSRFToken'), false);
});

test('axios upload/cancel calls use the same prefix and CSRF token', async () => {
    configure('/pun/dev/transcriber');
    document.cookie += '; csrftoken=unrelated-app-token';
    const response = await api.post('/upload/', {}, {adapter: async config => ({data:config, status:200})});
    assert.equal(response.data.url, '/pun/dev/transcriber/upload/');
    assert.equal(response.data.headers['X-CSRFToken'], 'example-token');
    assert.equal(response.data.withXSRFToken, false);
});

test('transcription status distinguishes queueing, estimated progress, and terminal states', async () => {
    const {createServer} = await import('vite');
    const {createElement} = await import('react');
    const {renderToStaticMarkup} = await import('react-dom/server');
    const server = await createServer({server: {middlewareMode: true}, appType: 'custom'});
    try {
        const {default: TranscriptionStatus} = await server.ssrLoadModule('/src/TranscriptionStatus.jsx');
        const base = {
            slurm_job_id: '123', slurm_started_at: '2026-11-03T12:00:00+00:00',
            estimated_duration_seconds: 180, elapsed_seconds: 60,
        };
        const render = (status) => renderToStaticMarkup(createElement(TranscriptionStatus, {
            statusText: status.job_state, activeTask: [], status: {...base, ...status},
        }));
        const running = render({job_state: 'running'});
        assert.match(running, /123/);
        assert.match(running, /Approximately 3m 0s/);
        assert.match(running, /Approximately 2m 0s/);
        assert.match(running, /value="33\.333/);
        const queued = render({job_state: 'queued', slurm_started_at: null, elapsed_seconds: null});
        assert.match(queued, /Waiting for resources/);
        assert.match(queued, /Not started yet/);
        assert.doesNotMatch(queued, /<progress/);
        const exceeded = render({job_state: 'running', elapsed_seconds: 240});
        assert.match(exceeded, /value="90"/);
        assert.match(exceeded, /Taking longer than estimated/);
        assert.doesNotMatch(exceeded, /Estimated remaining/);
        for (const job_state of ['failed', 'cancelled', 'cancelling']) {
            assert.doesNotMatch(render({job_state}), /<progress/);
        }
        assert.doesNotMatch(render({job_state: 'running', elapsed_seconds: null}), /<progress/);
    } finally {
        await server.close();
    }
});