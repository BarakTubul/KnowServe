from pydantic import BaseModel
from typing import List

class CreateDocumentDTO(BaseModel):
    title: str
    source_url: str
    owner_department_id: int
    allowed_department_ids: List[int]


class UpdateAccessDTO(BaseModel):
    allowed_department_ids: List[int]