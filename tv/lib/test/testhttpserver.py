"""testhttpserver.py -- Testing HTTP Server

The code here is based off of the standard SimpleHTTPServer code.
"""


import BaseHTTPServer
import hashlib
import cgi
import os
import posixpath
import urllib
import socket
import threading

from miro.plat import utils
from miro.plat import resources

def md5(d):
    return hashlib.md5(d).hexdigest()

class MiroHTTPRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    server_version = "MiroTestHTTP/1.0"
    handlers_created = 0
    protocol_version = "HTTP/1.1"

    def setup(self):
        BaseHTTPServer.BaseHTTPRequestHandler.setup(self)
        MiroHTTPRequestHandler.handlers_created += 1
        self.server.current_request_handler = self
        self.connection.settimeout(5.0)
        self.digest_nonce = "dcd98b7102dd2f0e8b11d0f600bfb0c093"

    def handle(self):
        try:
            BaseHTTPServer.BaseHTTPRequestHandler.handle(self)
        except StandardError:
            if not self.server.shutting_down:
                raise

    def date_time_string(self, timestamp=None):
        if timestamp is None:
            # If we are trying to get the date string for "now", use a fixed
            # time to avoid issues with unittests.  We never know when a
            # second will pass between calls.
            # The timestamp is Fri, 13 Feb 2009 23:31:30 GMT
            timestamp = 1234567890
        return BaseHTTPServer.BaseHTTPRequestHandler.date_time_string(self,
                timestamp)

    def send_request(self, send_body=True):
        f = self.send_head()
        if f:
            if send_body:
                if self.start_pos > 0:
                    f.seek(self.start_pos, os.SEEK_CUR)
                if self.end_pos > 0:
                    count = self.end_pos - self.start_pos
                else:
                    count = -1
                data = f.read(count)
                if self.server.pause_after >= 0:
                    data = data[:self.server.pause_after]
                self.wfile.write(data)
            f.close()
        if self.server.close_connection:
            self.close_connection = 1
            self.rfile.close()
            self.wfile.close()

    def do_GET(self):
        """Serve a GET request."""
        self.server.last_info = {
                'headers': self.headers,
                'method': 'GET',
        }
        self.send_request()

    def do_HEAD(self):
        """Serve a HEAD request."""
        if not self.server.allow_head:
            self.send_error(405, "Method not allowed")
            return

        self.server.last_info = {
                'headers': self.headers,
                'method': 'HEAD',
        }
        self.send_request(send_body=False)

    def do_POST(self):
        """Serve a GET request."""
        form = cgi.FieldStorage(fp=self.rfile,
                headers=self.headers,
                environ={
                    'REQUEST_METHOD':'POST',
                    'CONTENT_TYPE': self.headers['content-type'],
        })
        self.server.last_info = {
                'headers': self.headers,
                'method': 'POST',
                'post_data': form,
        }
        self.send_request()

    def send_head(self):
        """Common code for GET and HEAD commands.

        This sends the response code and MIME headers.

        Return value is either a file object (which has to be copied
        to the outputfile by the caller unless the command was HEAD,
        and must be closed by the caller under all circumstances), or
        None, in which case the caller has nothing further to do.

        """
        location_header = None
        self.start_pos = self.end_pos = -1
        headers_to_send = []
        if self.path == '/temp-redirect':
            code = 302
            location_header = self.build_url("test.txt")
            path = self.translate_path('redirect.html')
        elif self.path == '/perm-redirect':
            code = 301
            location_header = self.build_url("test.txt")
            path = self.translate_path('redirect.html')
        elif self.path == '/temp-then-perm-redirect':
            code = 302
            location_header = self.build_url("perm-redirect")
            path = self.translate_path('redirect.html')
        elif self.path == '/circular-redirect':
            code = 302
            location_header = self.build_url("circular-redirect2")
            path = self.translate_path('redirect.html')
        elif self.path == '/circular-redirect2':
            code = 302
            location_header = self.build_url("circular-redirect")
            path = self.translate_path('redirect.html')
        elif self.path == '/screen-redirect':
            code = 302
            location_header = self.build_url("linux-screen.jpg")
            path = self.translate_path('redirect.html')
        elif (self.path.startswith("/protected/") or
                self.path.startswith("/protected2/") or
                self.path.startswith("/protected3/")):
            # are password protected.  The data is always just test.txt
            auth = 'Basic ' + ('user:password'.encode("base64")[:-1])
            auth2 = 'Basic ' + ('user2:password2'.encode("base64")[:-1])
            # use [:-1] to cut off the trailing newline
            if (self.path.startswith("/protected/") or
                    self.path.startswith("/protected2/")):
                realm = "Secure Area"
            else:
                realm = "Secure Area2"
            if self.headers.get('authorization') in (auth, auth2):
                code = 200
                path = self.translate_path('test.txt')
            else:
                code = 401
                path = self.translate_path('auth-failed.txt')
                headers_to_send.append(('WWW-Authenticate',
                    'Basic realm="%s"' % realm))
        elif self.path.startswith("/digest-protected"):
            # Same as protected, but for digest auth
            # Implementation based on the RFC example
            # http://www.ietf.org/rfc/rfc2069.txt
            # We use RFC 2069 instead of RFC 2617 because it's easier to
            # implement

            # use [:-1] to cut off the trailing newline

            client_auth = self.headers.get('authorization')
            if client_auth is not None:
                client_auth = set(s.strip() for s in client_auth.split(','))
            correct_auth_response = set([
                'username="user"',
                 'realm="Secure Area Digest"',
                 'nonce="%s"' % self.digest_nonce,
                 'uri="%s"' % self.path,
                 'response="%s"' % self.calc_digest_response(),
                 'opaque="5ccc069c403ebaf9f0171e9517f40e41"'])

            if self.parse_client_digest_auth() == correct_auth_response:
                code = 200
                path = self.translate_path('test.txt')
            else:
                code = 401
                path = self.translate_path('auth-failed.txt')
                headers_to_send.append(('WWW-Authenticate',
                    'Digest '
                    'realm="Secure Area Digest", '
                    'nonce="%s", '
                    'opaque="5ccc069c403ebaf9f0171e9517f40e41"' %
                    self.digest_nonce))
        elif self.path.startswith("/invalid-auth/"):
            # send back an invalid auth header
            if self.path == '/invalid-auth/badscheme':
                header = 'FakeAuthScheme realm="Protected"'
            elif self.path == '/invalid-auth/norealm':
                header = 'Basic'
            elif self.path == '/invalid-auth/garbled':
                header = 'bsnth snatou sntaountsaouh'
            else:
                # default is a blank header
                header = ''

            code = 401
            path = self.translate_path('auth-failed.txt')
            headers_to_send.append(('WWW-Authenticate', header))
        else:
            code = 200
            path = self.translate_path(self.path)
        if 'range' in self.headers and self.server.allow_resume:
            range = self.headers['range']
            if range.startswith("bytes="):
                byte_range = range[len('bytes='):]
                start, end = byte_range.split('-')
                if start != '':
                    self.start_pos = int(start)
                if end != '':
                    self.end_pos = int(end)
                code = 206
                headers_to_send.append(('Content-Range', range))
        f = None
        try:
            f = open(path, 'rb')
        except IOError:
            self.send_error(404, "File not found")
            return None
        self.send_response(code)
        if location_header is not None:
            self.send_header("Location", location_header)
        fs = os.fstat(f.fileno())
        length = fs[6]
        if self.end_pos > 0:
            length = min(self.end_pos, length)
        if self.start_pos > 0:
            length -= self.start_pos
        if 'content-length' not in self.server.headers_to_send:
            self.send_header("Content-Length", str(length))
        self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
        for key, value in self.server.headers_to_send:
            self.send_header(key, value)
        for key, value in headers_to_send:
            self.send_header(key, value)
        self.end_headers()
        return f

    def parse_client_digest_auth(self):
        try:
            client_auth = self.headers['authorization']
        except KeyError:
            return None
        if not client_auth.lower().startswith("digest "):
            return None
        client_auth = client_auth[len("digest "):]
        return set(s.strip() for s in client_auth.split(','))

    def calc_digest_response(self):
        secret = 'user:Secure Area Digest:password'
        data = 'GET:' + self.path
        return md5(md5(secret) + ":" + self.digest_nonce + ":" + md5(data))

    def build_url(self, path):
        return 'http://localhost:%s/%s' % (self.server.port, path)

    def translate_path(self, path):
        """Translate a /-separated PATH to the local filename syntax.

        Components that mean special things to the local file system
        (e.g. drive or directory names) are ignored.  (XXX They should
        probably be diagnosed.)

        """
        # abandon query parameters
        path = path.split('?',1)[0]
        path = path.split('#',1)[0]
        path = posixpath.normpath(urllib.unquote(path))
        return resources.path("testdata/httpserver/%s" % path)

    def log_request(self, code):
        pass

    def log_error(self, *args):
        pass

class HTTPServer(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.event = threading.Event()

    def start(self):
        threading.Thread.start(self)
        self.event.wait()
        self.shutting_down = False
        self.httpserver.shutting_down = False

    def run(self):
        utils.begin_thread_loop(self)
        # try to find an open port
        for port in xrange(22200, 22300):
            if self._try_port(port):
                self.port = port
                break
        else:
            utils.finish_thread_loop(self)
            raise AssertionError("Can't find an open port")
        self.httpserver = BaseHTTPServer.HTTPServer(('', self.port),
                MiroHTTPRequestHandler)
        self.httpserver.allow_head = True
        self.httpserver.headers_to_send = []
        self.httpserver.port = self.port
        self.httpserver.close_connection = False
        self.httpserver.allow_resume = True
        self.httpserver.pause_after = -1
        self.event.set()
        try:
            self.httpserver.serve_forever()
        except socket.error:
            if not self.shutting_down:
                utils.finish_thread_loop(self)
                raise
        utils.finish_thread_loop(self)

    def stop(self):
        self.shutting_down = True
        self.httpserver.shutting_down = False
        if hasattr(self.httpserver, 'current_request_handler'):
            self.httpserver.current_request_handler.connection.close()
            self.httpserver.current_request_handler.finish()
        if hasattr(self.httpserver, 'shutdown'):
            self.httpserver.shutdown()
        else:
            self.socket.close()
        self.join()

    def _try_port(self, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(('', port))
        except socket.error:
            return False
        else:
            s.close()
            return True

    def build_url(self, path):
        return 'http://localhost:%s/%s' % (self.port, path)

    def last_info(self):
        return self.httpserver.last_info

    def disable_head_requests(self):
        self.httpserver.allow_head = False

    def add_header(self, key, value):
        self.httpserver.headers_to_send.append((key, value))

    def close_connection(self):
        self.httpserver.close_connection = True

    def disable_resume(self):
        self.httpserver.allow_resume = False

    def pause_after(self, bytes):
        self.httpserver.pause_after = bytes
