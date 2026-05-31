from typing import Any, Literal

from pydantic import BaseModel, Field


class PropertyOut(BaseModel):
    property_code: str
    property_name: str | None = None
    official_property_name: str | None = None
    address: str | None = None
    website_url: str | None = None
    scrape_enabled: bool = False
    match_confidence: str | None = None
    has_rent_roll_snapshots: bool = False
    has_website_pages: bool = False
    rent_roll_snapshot_count: int = 0
    website_page_count: int = 0

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=3)
    property_code: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=6000)
    selected_model: str | None = None


class Source(BaseModel):
    title: str | None = None
    url: str | None = None
    snippet: str | None = None


class Followup(BaseModel):
    label: str
    question: str
    route_hint: str | None = None


class ResponseComponent(BaseModel):
    type: Literal["kpi_cards", "table", "bar_chart", "line_chart"]
    title: str
    data: list[dict[str, Any]] | None = None
    columns: list[str] | None = None
    rows: list[dict[str, Any]] | list[list[Any]] | None = None
    x_key: str | None = None
    y_key: str | None = None


class ChatMetadata(BaseModel):
    property_code: str
    model: str
    tools_used: list[str] = []
    route: str = "CHAT"


class ChatResponse(BaseModel):
    answer_markdown: str
    components: list[ResponseComponent] = []
    sources: list[Source] = []
    followups: list[Followup] = []
    metadata: ChatMetadata


class DiagnosticsOut(BaseModel):
    db_connected: bool
    db_error_type: str | None = None
    db_error_message: str | None = None
    database_url_shape: dict[str, Any] | None = None
    cloudsql_dir_exists: bool | None = None
    cloudsql_entries: list[str] = Field(default_factory=list)
    expected_cloudsql_instance: str | None = None
    expected_cloudsql_socket_path_exists: bool | None = None
    property_count: int
    properties_count: int = 0
    snapshot_count: int = 0
    snapshots_count: int = 0
    rent_roll_row_count: int
    rent_roll_rows_count: int = 0
    summary_group_count: int = 0
    summary_groups_count: int = 0
    charge_summary_count: int = 0
    charge_summaries_count: int = 0
    future_resident_count: int = 0
    future_residents_count: int = 0
    website_page_count: int
    website_pages_count: int = 0
    chroma_chunks_count: int | None = None
    chroma_collection_status: dict[str, Any]
    available_models: list[str]
    embedding_model: str
