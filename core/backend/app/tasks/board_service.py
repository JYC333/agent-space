from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session
from ulid import ULID

from app.models import Board, BoardColumn, Task, Workspace


def _new_id() -> str:
    return str(ULID())


_DEFAULT_COLUMN_DEFS: list[tuple[str, str, int, bool, bool]] = [
    ("Inbox", "inbox", 0, False, True),
    ("Ready", "ready", 1, False, False),
    ("In progress", "in_progress", 2, False, False),
    ("Needs review", "needs_review", 3, False, False),
    ("Done", "done", 4, True, False),
    ("Blocked", "blocked", 5, False, False),
    ("Cancelled", "cancelled", 6, False, False),
]


class BoardService:
    def __init__(self, db: Session):
        self.db = db

    def _validate_workspace(self, workspace_id: str, space_id: str) -> None:
        ws = self.db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not ws:
            raise HTTPException(status_code=400, detail=f"Workspace '{workspace_id}' not found")
        if ws.space_id != space_id:
            raise HTTPException(
                status_code=400,
                detail=f"Workspace '{workspace_id}' does not belong to this space",
            )

    def create_default_columns(self, board: Board) -> None:
        for name, status_key, position, is_done, is_default in _DEFAULT_COLUMN_DEFS:
            col = BoardColumn(
                id=_new_id(),
                space_id=board.space_id,
                board_id=board.id,
                name=name,
                description=None,
                status_key=status_key,
                position=position,
                wip_limit=None,
                is_done_column=is_done,
                is_default_column=is_default,
                metadata_json=None,
            )
            self.db.add(col)

    def create(
        self,
        *,
        space_id: str,
        user_id: str,
        name: str,
        description: Optional[str],
        workspace_id: Optional[str],
        board_type: str,
        status: str,
        default_view: Optional[str],
        sort_order: Optional[int],
        metadata_json: Optional[dict],
        create_default_columns: bool,
        agent_id: Optional[str] = None,
    ) -> Board:
        if workspace_id:
            self._validate_workspace(workspace_id, space_id)
        board = Board(
            id=_new_id(),
            space_id=space_id,
            workspace_id=workspace_id,
            name=name,
            description=description,
            board_type=board_type,
            status=status,
            default_view=default_view,
            sort_order=sort_order,
            metadata_json=metadata_json,
            created_by_user_id=user_id,
            created_by_agent_id=agent_id,
        )
        self.db.add(board)
        self.db.flush()
        if create_default_columns:
            self.create_default_columns(board)
        self.db.commit()
        self.db.refresh(board)
        return board

    def get(self, board_id: str, space_id: str) -> Board:
        b = (
            self.db.query(Board)
            .filter(Board.id == board_id, Board.space_id == space_id, Board.deleted_at.is_(None))
            .first()
        )
        if not b:
            raise HTTPException(status_code=404, detail="Board not found")
        return b

    def list_boards(
        self,
        space_id: str,
        *,
        include_archived: bool = False,
        workspace_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[Board]]:
        q = self.db.query(Board).filter(Board.space_id == space_id)
        if not include_archived:
            q = q.filter(Board.deleted_at.is_(None))
        if workspace_id:
            q = q.filter(Board.workspace_id == workspace_id)
        total = q.count()
        items = q.order_by(Board.sort_order.asc(), Board.created_at.desc()).offset(offset).limit(limit).all()
        return total, items

    def update(self, board_id: str, space_id: str, **fields) -> Board:
        board = self.get(board_id, space_id)
        for key, value in fields.items():
            if value is None and key != "deleted_at":
                continue
            if hasattr(board, key):
                setattr(board, key, value)
        board.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(board)
        return board

    def soft_delete(self, board_id: str, space_id: str) -> Board:
        return self.update(
            board_id,
            space_id,
            deleted_at=datetime.now(UTC),
            status="archived",
        )

    def list_columns(self, board_id: str, space_id: str) -> list[BoardColumn]:
        self.get(board_id, space_id)
        return (
            self.db.query(BoardColumn)
            .filter(
                BoardColumn.board_id == board_id,
                BoardColumn.space_id == space_id,
                BoardColumn.deleted_at.is_(None),
            )
            .order_by(BoardColumn.position.asc())
            .all()
        )

    def list_tasks_on_board(
        self,
        board_id: str,
        space_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[Task]]:
        self.get(board_id, space_id)
        q = self.db.query(Task).filter(
            Task.board_id == board_id,
            Task.space_id == space_id,
            Task.deleted_at.is_(None),
        )
        total = q.count()
        items = q.order_by(Task.updated_at.desc()).offset(offset).limit(limit).all()
        return total, items

    def resolve_column(self, column_id: str, board_id: str, space_id: str) -> BoardColumn:
        col = (
            self.db.query(BoardColumn)
            .filter(
                BoardColumn.id == column_id,
                BoardColumn.board_id == board_id,
                BoardColumn.space_id == space_id,
                BoardColumn.deleted_at.is_(None),
            )
            .first()
        )
        if not col:
            raise HTTPException(status_code=400, detail="Column not found for this board/space")
        return col
