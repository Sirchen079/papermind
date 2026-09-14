"""Claim-Evidence 图谱模型（P12）。

Claim：论文的一条可追溯论断（AI 抽取或用户手动添加）。
ClaimRelation：两条论断间的支持/矛盾/延伸关系（a < b 规范序存储，
唯一键保证重复分析不产生重复行）。
"""
from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.models.base import utcnow

CLAIM_KINDS = ("main", "supporting")
CLAIM_SOURCES = ("ai", "user")
CLAIM_RELATION_TYPES = ("supports", "contradicts", "extends")


class Claim(SQLModel, table=True):
    """One traceable claim made by a paper (extraction target or manual note)."""

    __tablename__ = "claim"

    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", index=True)
    text: str
    kind: str = Field(default="main")  # main | supporting
    source: str = Field(default="ai")  # ai | user
    excerpt_id: int | None = Field(default=None, foreign_key="paperexcerpt.id")
    is_deleted: bool = False
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class ClaimRelation(SQLModel, table=True):
    """A typed relation between two claims (supports / contradicts / extends).

    ``claim_a_id < claim_b_id`` is canonical so a pair + type exists at most
    once (unique constraint) — re-analysis stays idempotent.
    """

    __tablename__ = "claimrelation"
    __table_args__ = (
        UniqueConstraint("claim_a_id", "claim_b_id", "type", name="uq_claimrelation_a_b_type"),
    )

    id: int | None = Field(default=None, primary_key=True)
    claim_a_id: int = Field(foreign_key="claim.id", index=True)
    claim_b_id: int = Field(foreign_key="claim.id", index=True)
    type: str  # supports | contradicts | extends
    source: str = Field(default="ai")  # ai | user
    note: str | None = None
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
