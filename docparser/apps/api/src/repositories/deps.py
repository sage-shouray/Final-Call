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
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.database import get_db
from src.repositories.audit_repository import AuditRepository
from src.repositories.document_repository import DocumentRepository
from src.repositories.user_repository import UserRepository

# Shared DB dependency type alias
DBDep = Annotated[AsyncIOMotorDatabase, Depends(get_db)]  # type: ignore[type-arg]


async def get_document_repo(db: DBDep) -> AsyncGenerator[DocumentRepository, None]:
    yield DocumentRepository(db)


async def get_audit_repo(db: DBDep) -> AsyncGenerator[AuditRepository, None]:
    yield AuditRepository(db)


async def get_user_repo(db: DBDep) -> AsyncGenerator[UserRepository, None]:
    yield UserRepository(db)
