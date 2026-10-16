"""Google Drive access: locate the folder and tracker file, convert the xlsx once."""
from __future__ import annotations

import io
from typing import Optional

FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class DriveNotFoundError(Exception):
    """A folder or file the tracker needs does not exist."""


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class DriveGateway:
    def __init__(self, service):
        self._svc = service

    def _list(self, query: str) -> list:
        resp = self._svc.files().list(q=query, fields="files(id,name,mimeType)", pageSize=100,
                                      spaces="drive").execute()
        return resp.get("files", [])

    def find_folder(self, path: str) -> str:
        parent = "root"
        for part in [p for p in path.strip("/").split("/") if p]:
            found = self._list(f"name='{_esc(part)}' and mimeType='{FOLDER_MIME}' "
                               f"and '{parent}' in parents and trashed=false")
            if not found:
                raise DriveNotFoundError(f"Drive folder not found: {path} (missing '{part}')")
            parent = found[0]["id"]
        return parent

    def find_file(self, name: str, parent_id: str, mime: str) -> Optional[dict]:
        found = self._list(f"name='{_esc(name)}' and mimeType='{mime}' and '{parent_id}' in parents and trashed=false")
        return found[0] if found else None

    def convert_xlsx_to_sheet(self, xlsx_id: str, folder_id: str, title: str) -> str:
        """Upload a copy of the xlsx as a native Google Sheet; the original file is left untouched."""
        from googleapiclient.http import MediaIoBaseUpload
        content = self._svc.files().get_media(fileId=xlsx_id).execute()
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=XLSX_MIME, resumable=False)
        created = self._svc.files().create(
            body={"name": title, "mimeType": SHEET_MIME, "parents": [folder_id]},
            media_body=media, fields="id").execute()
        return created["id"]
