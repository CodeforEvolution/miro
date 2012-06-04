import os

from miro import app
from miro import downloader
from miro import eventloop
from miro import models
from miro import prefs
from miro.test.framework import EventLoopTest, uses_httpclient

class DownloaderTest(EventLoopTest):
    """Test feeds that download things.
    """
    def setup_state(self):
        self.url = u'http://qa.pculture.org/feeds_test/unittest-feed-1.rss'
        self.feed = models.Feed(self.url)
        self.log_file = os.path.join(self.tempdir, 'miro-download-unit-tests')
        app.config.set(prefs.DOWNLOADER_LOG_PATHNAME, self.log_file)
        self.movies_dir = os.path.join(self.tempdir, 'movies-dir')
        if not os.path.exists(self.movies_dir):
            os.makedirs(self.movies_dir)
        app.config.set(prefs.MOVIES_DIRECTORY, self.movies_dir)

        # initialize and start the downloader after fixing the MOVIES_DIRECTORY
        # no need to create DownloadStateManager() object.  Aleady created.
        app.download_state_manager.init_controller()
        app.download_state_manager.startup_downloader()

    def tearDown(self):
        app.download_state_manager.shutdown_downloader(
                lambda: self.stopEventLoop(abnormal=False))
        self.runEventLoop()
        app.download_state_manager.daemon_starter = None
        EventLoopTest.tearDown(self)

    def run_eventloop_until_items(self):
        tracker = self.feed.items.make_tracker()
        tracker.connect('added', lambda view, obj: eventloop.shutdown())
        try:
            self.runEventLoop()
        finally:
            tracker.unlink()

    def run_eventloop_until_download(self):
        tracker = self.feed.downloaded_items.make_tracker()
        tracker.connect('added', lambda view, obj: eventloop.shutdown())
        try:
            self.runEventLoop()
        finally:
            tracker.unlink()

    def download_item(self):
        self.feed.update()
        self.run_eventloop_until_items()
        self.assertEquals(self.feed.items.count(), 1)
        i = list(self.feed.items)[0]
        i.download()
        self.run_eventloop_until_download()

    @uses_httpclient
    def test_download(self):
        self.setup_state()
        self.download_item()

    @uses_httpclient
    def test_delete(self):
        self.setup_state()
        self.download_item()
        self.assertEquals(self.feed.items.count(), 1)
        list(self.feed.items)[0].expire()

    ## def test_resume(self):
    ##     # FIXME - implement this
    ##     pass

    ## def test_resume_fail(self):
    ##     # FIXME - implement this
    ##     pass
