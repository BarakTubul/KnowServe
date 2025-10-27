from typing import List
from fastapi import UploadFile, File, Form


class DocumentUploadForm:
    """
    Form schema for uploading multiple documents to department folders.
    Used with multipart/form-data requests.
    """

    # The actual files
    files: List[UploadFile] = File(...)

    # The user-assigned titles for each file (same order as files)
    names: List[str] = Form(...)

    # Department(s) related to the upload
    department_ids: List[int] = Form(...)