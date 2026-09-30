from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    status: str = "ok"
    version: str = "5.1.0"


class RegistrationResultOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    template_id: str
    filename: str
    fill_status: str
    blocking_reasons: list[str]
    warnings: list[str]
    safe_write_start_row: int | None = None
    error: str | None = None


class TemplateEntryOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    template_id: str
    filename: str
    category: str
    category_status: str
    template_purpose: str
    fill_status: str
    listing_sheet: str | None
    header_row: int | None
    safe_write_start_row: int | None
    is_active: bool
    warnings: list[str]
    blocking_reasons: list[str]
    analysis_timestamp: str
    registration_timestamp: str


class ActivateTemplateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    template_id: str
    is_active: bool


class SourceUploadResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    source_id: str
    filename: str
    row_count: int
    columns: list[str]
    asin_column: str | None
    sku_column: str | None
    category_column: str | None
    preview: list[dict[str, Any]]


class AsinValidateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    asins: list[str]


class AsinValidationItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    input: str
    normalized: str
    valid: bool
    reason: str | None = None
    duplicate: bool = False
    parent_sku: str | None = None
    sku: str | None = None


class AsinValidateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    items: list[AsinValidationItem]
    valid_count: int
    invalid_count: int
    duplicate_count: int


class CreateRunResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    run_id: str


class ResolveRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    template_ids: list[str]
    source_ids: list[str]
    asins: list[str]
    template_profiles: dict[str, Any] | None = None  # inline profiles keyed by template_id


class ResolvedProductOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    asin: str
    sku: str | None
    product_name: str | None
    template_id: str | None
    template_filename: str | None
    source_id: str | None
    source_row: dict[str, Any]
    status: str  # matched | unmatched | ambiguous


class PreviewCellOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    value: str
    status: str  # source_value | missing | unmapped | fixed_value | manual


class PreviewRowOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    asin: str
    sku: str | None
    template_id: str
    cells: dict[str, PreviewCellOut]


class ContentProductHint(BaseModel):
    """Minimal product info sent alongside content edits so the preview can render the row."""
    asin: str
    sku: str | None = None
    product_name: str | None = None


class ManualEditsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    edits: dict[str, str]
    products: list[ContentProductHint] = Field(default_factory=list)


class ValidationFindingOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    asin: str
    sku: str | None
    column: str
    value: str
    severity: str  # blocking | error | warning | review | info
    error_type: str
    recommended_action: str


class FindingsGrouped(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    blocking: list[ValidationFindingOut]
    error: list[ValidationFindingOut]
    warning: list[ValidationFindingOut]
    review: list[ValidationFindingOut]
    info: list[ValidationFindingOut]


class ExportResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    run_id: str
    export_files: list[dict[str, Any]]


class DownloadFileOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    filename: str
    size_bytes: int
    template_id: str | None
    file_type: str  # xlsx | csv
