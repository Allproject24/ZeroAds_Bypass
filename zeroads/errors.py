class UnsupportedUrl(ValueError):
    pass

class DownloadFailure(RuntimeError):
    def __init__(self, message, manual_url=None):
        super().__init__(message)
        self.manual_url = manual_url
