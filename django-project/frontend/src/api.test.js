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