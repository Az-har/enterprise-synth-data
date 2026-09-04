"""
Pydantic data models for SAP and Custom Table Schemas.
"""
from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class PossibleValue(BaseModel):
    """Represents an allowed domain code and its business description."""
    val: str = Field(..., description="The code value, e.g. 'KR', 'SA'")
    desc: str = Field(..., description="Business meaning, e.g. 'Vendor Invoice'")


class ForeignKey(BaseModel):
    """Represents a foreign key relationship to another table."""
    field: str = Field(..., description="The local field name, e.g. 'BUKRS'")
    ref_table: str = Field(..., description="Referenced parent table, e.g. 'T001'")
    ref_field: str = Field(..., description="Referenced field in parent table, e.g. 'BUKRS'")


class FieldMeta(BaseModel):
    """Metadata for an individual table column/field."""
    name: str = Field(..., description="Field technical name, e.g. 'BELNR'")
    data_element: Optional[str] = Field(None, description="Data element, e.g. 'BELNR_D'")
    description: Optional[str] = Field("", description="Field label/business description")
    data_type: str = Field("CHAR", description="Datatype, e.g. 'CHAR', 'NUMC', 'DATS', 'CURR', 'DEC'")
    length: int = Field(10, description="Field character length")
    decimals: int = Field(0, description="Decimals if numeric")
    is_key: bool = Field(False, description="Whether this is a primary key")
    check_table: Optional[str] = Field(None, description="Checktable name if FK reference exists")
    possible_values: List[PossibleValue] = Field(default_factory=list, description="Allowed domain enums")


class TableSchema(BaseModel):
    """Metadata and definition of an entire table."""
    name: str = Field(..., description="Table technical name, e.g. 'BKPF'")
    description: str = Field(..., description="Table business description")
    category: str = Field("General", description="Module/Category: Finance, Sales, Materials, Master")
    keys: List[str] = Field(default_factory=list, description="List of primary key field names")
    fields: Dict[str, FieldMeta] = Field(default_factory=dict, description="Dictionary of field_name -> FieldMeta")
    foreign_keys: List[ForeignKey] = Field(default_factory=list, description="List of FK relationships")

    def get_field(self, field_name: str) -> Optional[FieldMeta]:
        """Case-insensitive field lookup."""
        normalized = field_name.strip().upper()
        for k, v in self.fields.items():
            if k.upper() == normalized:
                return v
        return None

    def get_key_fields(self) -> List[FieldMeta]:
        """Return list of FieldMeta objects for primary keys."""
        return [self.fields[k] for k in self.keys if k in self.fields]
