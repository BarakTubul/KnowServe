"""
Google Drive Client for KnowServe
Handles per-department uploads using folder IDs from environment variables.
"""

import io
import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2 import service_account
from app.config import settings


# 🔹 Department → Folder ID mapping from .env
DEPARTMENT_FOLDER_MAP = {
    "Engineering": os.getenv("DRIVE_FOLDER_ENGINEERING"),
    "Human Resources": os.getenv("DRIVE_FOLDER_HR"),
    "Finance": os.getenv("DRIVE_FOLDER_FINANCE"),
    "Marketing": os.getenv("DRIVE_FOLDER_MARKETING"),
    "Research & Development": os.getenv("DRIVE_FOLDER_RND"),
}


class GoogleDriveClient:
    def __init__(self, department_name: str):
        """
        Initialize the Drive client for a specific department.
        Each department has its own folder ID in Drive.
        """
        self.credentials_path = settings.CREDENTIALS_PATH

        self.scopes = ["https://www.googleapis.com/auth/drive.file"]
        self.folder_id = DEPARTMENT_FOLDER_MAP.get(department_name)

        if not self.folder_id:
            raise ValueError(f"No Google Drive folder configured for department '{department_name}'")

        self.drive_service = self._build_service()

    def _build_service(self):
        """Authenticate with the Google Drive API using the service account."""
        creds = service_account.Credentials.from_service_account_file(
            self.credentials_path, scopes=self.scopes
        )
        return build("drive", "v3", credentials=creds)

    async def upload_file(self, file):
        """
        Uploads a FastAPI UploadFile to the correct department folder in Google Drive.
        Returns the public URL (webViewLink).
        """
        try:
            metadata = {"name": file.filename, "parents": [self.folder_id]}
            media = MediaIoBaseUpload(io.BytesIO(await file.read()), mimetype=file.content_type)

            # Upload file
            uploaded = (
                self.drive_service.files()
                .create(body=metadata, media_body=media, fields="id, webViewLink")
                .execute()
            )

            file_id = uploaded["id"]
            web_link = uploaded["webViewLink"]

            # Make the file viewable by anyone with the link
            self.drive_service.permissions().create(
                fileId=file_id, body={"role": "reader", "type": "anyone"}
            ).execute()

            print(f"✅ [Drive] Uploaded '{file.filename}' to department folder '{self.folder_id}'")
            return {"file_id": file_id, "url": web_link}

        except Exception as e:
            print(f"❌ [Drive] Upload failed: {e}")
            raise

    def create_folder(self, name: str) -> dict:
        """
        Create a new folder in Google Drive (under the root, not per department).
        Returns its ID and webViewLink.
        """
        try:
            metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
            folder = (
                self.drive_service.files()
                .create(body=metadata, fields="id, webViewLink")
                .execute()
            )
            print(f"📁 [Drive] Created folder '{name}' ({folder['id']})")
            return folder
        except Exception as e:
            print(f"❌ [Drive] Folder creation failed: {e}")
            raise
