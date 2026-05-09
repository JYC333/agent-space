from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import ContextBuildRequest, ContextPackage
from ..auth.api_key import get_identity
from .context_builder import ContextBuilder

router = APIRouter(prefix="/context", tags=["context"])


@router.post("/build", response_model=ContextPackage)
def build_context(
    req: ContextBuildRequest,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    builder = ContextBuilder(db)
    return builder.build(
        space_id=space_id,
        user_id=user_id,
        workspace_id=req.workspace_id,
        task_type=req.task_type,
        capability_id=req.capability_id,
        session_id=req.session_id,
        query=req.query,
    )
