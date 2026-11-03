"""Stand-ins for the network and the system installer."""


class FakeReleases:
    """A release feed that never touches the network."""

    def __init__(self, release=None):
        self.release = release
        self.downloads = []

    def latest(self):
        return self.release

    def download(self, asset, progress):
        progress(asset.size // 2, asset.size)
        progress(asset.size, asset.size)
        self.downloads.append(asset.name)
        return f"/tmp/{asset.name}"


class FakeInstaller:
    def __init__(self, supported=True, takes_over=False):
        self._supported = supported
        self.takes_over = takes_over
        self.installed = []

    def supported(self):
        return self._supported

    def pick(self, assets):
        return next((a for a in assets if a.name.endswith(".deb")), None)

    def install(self, path):
        self.installed.append(path)
        return self.takes_over
