from sqlmodel import SQLModel, Field


class PaperDocument(SQLModel, table=True):
    __tablename__ = 'paperdocument'
    paper_id: int = Field(primary_key=True, foreign_key='paper.id', ondelete='CASCADE')
    run_id: str = ''
    source_hash: str = ''
    status: str = 'idle'
    mode: str = 'auto'
    model_config_id: int | None = None
    model_name: str = ''
    total_pages: int = 0
    pages_json: str = '[]'
    markdown: str = ''
    published_hash: str = ''
    error: str = ''
    index_status: str = ''
