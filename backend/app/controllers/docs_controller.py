from app.services.docs_service import DocsService

class DocsController:

    @staticmethod
    async def list_my_docs(current_user):
        # Admins see everything
        if current_user["role"] == "admin":
            return await DocsService.list_all()

        # Regular employees/managers see department docs
        department_id = current_user["department_id"]
        return await DocsService.list_allowed(department_id)
