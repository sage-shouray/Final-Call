"""FastAPI dependency factories for all repositories.

Usage in a router:
    from src.repositories.deps import get_document_repo
    ...
    async def my_route(repo: Annotated[DocumentRepository, Depends(get_document_repo)]):
        ...
"""
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.repositories.audit_repository import AuditRepository
from src.repositories.document_repository import DocumentRepository
from src.repositories.user_repository import UserRepository

# Shared DB dependency type alias
DBDep = Annotated[AsyncSession, Depends(get_db)]


async def get_document_repo(session: DBDep) -> AsyncGenerator[DocumentRepository, None]:
    yield DocumentRepository(session)


async def get_audit_repo(session: DBDep) -> AsyncGenerator[AuditRepository, None]:
    yield AuditRepository(session)


async def get_user_repo(session: DBDep) -> AsyncGenerator[UserRepository, None]:
    yield UserRepository(session)
