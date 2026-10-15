from django.test import TestCase, override_settings


@override_settings(APP_PREFIX='/pun/dev/transcriber', FORCE_SCRIPT_NAME='/pun/dev/transcriber',
    MEDIA_URL='/pun/dev/transcriber/media/', ALLOWED_HOSTS=['testserver'],
    CSRF_COOKIE_NAME='csrftoken_transcriber', CSRF_COOKIE_PATH='/pun/dev/transcriber/')
class PrefixTests(TestCase):
    def test_passenger_decodes_media_paths_once(self):
        import io
        import tempfile
        from pathlib import Path
        from urllib.parse import quote
        from passenger_wsgi import application
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            for name in ('Interview #1? 100%20.wav', 'M\u00f8de.wav'):
                with self.subTest(name=name):
                    (Path(directory) / name).write_bytes(b'audio')
                    statuses = []
                    environment = {
                        'REQUEST_METHOD': 'GET', 'SCRIPT_NAME': '/pun/dev/transcriber',
                        'PATH_INFO': '/media/' + quote(name),
                        'SERVER_NAME': 'testserver', 'SERVER_PORT': '443',
                        'SERVER_PROTOCOL': 'HTTP/1.1', 'wsgi.version': (1, 0),
                        'wsgi.url_scheme': 'https', 'wsgi.input': io.BytesIO(),
                        'wsgi.errors': io.StringIO(), 'wsgi.multithread': False,
                        'wsgi.multiprocess': False, 'wsgi.run_once': False,
                    }
                    response = application(environment, lambda status, headers: statuses.append(status))
                    try:
                        body = b''.join(response)
                    finally:
                        response.close()
                    self.assertEqual(statuses, ['200 OK'])
                    self.assertEqual(body, b'audio')

    def test_html_runtime_prefix_and_cookie(self):
        response = self.client.get('/')
        self.assertContains(response, 'content="/pun/dev/transcriber"')
        self.assertContains(response, 'href="/pun/dev/transcriber/"')
        self.assertContains(response, 'content="csrftoken_transcriber"')
        self.assertEqual(response.cookies['csrftoken_transcriber']['path'], '/pun/dev/transcriber/')

    def test_media_url_keeps_prefix_once(self):
        from django.test import RequestFactory
        from .views import _build_media_absolute_url
        request = RequestFactory().get('/', SCRIPT_NAME='/pun/dev/transcriber')
        self.assertEqual(_build_media_absolute_url(request, 'batch/data/input.wav'),
            'http://testserver/pun/dev/transcriber/media/batch/data/input.wav')

    def test_production_static_and_wsgi_script_name(self):
        import io
        import tempfile
        from pathlib import Path
        from django.core.handlers.wsgi import WSGIHandler
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sample.js').write_text('export const ready = true;')
            with override_settings(DEBUG=False, STATIC_ROOT=root, STATIC_URL='/pun/dev/transcriber/static/'):
                application = WSGIHandler()
                statuses = []
                environment = {
                    'REQUEST_METHOD':'GET', 'SCRIPT_NAME':'/pun/dev/transcriber',
                    'PATH_INFO':'/static/sample.js', 'SERVER_NAME':'testserver', 'SERVER_PORT':'443',
                    'SERVER_PROTOCOL':'HTTP/1.1', 'wsgi.version':(1,0), 'wsgi.url_scheme':'https',
                    'wsgi.input':io.BytesIO(), 'wsgi.errors':io.StringIO(),
                    'wsgi.multithread':False, 'wsgi.multiprocess':False, 'wsgi.run_once':False,
                }
                response = application(environment, lambda status, headers: statuses.append(status))
                try:
                    body = b''.join(response)
                finally:
                    response.close()
                self.assertEqual(statuses, ['200 OK'])
                self.assertIn(b'export const ready', body)