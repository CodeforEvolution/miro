import functools
import os
import logging
import pycurl
import pickle
from cStringIO import StringIO

from miro import app
from miro import prefs
from miro import dialogs
from miro import eventloop
from miro import httpauth
from miro import httpclient
from miro import signals
from miro.plat import resources
from miro.test import mock
from miro.test.framework import EventLoopTest, uses_httpclient

from miro.gtcache import gettext as _

TEST_PATH = 'test.txt'

def uses_mock_httpclient(fun):
    def _uses_mock_httpclient(self):
        self.mocked_multi = httpclient.curl_manager.multi = mock.Mock()
        self.mocked_multi.timeout.return_value = -1
        self.mocked_multi.fdset.return_value = ([], [], [])
        self.mocked_multi.perform.return_value = (None, None)
        return fun(self)
    wrapped = functools.update_wrapper(_uses_mock_httpclient, fun)
    return uses_httpclient(wrapped)

class HTTPClientTestBase(EventLoopTest):
    def setUp(self):
        EventLoopTest.setUp(self)
        self.start_http_server()
        self.grab_url_info = self.grab_url_error = None
        self.expecting_errback = False
        self.event_loop_timeout = 1.0
        test_txt_path = resources.path("testdata/httpserver/test.txt")
        self.test_response_data = open(test_txt_path).read()

    def grab_url_callback(self, info):
        self.grab_url_info = info
        self.stopEventLoop(abnormal=False)

    def grab_url_errback(self, error):
        self.grab_url_error = error
        self.stopEventLoop(abnormal=False)

    def runEventLoop(self, timeout):
        EventLoopTest.runEventLoop(self, timeout=timeout)
        if self.grab_url_error is not None and not self.expecting_errback:
            raise AssertionError("grab_url error: %s" % self.grab_url_error)

    def grab_url(self, url, *args, **kwargs):
        self.grab_url_error = self.grab_url_info = None
        self.client = httpclient.grab_url(url, self.grab_url_callback,
                self.grab_url_errback, *args, **kwargs)
        self.runEventLoop(timeout=self.event_loop_timeout)

    def grab_headers(self, url, *args, **kwargs):
        self.grab_url_error = self.grab_url_info = None
        self.client = httpclient.grab_headers(url, self.grab_url_callback,
                self.grab_url_errback, *args, **kwargs)
        self.runEventLoop(timeout=self.event_loop_timeout)

    def check_errback_called(self):
        self.assertNotEquals(self.grab_url_error, None)
        self.assertEquals(self.grab_url_info, None)

    def check_nothing_called(self):
        self.assertEquals(self.grab_url_error, None)
        self.assertEquals(self.grab_url_info, None)

    def _write_partial_file(self, filename, bytes=30):
        # Write the start of test.txt to a file to test HTTP resume capability
        fp = open(filename, 'w')
        fp.write(self.test_response_data[:bytes])
        fp.close()

class HTTPClientTest(HTTPClientTestBase):
    @uses_httpclient
    def test_simple_get(self):
        self.grab_url(self.httpserver.build_url('test.txt'))
        self.assertEquals(self.grab_url_info['body'], self.test_response_data)

    @uses_httpclient
    def test_file_get(self):
        path = resources.path("testdata/httpserver/test.txt")
        self.grab_url("file://" + path)
        self.assertEquals(self.grab_url_info['body'], self.test_response_data)

    @uses_httpclient
    def test_simple_get_url_with_spaces(self):
        self.grab_url(self.httpserver.build_url('test%20with%20spaces.txt'))
        self.assertEquals(self.grab_url_info['body'], self.test_response_data)
        # Having spaces in the URL is not legal, but could happen in the wild.
        # We should work around buggy feeds.
        self.grab_url(self.httpserver.build_url('test with spaces.txt'))
        self.assertEquals(self.grab_url_info['body'], self.test_response_data)

    @uses_httpclient
    def test_gzip_get(self):
        self.httpserver.add_header("content-encoding", "gzip")
        self.grab_url(self.httpserver.build_url('test.txt.gz'))
        self.assertEquals(self.grab_url_info['body'], self.test_response_data)

    @uses_httpclient
    def test_unicode_url(self):
        self.grab_url(unicode(self.httpserver.build_url('test.txt')))
        self.assertEquals(self.grab_url_info['body'], self.test_response_data)

    def check_header(self, key, value):
        self.assertEqual(self.last_http_info('headers')[key], value)

    def check_header_not_present(self, key):
        self.assert_(key not in self.last_http_info('headers'))

    @uses_httpclient
    def test_etag(self):
        self.grab_url(self.httpserver.build_url('test.txt'))
        self.check_header_not_present('etag')
        self.grab_url(self.httpserver.build_url('test.txt'), etag='abcdef')
        self.check_header('etag', 'abcdef')

    @uses_httpclient
    def test_modified(self):
        m_str = 'Wed, 24 Mar 2010 01:31:03 GMT'
        self.grab_url(self.httpserver.build_url('test.txt'))
        self.check_header_not_present('if-modified-since')
        self.grab_url(self.httpserver.build_url('test.txt'), modified=m_str)
        self.check_header('if-modified-since', m_str)

    @uses_httpclient
    def test_unicode_values(self):
        self.grab_url(self.httpserver.build_url('test.txt'),
            modified= u'Wed, 24 Mar 2010 01:31:03 GMT',
            etag=u'abcdef')

    @uses_httpclient
    def test_post_vars(self):
        self.grab_url(self.httpserver.build_url('test.txt'),
                      post_vars={'abc': '123', 'foo': 'bar'})
        self.assertEqual(self.last_http_info('method'), 'POST')
        post_data = self.last_http_info('post_data')
        self.assertSameSet(post_data.keys(), ['abc', 'foo'])
        self.assertEquals(post_data.getvalue('abc'), '123')
        self.assertEquals(post_data.getvalue('foo'), 'bar')

    @uses_httpclient
    def test_post_files(self):
        f1 = {'filename': 'testing.txt',
                    'mimetype': 'text/plain',
                    'handle': StringIO('contents#1'),
        }
        f2 = {'filename': 'nulldata.dat',
                    'mimetype': 'application/unknown',
                    'handle': StringIO('abc\0\0def')
        }
        self.grab_url(self.httpserver.build_url('test.txt'),
                      post_vars={'abc': '123'},
                      post_files={'file1': f1, 'file2': f2})
        post_data = self.last_http_info('post_data')
        self.assertEquals(post_data.getvalue('abc'), '123')
        self.assertEquals(post_data.getvalue('file1'), 'contents#1')
        self.assertEquals(post_data.getvalue('file2'), 'abc\0\0def')

    def _test_head_common(self):
        url = self.httpserver.build_url('test.txt')
        self.grab_url(url)
        get_info = self.grab_url_info

        self.grab_headers(url)
        head_info = self.grab_url_info

        self.assertEquals(head_info['body'], '')

        self.assertSameSet(get_info.keys(), head_info.keys())
        for k in head_info:
            if k != 'body':
                if get_info[k] != head_info[k]:
                    raise AssertionError("values differ for key %s: %r, %r"
                            % (k, get_info[k], head_info[k]))

    @uses_httpclient
    def test_head(self):
        self._test_head_common()

    @uses_httpclient
    def test_head_get_fallback(self):
        self.httpserver.disable_head_requests()
        self._test_head_common()

    @uses_httpclient
    def test_info(self):
        self.httpserver.add_header('x-foo', 'bar')
        self.grab_url(self.httpserver.build_url('test.txt'))
        self.assertEquals(self.grab_url_info['x-foo'], 'bar')
        path = resources.path("testdata/httpserver/test.txt")
        self.assertEquals(self.grab_url_info['content-length'],
                len(open(path).read()))

    @uses_httpclient
    def test_info_header_callback(self):
        self.httpserver.add_header('x-foo', 'bar')

        def on_headers(headers):
            self.header_callback_info = headers.copy()
        self.grab_url(self.httpserver.build_url('test.txt'),
                      header_callback=on_headers)
        self.assertEquals(self.header_callback_info['x-foo'], 'bar')
        path = resources.path("testdata/httpserver/test.txt")
        self.assertEquals(self.header_callback_info['content-length'],
                len(open(path).read()))
        self.assert_('body' not in self.header_callback_info)

    def check_redirects(self, original, updated, redirected):
        info = self.grab_url_info
        self.assertEquals(info['original-url'],
                self.httpserver.build_url(original))
        self.assertEquals(info['updated-url'],
                self.httpserver.build_url(updated))
        self.assertEquals(info['redirected-url'],
                self.httpserver.build_url(redirected))

    @uses_httpclient
    def test_redirect(self):
        self.grab_url(self.httpserver.build_url('temp-redirect'))
        self.check_redirects('temp-redirect', 'temp-redirect', 'test.txt')
        self.grab_url(self.httpserver.build_url('perm-redirect'))
        self.check_redirects('perm-redirect', 'test.txt', 'test.txt')
        self.grab_url(self.httpserver.build_url('temp-then-perm-redirect'))
        self.check_redirects('temp-then-perm-redirect',
                'temp-then-perm-redirect', 'test.txt')
        # try the same thing with HEAD requests
        self.grab_headers(self.httpserver.build_url('temp-redirect'))
        self.check_redirects('temp-redirect', 'temp-redirect', 'test.txt')
        self.grab_headers(self.httpserver.build_url('perm-redirect'))
        self.check_redirects('perm-redirect', 'test.txt', 'test.txt')
        self.grab_headers(self.httpserver.build_url('temp-then-perm-redirect'))
        self.check_redirects('temp-then-perm-redirect',
                'temp-then-perm-redirect', 'test.txt')

    @uses_httpclient
    def test_redirect_headers(self):
        # check that we get the headers from the redirected URL, not the
        # original one
        def header_callback(headers):
            self.headers = headers
        self.grab_url(self.httpserver.build_url('temp-redirect'),
                header_callback=header_callback)
        self.assertEquals(self.headers['content-length'],
                len(self.test_response_data))

    @uses_httpclient
    def test_circular_redirect_headers(self):
        def header_callback(headers):
            self.headers = headers
        self.expecting_errback = True
        self.grab_url(self.httpserver.build_url('circular-redirect'),
                header_callback=header_callback)
        self.assert_(isinstance(self.grab_url_error,
            httpclient.TooManyRedirects))
        self.assert_(not hasattr(self, 'headers'))

    @uses_httpclient
    def test_filename(self):
        self.grab_url(self.httpserver.build_url("test.txt"))
        self.assertEqual(self.grab_url_info['filename'], 'test.txt')
        # redirects should use the last filename
        self.grab_headers(self.httpserver.build_url('temp-redirect'))
        self.assertEqual(self.grab_url_info['filename'], 'test.txt')
        # content-disposition overrides the default
        self.httpserver.add_header('Content-disposition',
                'filename="myfile.txt"; size=45')
        self.grab_url(self.httpserver.build_url("test.txt"))
        self.assertEqual(self.grab_url_info['filename'], 'myfile.txt')

    @uses_httpclient
    def test_charset(self):
        self.grab_url(self.httpserver.build_url("test.txt"))
        self.assertEquals(self.grab_url_info['charset'], 'iso-8859-1')

        self.httpserver.add_header("Content-Type", "text/html; charset=UTF-8")
        self.grab_url(self.httpserver.build_url("test.txt"))
        self.assertEquals(self.grab_url_info['charset'], 'UTF-8')

    @uses_httpclient
    def test_upload_progress(self):
        # upload a 100k file
        data = '0' * (1000 * 1024)
        f1 = {'filename': 'testing.txt',
                    'mimetype': 'text/plain',
                    'handle': StringIO(data),
        }
        self.event_loop_timeout = 5
        TIMEOUT = 0.001

        self.last_uploaded = None
        self.last_total = None
        self.saw_total = False
        def check_upload_progress():
            progress = self.client.get_stats()
            if progress.upload_total == -1:
                # client didn't know the total upload at this point.
                self.assertEquals(progress.uploaded, -1)
                eventloop.add_timeout(TIMEOUT, check_upload_progress,
                        'upload progress timeout')
                return
            self.saw_total = True

            if self.last_uploaded is not None:
                # the currently upload size should only increase
                self.assert_(progress.uploaded >= self.last_uploaded)
            self.last_uploaded = progress.uploaded

            if self.last_total is not None:
                # the total upload size shouldn't change
                self.assertEquals(progress.upload_total, self.last_total)
            self.last_total = progress.upload_total

            eventloop.add_timeout(TIMEOUT, check_upload_progress,
                    'upload progress timeout')

        eventloop.add_timeout(TIMEOUT, check_upload_progress,
                'upload progress timeout')
        self.grab_url(self.httpserver.build_url('test.txt'),
                post_files={'file1': f1})

        # make sure at least one of our sending_progress() calls worked
        self.assert_(self.saw_total)
        # there probably could be more tests but I'm not sure how to implement
        # them.

    @uses_httpclient
    def test_content_checker(self):
        def check_content(data):
            return True
        self.grab_url(self.httpserver.build_url('test.txt'),
                content_check_callback=check_content)
        self.assertEquals(self.grab_url_error, None)
        self.assertEquals(self.grab_url_info['body'], self.test_response_data)

    @uses_httpclient
    def test_content_checker_cancel(self):
        self.httpserver.pause_after(5)
        self.check_content_data = None
        def check_content(data):
            self.check_content_data = data
            if len(data) == 5:
                # wait a bit to see if any more data comes through, which it
                # shouldn't
                eventloop.add_timeout(0.2, self.stopEventLoop, 'stop download',
                        args=(False,))
                return False
            return True
        self.grab_url(self.httpserver.build_url('test.txt'),
                content_check_callback=check_content)
        self.assertEquals(self.grab_url_info, None)
        self.assertEquals(self.grab_url_error, None)
        self.assertEquals(self.check_content_data, 'Miro ')

    @uses_httpclient
    def test_content_checker_exception(self):
        self.httpserver.pause_after(5)
        self.check_content_data = None
        self.error_signal_okay = True
        def check_content(data):
            self.check_content_data = data
            if len(data) == 5:
                # wait a bit to see if any more data comes through, which it
                # shouldn't
                eventloop.add_timeout(0.2, self.stopEventLoop, 'stop download',
                        args=(False,))
                1/0
            return True
        self.grab_url(self.httpserver.build_url('test.txt'),
                content_check_callback=check_content)
        self.assertEquals(self.grab_url_info, None)
        self.assertEquals(self.grab_url_error, None)
        self.assertEquals(self.check_content_data, 'Miro ')
        self.assert_(self.saw_error)

    @uses_httpclient
    def test_write_file(self):
        filename = self.make_temp_path(".txt")
        self.grab_url(self.httpserver.build_url('test.txt'),
                write_file=filename)
        self.assert_('body' not in self.grab_url_info)
        self.assertEquals(open(filename).read(), self.test_response_data)

    @uses_httpclient
    def test_write_file_resume(self):
        filename = self.make_temp_path(".txt")
        initial_size = 5
        self._write_partial_file(filename, initial_size)
        self.grab_url(self.httpserver.build_url('test.txt'),
                write_file=filename, resume=True)
        self.assertEquals(open(filename).read(), self.test_response_data)
        self.check_header('Range', 'bytes=%d-' % initial_size)

    @uses_httpclient
    def test_write_file_no_resume(self):
        filename = self.make_temp_path(".txt")
        self._write_partial_file(filename)
        self.grab_url(self.httpserver.build_url('test.txt'),
                write_file=filename, resume=False)
        self.assertEquals(open(filename).read(), self.test_response_data)
        self.check_header_not_present('Range')

    @uses_httpclient
    def test_write_file_failed_resume(self):
        self.httpserver.disable_resume()
        self.expecting_errback = True
        filename = self.make_temp_path(".txt")
        self._write_partial_file(filename)
        self.grab_url(self.httpserver.build_url('test.txt'),
                write_file=filename, resume=True)
        self.assert_(isinstance(self.grab_url_error, httpclient.ResumeFailed))

    @uses_httpclient
    def test_resume_sizes(self):
        filename = self.make_temp_path(".txt")
        initial_size = 30
        self._write_partial_file(filename, initial_size)
        def on_headers(headers):
            self.headers = headers
        self.grab_url(self.httpserver.build_url('test.txt'),
                write_file=filename, resume=True, header_callback=on_headers)
        path = resources.path("testdata/httpserver/test.txt")
        file_size = len(open(path).read())
        download_size = file_size - initial_size
        self.assertEquals(self.headers['total-size'], file_size)
        self.assertEquals(self.headers['content-length'], file_size -
                initial_size)
        self.assertEquals(self.client.get_stats().downloaded, download_size)
        self.assertEquals(self.client.get_stats().initial_size, initial_size)

    @uses_httpclient
    def test_resume_no_file(self):
        filename = self.make_temp_path(".txt")
        self.grab_url(self.httpserver.build_url('test.txt'),
                write_file=filename, resume=True)
        self.assertEquals(open(filename).read(), self.test_response_data)
 
    @uses_httpclient
    def test_cancel(self):
        filename = self.make_temp_path(".txt")
        self.httpserver.pause_after(5)
        def cancel_after_5_bytes():
            if self.client.get_stats().downloaded == 5:
                self.client.cancel()
                self.stopEventLoop(False)
            else:
                eventloop.add_timeout(0.1, cancel_after_5_bytes, 'cancel')
        eventloop.add_timeout(0.1, cancel_after_5_bytes, 'cancel')
        self.expecting_errback = True
        self.grab_url(self.httpserver.build_url('test.txt'),
                write_file=filename)
        # Neither the callback, nor the errback should be called
        self.assertEquals(self.grab_url_info, None)
        self.assertEquals(self.grab_url_error, None)
        # We shouldn't delete the file
        self.assert_(os.path.exists(filename))

    @uses_httpclient
    def test_remove_file(self):
        filename = self.make_temp_path(".txt")
        self.httpserver.pause_after(5)
        def cancel_after_5_bytes():
            if self.client.get_stats().downloaded == 5:
                self.client.cancel(remove_file=True)
                self.stopEventLoop(False)
            else:
                eventloop.add_timeout(0.1, cancel_after_5_bytes, 'cancel')
        eventloop.add_timeout(0.1, cancel_after_5_bytes, 'cancel')
        self.expecting_errback = True
        self.grab_url(self.httpserver.build_url('test.txt'),
                write_file=filename)
        self.assertEquals(self.grab_url_info, None)
        self.assertEquals(self.grab_url_error, None)
        self.wait_for_libcurl_manager()
        self.assert_(not os.path.exists(filename))

class HTTPAuthTest(HTTPClientTestBase):
    def setUp(self):
        HTTPClientTestBase.setUp(self)
        self.setup_cancel()
        self.dialogs_seen = 0
        self.dialog_callback = None
        self.answer = None

    def setup_answer(self, username, password, button=dialogs.BUTTON_OK):
        self.answer = (unicode(username), unicode(password), button)

    def handle_new_dialog(self, obj, dialog):
        if self.answer is None:
            HTTPClientTestBase.handle_new_dialog(self, obj, dialog)

        self.dialogs_seen += 1
        if self.dialog_callback:
            self.dialog_callback()
        username, password, button = self.answer
        dialog.run_callback(button, username, password)

    def setup_cancel(self):
        self.setup_answer('', '', dialogs.BUTTON_CANCEL)

    def check_auth_errback_called(self):
        self.check_errback_called()
        self.assert_(isinstance(self.grab_url_error,
            httpclient.AuthorizationFailed))

    def check_auth_canceled(self):
        self.check_errback_called()
        self.assert_(isinstance(self.grab_url_error,
            httpclient.AuthorizationCanceled))

    @uses_httpclient
    def test_auth_failed(self):
        self.expecting_errback = True
        self.setup_cancel()
        self.grab_url(self.httpserver.build_url('protected/index.txt'))
        self.check_auth_canceled()

        self.setup_answer("wronguser", "wrongpass")
        self.grab_url(self.httpserver.build_url('protected/index.txt'))
        self.check_auth_errback_called()

    @uses_httpclient
    def test_auth_correct(self):
        self.setup_answer("user", "password")
        self.grab_url(self.httpserver.build_url('protected/index.txt'))
        self.assertEquals(self.dialogs_seen, 1)

    @uses_httpclient
    def test_auth_with_write_file(self):
        # check that if the auth fails, we don't write data to our file
        filename = self.make_temp_path(".txt")
        self.setup_answer("user", "wrongpassword")
        self.expecting_errback = True
        self.grab_url(self.httpserver.build_url('protected/index.txt'),
                write_file=filename)
        self.assertEquals(open(filename).read(), "")

    @uses_httpclient
    def test_auth_failed_with_write_file_resume(self):
        # check the corner case where are resuming a transfer, but we are
        # getting back an auth failed response
        filename = self.make_temp_path(".txt")
        # write more data than is contained in our auth failed response.  We
        # should still get a AuthorizationFailed, rather than a ResumeFailed
        # response.
        self._write_partial_file(filename, 30)
        self.setup_answer("user", "wrongpassword")
        self.expecting_errback = True
        self.grab_url(self.httpserver.build_url('protected/index.txt'),
                write_file=filename, resume=True)
        self.check_auth_errback_called()

    @uses_httpclient
    def test_auth_success_with_write_file_resume(self):
        # check this corner case when we are resuming a transfer:
        #  - we get an auth failed response
        #  - we then send the correct credentials
        # In this case, we have to make sure that the initial auth failed
        # reponse didn't mess up the resume.
        filename = self.make_temp_path(".txt")
        # write more data than is contained in our auth failed response.
        self._write_partial_file(filename, 30)
        self.setup_answer("user", "password")
        self.grab_url(self.httpserver.build_url('protected/index.txt'),
                write_file=filename, resume=True)
        self.assertEquals(self.dialogs_seen, 1)
        self.assertEquals(open(filename).read(), self.test_response_data)

    @uses_httpclient
    def test_auth_memory(self):
        self.setup_answer("user", "password")
        self.grab_url(self.httpserver.build_url('protected/index.txt'))
        self.assertEquals(self.dialogs_seen, 1)
        # We shouldn't see another dialog for the same URL
        self.grab_url(self.httpserver.build_url('protected/index.txt'))
        self.assertEquals(self.dialogs_seen, 1)
        # ditto for ones in the same directory
        self.grab_url(self.httpserver.build_url('protected/index2.txt'))
        self.assertEquals(self.dialogs_seen, 1)
        # Even for ones in a subdirectory
        self.grab_url(self.httpserver.build_url('protected/foo/index2.txt'))
        self.assertEquals(self.dialogs_seen, 1)
        # Now time to test the internals of re-using HTTP auth for things
        # outside the subdirectory.  This is complicated because if things are
        # outside the subdirectory, then we can re-use the auth only if the
        # realm is the same.

        # This one is outside the subdirectory, but it's www-authenticate
        # header returns the same realm.  We shouldn't need a new dialog.
        self.grab_url(self.httpserver.build_url('protected2/index.txt'))
        self.assertEquals(self.dialogs_seen, 1)
        # This one is outside the subdirectory, and it's in a different realm.
        # We should see a new dialog
        self.grab_url(self.httpserver.build_url('protected3/index.txt'))
        self.assertEquals(self.dialogs_seen, 2)

    @uses_httpclient
    def test_digest_auth_failed(self):
        self.expecting_errback = True
        self.setup_cancel()
        self.grab_url(self.httpserver.build_url('digest-protected/index.txt'))
        self.check_auth_canceled()

        self.setup_answer("wronguser", "wrongpass")
        self.grab_url(self.httpserver.build_url('digest-protected/index.txt'))
        self.check_auth_errback_called()

    @uses_httpclient
    def test_digest_auth_correct(self):
        self.setup_answer("user", "password")
        self.grab_url(self.httpserver.build_url('digest-protected/index.txt'))
        self.assertEquals(self.dialogs_seen, 1)

    @uses_httpclient
    def test_auth_overwrite(self):
        "Test that new passwords overwrite old ones"
        self.expecting_errback = True
        self.assertEquals(len(httpauth.password_list.passwords), 0)
        self.setup_answer("user", "password")
        self.grab_url(self.httpserver.build_url('protected/subdir/index.txt'))
        self.setup_answer("user2", "password2")
        self.grab_url(self.httpserver.build_url('protected/subdir/index.txt'))
        self.assertEquals(len(httpauth.password_list.passwords), 1)

    @uses_httpclient
    def test_digest_auth_memory(self):
        self.setup_answer("user", "password")
        self.grab_url(self.httpserver.build_url('digest-protected/index.txt'))
        self.assertEquals(self.dialogs_seen, 1)
        # We shouldn't see another dialog for the same URL
        self.grab_url(self.httpserver.build_url('digest-protected/index.txt'))
        self.assertEquals(self.dialogs_seen, 1)
        # ditto for ones in the same directory
        self.grab_url(self.httpserver.build_url('digest-protected/index2.txt'))
        self.assertEquals(self.dialogs_seen, 1)
        # Even for ones in a subdirectory
        self.grab_url(self.httpserver.build_url(
                'digest-protected/foo/index2.txt'))
        self.assertEquals(self.dialogs_seen, 1)
        # Or even for ones outside the directory (only true for digest auth)
        self.grab_url(self.httpserver.build_url('digest-protected2/index.txt'))
        self.assertEquals(self.dialogs_seen, 1)

    @uses_httpclient
    def test_max_attempts(self):
        self.expecting_errback = True
        self.setup_answer("wronguser", "wrongpass")
        self.grab_url(self.httpserver.build_url('protected/index.txt'))
        self.assertEquals(self.dialogs_seen, httpclient.MAX_AUTH_ATTEMPTS)

    @uses_httpclient
    def test_quick_cancel(self):
        # Try canceling before find_http_auth returns and make sure things
        # work.
        self.setup_answer("user", "password")
        url = self.httpserver.build_url('protected/index.txt')
        self.grab_url_error = self.grab_url_info = None
        self.client = httpclient.grab_url(url, self.grab_url_callback,
                self.grab_url_errback)
        # at this point, our client should be finding the HTTP auth.  It
        # shouldn't have started transfering data.
        self.assertEquals(len(httpclient.curl_manager.transfer_map), 0)
        self.client.cancel()
        self.expecting_errback = True
        eventloop.add_timeout(0.2, self.stopEventLoop, 'stopping event loop',
                args=(False,))
        self.runEventLoop(timeout=self.event_loop_timeout)
        # make sure that the callback/errback weren't called and nothing is
        # transfering
        self.check_nothing_called()
        self.assertEquals(len(httpclient.curl_manager.transfer_map), 0)

    @uses_httpclient
    def test_cancel_while_waiting(self):
        # Try canceling while we're waiting for the user to put in the
        def on_dialog():
            self.client.cancel()
            eventloop.add_timeout(0.2, self.stopEventLoop,
                    'stopping event loop', args=(False,))
        self.dialog_callback = on_dialog
        self.setup_answer("user", "password")
        self.grab_url(self.httpserver.build_url('protected/index.txt'))
        # make sure that the callback/errback weren't called and nothing is
        # transfering
        self.check_nothing_called()
        self.assertEquals(len(httpclient.curl_manager.transfer_map), 0)

    @uses_httpclient
    def test_store(self):
        self.setup_answer("user", "password")
        self.grab_url(self.httpserver.build_url('protected/index.txt'))
        self.assertEquals(self.dialogs_seen, 1)
        # write out the data
        store_path = self.make_temp_path('.json')
        httpauth.write_to_file(store_path)
        # reset the data, check that we get a new dialog
        httpauth.init()
        self.grab_url(self.httpserver.build_url('protected/index.txt'))
        self.assertEquals(self.dialogs_seen, 2)
        # reset the data, then restore from file.  We shouldn't get a new
        # dialog this time
        httpauth.init()
        httpauth.restore_from_file(store_path)
        self.grab_url(self.httpserver.build_url('protected/index.txt'))
        self.assertEquals(self.dialogs_seen, 2)

    @uses_httpclient
    def test_bad_auth(self):
        self.setup_answer("user", "password")
        self.expecting_errback = True

        # test when schemes that aren't "basic" or "digest"
        self.grab_url(self.httpserver.build_url('invalid-auth/badscheme'))
        self.assert_(isinstance(self.grab_url_error,
            httpclient.AuthorizationFailed))
        # when we get invalid auth headers, we shouldn't pop up dialogs for
        # the user
        self.assertEquals(self.dialogs_seen, 0)

        # test auth header without realm
        self.grab_url(self.httpserver.build_url('invalid-auth/norealm'))
        self.assert_(isinstance(self.grab_url_error,
            httpclient.AuthorizationFailed))
        self.assertEquals(self.dialogs_seen, 0)

        # test completely garbled auth header
        self.grab_url(self.httpserver.build_url('invalid-auth/garbled'))
        self.assert_(isinstance(self.grab_url_error,
            httpclient.AuthorizationFailed))
        self.assertEquals(self.dialogs_seen, 0)

        # test auth header with no data
        self.grab_url(self.httpserver.build_url('invalid-auth/'))
        self.assert_(isinstance(self.grab_url_error,
            httpclient.AuthorizationFailed))
        self.assertEquals(self.dialogs_seen, 0)

class HTTPAuthBackendTest(EventLoopTest):
    """ Test using the  httpauth module directly.

    We can do test certain things here that we can't in HTTPAuthTest, for
    example hostnames other than localhost
    """

    def setUp(self):
        self.dialogs_seen = 0
        EventLoopTest.setUp(self)

    def handle_new_dialog(self, obj, dialog):
        self.dialogs_seen += 1
        dialog.run_callback(dialogs.BUTTON_OK, u'user', u'password')

    def callback(self, auth):
        self.callback_data = auth
        self.stopEventLoop(abnormal=False)

    def ask_for_http_auth(self, url, auth_header):
        httpauth.ask_for_http_auth(self.callback, url, auth_header,
                "My Location")
        self.runEventLoop(timeout=0.1)
        return self.callback_data

    def test_simple(self):
        url = 'http://example.com/foo.html'
        header = 'Basic realm="Protected Space"'
        self.assertEquals(httpauth.find_http_auth(url), None)
        auth = self.ask_for_http_auth(url, header)
        self.assertEquals(auth.username, 'user')
        self.assertEquals(auth.password, 'password')
        self.assertEquals(auth.scheme, 'basic')

    def test_bad_auth_header(self):
        # See #14973 for an example of this in the wild
        url = 'http://example.com/foo.html'
        header = '' # blank header should definitely raise an error
        self.assertRaises(ValueError, httpauth.ask_for_http_auth,
                self.callback, url, header, 'My Location')

    def test_basic_reuse(self):
        header = 'Basic realm="Protected Space"'
        url = 'http://example.com/foo/test.html'
        # we should re-use the auth credentials for urls in the same directory
        url2 = 'http://example.com/foo/test2.html'
        url3 = 'http://example.com/foo/bar/test2.html'
        # but not for ones outside
        url4 = 'http://example.com/test.html'
        url5 = 'http://example2.com/foo/test.html'
        auth = self.ask_for_http_auth(url, header)
        self.assertEquals(httpauth.find_http_auth(url), auth)
        self.assertEquals(httpauth.find_http_auth(url2), auth)
        self.assertEquals(httpauth.find_http_auth(url3), auth)
        self.assertEquals(httpauth.find_http_auth(url4), None)
        self.assertEquals(httpauth.find_http_auth(url5), None)
        # however, if we know the www-authenticate header (and thus the
        # realm), then we can re-use the credentials
        self.assertEquals(httpauth.find_http_auth(url4, header), auth)
        # but not if the realm is different or the root url
        self.assertEquals(httpauth.find_http_auth(url5, header), None)
        self.assertEquals(httpauth.find_http_auth(url5,
            'Basic realm="Other Protected Space"'), None)

    def test_remove(self):
        url = 'http://example.com/foo.html'
        header = 'Basic realm="Protected Space"'
        auth = self.ask_for_http_auth(url, header)
        self.assertEquals(httpauth.find_http_auth(url, header), auth)
        httpauth.remove(auth)
        self.assertEquals(httpauth.find_http_auth(url, header), None)

    def test_basic_two_domains_same_realm(self):
        # test that if two domains have the same realm, we don't allow 1
        # password to overwrite the other #14613
        header = 'Basic realm="Protected Space"'
        url = 'http://example.com/foo/test.html'
        url2 = 'http://example2.com/foo/test.html'
        start_count = len(httpauth.password_list.passwords)
        self.ask_for_http_auth(url, header)
        self.assertEquals(len(httpauth.password_list.passwords), start_count+1)
        self.ask_for_http_auth(url2, header)
        self.assertEquals(len(httpauth.password_list.passwords), start_count+2)
        # same thing with digest auth
        header = 'Digest realm="Protected Space",nonce="123"'
        self.ask_for_http_auth(url, header)
        self.assertEquals(len(httpauth.password_list.passwords), start_count+3)
        self.ask_for_http_auth(url2, header)
        self.assertEquals(len(httpauth.password_list.passwords), start_count+4)

    def test_digest_reuse(self):
        header = 'Digest realm="Protected Space",nonce="123"'
        url = 'http://example.com/foo/test.html'
        # we should re-use the auth credentials for all urls in the same server
        url2 = 'http://example.com/foo/test2.html'
        url3 = 'http://example.com/foo/bar/test2.html'
        url4 = 'http://example.com/test.html'
        # but not for ones outside
        url5 = 'http://example2.com/foo/test.html'
        auth = self.ask_for_http_auth(url, header)
        self.assertEquals(httpauth.find_http_auth(url), auth)
        self.assertEquals(httpauth.find_http_auth(url2), auth)
        self.assertEquals(httpauth.find_http_auth(url3), auth)
        self.assertEquals(httpauth.find_http_auth(url4), auth)
        self.assertEquals(httpauth.find_http_auth(url5), None)

    def test_digest_reuse_with_domain(self):
        header = ('Digest realm="Protected Space",nonce="123",'
                'domain="/metoo,http://metoo.com/,http://example2.com/metoo"')
        url = 'http://example.com/foo/test.html'
        # we should re-use the auth credentials for urls specified in domain
        url2 = 'http://example.com/metoo/'
        url3 = 'http://example.com/metoo/index.html/'
        url4 = 'http://metoo.com/'
        url5 = 'http://example2.com/metoo/'
        # but not for ones outside
        url6 = 'http://example.com/notmetoo/index.html/'
        url7 = 'http://notmetoo.com/'
        url8 = 'http://example2.com/notmetoo/'

        auth = self.ask_for_http_auth(url, header)
        self.assertEquals(httpauth.find_http_auth(url), auth)
        self.assertEquals(httpauth.find_http_auth(url2), auth)
        self.assertEquals(httpauth.find_http_auth(url3), auth)
        self.assertEquals(httpauth.find_http_auth(url4), auth)
        self.assertEquals(httpauth.find_http_auth(url5), auth)

        self.assertEquals(httpauth.find_http_auth(url6), None)
        self.assertEquals(httpauth.find_http_auth(url7), None)
        self.assertEquals(httpauth.find_http_auth(url8), None)

class HTTPAuthBackendTestDLDaemonVersion(HTTPAuthBackendTest):
    """Same tests as HTTPAuthBackendTest, using dl_daemon.private.httpauth
    """
    def setUp(self):
        HTTPAuthBackendTest.setUp(self)

        # seed http auth with some initial data
        url = 'http://oldserver.com/foo.html'
        header = 'Basic realm="Old Protected Space"'
        self.ask_for_http_auth(url, header)

        from miro.dl_daemon import daemon

        class FakeDaemon(daemon.ControllerDaemon):
            def __init__(self):
                self.shutdown = False
                self._setup_httpauth()

            def send(self, command, callback):
                # run the command back and forth through pickle to simulate
                # sending it over the wire.  This ensures ojects things like
                # lists are seen as copies rather than the same object (see
                # UpdatePasswords for an example).  We could use the copy
                # module, but I (BDK) wanted to simulate what happens between
                # the downloader and main process as closely as possible.
                command = pickle.loads(pickle.dumps(command))
                command.set_daemon(self)
                command.action()

        from miro.dl_daemon.private import httpauth
        httpauth.update_passwords([])
        daemon.LAST_DAEMON = FakeDaemon()
        globals()['httpauth'] = httpauth
        # make sure the UpdatePasswords command gets sent now
        self.runPendingIdles()

    def tearDown(self):
        from miro import httpauth
        from miro.dl_daemon import daemon
        globals()['httpauth'] = httpauth
        daemon.LAST_DAEMON._remove_httpauth_callback()
        HTTPAuthBackendTest.tearDown(self)

    def test_initial_list(self):
        """Test that the initial auth data gets sent to the daemon.  """

        # this was setup before the daemon started, we should not need to
        # re-enter it.
        url = 'http://oldserver.com/foo.html'
        auth = httpauth.find_http_auth(url)
        self.assertNotEquals(auth, None)
        self.assertEquals(auth.username, 'user')
        self.assertEquals(auth.password, 'password')

    def test_remove_from_main_process(self):
        # This is test_remove using the daemon's httpauth.py, but we also test
        # that it's removed from the main process
        import miro.httpauth
        url = 'http://example.com/foo.html'
        header = 'Basic realm="Protected Space"'
        auth = self.ask_for_http_auth(url, header)
        self.assertEquals(httpauth.find_http_auth(url, header), auth)
        self.assertEquals(miro.httpauth.find_http_auth(url, header), auth)
        httpauth.remove(auth)
        # wait for RemoveHTTPAuthCommand to be run
        self.runPendingIdles()
        self.assertEquals(httpauth.find_http_auth(url, header), None)
        self.assertEquals(miro.httpauth.find_http_auth(url, header), None)

class BadURLTest(HTTPClientTestBase):
    def setUp(self):
        HTTPClientTestBase.setUp(self)
        self.expecting_errback = True

    @uses_httpclient
    def test_scheme(self):
        self.grab_url('pculture.org/normalpage.txt')
        self.check_errback_called()
        self.assert_(isinstance(self.grab_url_error, httpclient.MalformedURL))

    @uses_httpclient
    def test_slashes(self):
        self.grab_url('http:jigsaw.w3.org/HTTP/')
        self.check_errback_called()
        self.assert_(isinstance(self.grab_url_error, httpclient.MalformedURL))

    @uses_httpclient
    def test_host(self):
        self.grab_url('http:///HTTP/')
        self.check_errback_called()
        self.assert_(isinstance(self.grab_url_error, httpclient.MalformedURL))

    @uses_httpclient
    def test_other_scheme(self):
        self.grab_url('rtsp://jigsaw.w3.org/')
        self.check_errback_called()
        self.assert_(isinstance(self.grab_url_error, httpclient.MalformedURL))

class NetworkErrorTest(HTTPClientTestBase):
    def setUp(self):
        HTTPClientTestBase.setUp(self)
        self.expecting_errback = True

    @uses_httpclient
    def test_connect_error(self):
        self.grab_url('http://255.255.255.255/')
        self.check_errback_called()
        # The http proxy always replies with something, (probably a 40x or
        # 50x message) so we should not check against this as it will
        # be unreliable when the proxy is active.
        if app.config.get(prefs.HTTP_PROXY_ACTIVE):
            logging.info('Proxy active: skipping specific connection error '
                         'check')
        else:
            self.assert_(isinstance(self.grab_url_error,
                httpclient.ConnectionError))

    @uses_httpclient
    def test_closed_connection_error(self):
        self.httpserver.add_header('content-length', 100000)
        self.httpserver.close_connection()
        self.grab_url(self.httpserver.build_url('test.txt'))
        self.check_errback_called()
        self.assert_(isinstance(self.grab_url_error,
            httpclient.ServerClosedConnection))

    @uses_httpclient
    def test_404_error(self, write_file=None):
        self.expecting_errback = True
        url = self.httpserver.build_url('badfile.txt')
        self.grab_url(url, write_file=write_file)
        self.assert_(isinstance(self.grab_url_error,
            httpclient.UnexpectedStatusCode))
        # FIXME: It'd be nice if we could check a HTTP code rather than a
        # static message.
        self.assertEquals(self.grab_url_error.friendlyDescription,
                _("File not found"))
        if write_file:
            self.assertEquals(open(write_file).read(), '')

    def test_error_nofile(self):
        write_file = self.make_temp_path(".txt")
        self.test_404_error(write_file=write_file)

    @uses_mock_httpclient
    def test_bad_domain_name(self):
        def mock_add_handle(handle):
            error = (handle, pycurl.E_COULDNT_RESOLVE_HOST, 'fake message')
            self.mocked_multi.info_read.return_value = ([], [], [error])
        self.mocked_multi.add_handle.side_effect = mock_add_handle
        self.grab_url('http://pculture.org/')
        self.check_errback_called()
        self.assert_(isinstance(self.grab_url_error,
            httpclient.UnknownHostError))

    @uses_httpclient
    def test_unknown_error(self):
        # This is a bit of a weird test.  We want to test the generic libcurl
        # error handle.  However, that code is only a fallback for libcurl
        # error codes that we don't know how to handle.  If we know a way to
        # produce that, then we should fix that code and add a handler for
        # that case.
        #
        # To test things, we manually call CurlTransfer.on_error(), which is
        # the method responsible for dealing with libcurl errors.
        class BogusLibcurlHandle:
            def errstr(self):
                return 'libcurl error'
        options = httpclient.TransferOptions("http://example.com/")
        bogus_transfer = httpclient.CurlTransfer(options,
                self.grab_url_callback, self.grab_url_errback)
        bogus_transfer.on_error(123456, BogusLibcurlHandle())
        self.runPendingIdles()

        # Check that we saw a NetworkError and that the description strings
        # are unicode (#13359)
        self.check_errback_called()
        self.assert_(isinstance(self.grab_url_error,
            httpclient.NetworkError))
        self.assert_(isinstance(self.grab_url_error.longDescription, unicode))
        self.assert_(isinstance(self.grab_url_error.friendlyDescription, unicode))
