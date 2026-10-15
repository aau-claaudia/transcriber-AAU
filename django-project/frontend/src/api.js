import axios from 'axios';

export function appUrl(path) {
    const configured = document.querySelector('meta[name="transcriber-prefix"]')?.content ?? '';
    const prefix = configured.startsWith('/') ? configured : '';
    if (!path.startsWith('/') || (prefix && path.startsWith(`${prefix}/`))) return path;
    return `${prefix}${path}`;
}

function csrfToken() {
    const configured = document.querySelector('meta[name="transcriber-csrf-cookie"]')?.content;
    const name = configured && !configured.includes('{') ? configured : 'csrftoken';
    const value = document.cookie.split('; ').find(cookie => cookie.startsWith(`${name}=`));
    return value ? decodeURIComponent(value.slice(name.length + 1)) : '';
}

export function apiFetch(path, options = {}) {
    const headers = new Headers(options.headers);
    if (!['GET', 'HEAD', 'OPTIONS'].includes((options.method ?? 'GET').toUpperCase())) {
        headers.set('X-CSRFToken', csrfToken());
    }
    return fetch(appUrl(path), { ...options, headers });
}

export const api = axios.create({ withXSRFToken: false });
api.interceptors.request.use(config => {
    config.url = appUrl(config.url);
    config.headers['X-CSRFToken'] = csrfToken();
    return config;
});