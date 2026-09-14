from sqlmodel import SQLModel, Field


class Setting(SQLModel, table=True):
    __tablename__ = "setting"
    key: str = Field(primary_key=True)
    value: str | None = None
