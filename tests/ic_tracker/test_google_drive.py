import pytest

from ic_tracker.google.drive import FOLDER_MIME, SHEET_MIME, XLSX_MIME, DriveGateway, DriveNotFoundError


class _Req:
    def __init__(self, value):
        self._v = value

    def execute(self):
        return self._v


class FakeDrive:
    def __init__(self, tree):
        self.tree = tree            # query substring -> list of file dicts
        self.queries = []
        self.created = None
        self.fetched = None
        self.media_bytes = b"xlsx-bytes"

    def files(self):
        return self

    def list(self, q, **kw):
        self.queries.append(q)
        for needle, files in self.tree.items():
            if needle in q:
                return _Req({"files": files})
        return _Req({"files": []})

    def get_media(self, fileId):
        self.fetched = fileId
        return _Req(self.media_bytes)

    def create(self, body, media_body, fields):
        self.created = (body, media_body)
        return _Req({"id": "NEW"})


def test_find_folder_walks_path_from_root():
    drive = FakeDrive({"name='Kids'": [{"id": "K"}], "name='Alex'": [{"id": "KK"}]})
    assert DriveGateway(drive).find_folder("Kids/Alex") == "KK"
    assert "'root' in parents" in drive.queries[0]
    assert "'K' in parents" in drive.queries[1]
    assert FOLDER_MIME in drive.queries[0] and "trashed=false" in drive.queries[0]


def test_find_folder_missing_raises():
    with pytest.raises(DriveNotFoundError) as err:
        DriveGateway(FakeDrive({})).find_folder("Kids/Alex")
    assert "Kids" in str(err.value)


def test_find_file_escapes_quotes_and_returns_first_or_none():
    drive = FakeDrive({"name='Kai\\'s": [{"id": "F1", "name": "x"}]})
    gw = DriveGateway(drive)
    assert gw.find_file("Kai's", "P", SHEET_MIME)["id"] == "F1"
    assert gw.find_file("Other", "P", SHEET_MIME) is None


def test_convert_xlsx_downloads_then_uploads_as_google_sheet():
    drive = FakeDrive({})
    new_id = DriveGateway(drive).convert_xlsx_to_sheet("XLSX", "FOLDER", "Assignments Tracker")
    body, media = drive.created
    assert new_id == "NEW" and drive.fetched == "XLSX"
    assert body == {"name": "Assignments Tracker", "mimeType": SHEET_MIME, "parents": ["FOLDER"]}
    assert media.mimetype() == XLSX_MIME
