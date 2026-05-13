from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.api_key import get_identity
from app.db import get_db
from app.schemas import BoardCreate, BoardOut, BoardUpdate, Page, TaskOut

from .board_service import BoardService

router = APIRouter(prefix="/boards", tags=["boards"])


@router.get("", response_model=Page[BoardOut])
def list_boards(
    workspace_id: str | None = Query(None),
    include_archived: bool = Query(False),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    svc = BoardService(db)
    total, items = svc.list_boards(
        space_id,
        include_archived=include_archived,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=BoardOut, status_code=201)
def create_board(
    data: BoardCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = BoardService(db)
    board = svc.create(
        space_id=space_id,
        user_id=user_id,
        name=data.name,
        description=data.description,
        workspace_id=data.workspace_id,
        board_type=data.board_type,
        status=data.status,
        default_view=data.default_view,
        sort_order=data.sort_order,
        metadata_json=data.metadata_json,
        create_default_columns=data.create_default_columns,
    )
    return board


@router.get("/{board_id}", response_model=BoardOut)
def get_board(
    board_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    return BoardService(db).get(board_id, space_id)


@router.patch("/{board_id}", response_model=BoardOut)
def patch_board(
    board_id: str,
    data: BoardUpdate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    fields = data.model_dump(exclude_unset=True)
    if fields.get("deleted_at") is not None and fields.get("status") is None:
        fields["status"] = "archived"
    return BoardService(db).update(board_id, space_id, **fields)


@router.get("/{board_id}/tasks", response_model=Page[TaskOut])
def list_board_tasks(
    board_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    total, items = BoardService(db).list_tasks_on_board(board_id, space_id, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)
