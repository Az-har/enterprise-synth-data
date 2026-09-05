"""
Generation Rules and Field Constraints.
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class FieldRule(BaseModel):
    """Rule defining how a specific column should be synthesized."""
    field_name: str
    rule_type: str = Field(..., description="'choice', 'range', 'distribution', 'fk_cascade', 'faker', 'sequence', 'fixed'")
    parameters: Dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **data):
        if "params" in data and "parameters" not in data:
            data["parameters"] = data.pop("params")
        super().__init__(**data)
    
    # Examples:
    # rule_type='choice', parameters={'choices': ['1000', '2000'], 'weights': [0.7, 0.3]}
    # rule_type='range', parameters={'min': 100.0, 'max': 5000.0, 'decimals': 2}
    # rule_type='distribution', parameters={'dist': 'lognormal', 'mean': 5.0, 'sigma': 1.0}
    # rule_type='fk_cascade', parameters={'parent_table': 'BKPF', 'parent_field': 'BELNR'}
    # rule_type='sequence', parameters={'prefix': 'INV-', 'start': 1000, 'pad': 10}
    # rule_type='fixed', parameters={'value': '100'}


class TableGenerationSpec(BaseModel):
    """Specification for generating a synthetic table."""
    table_name: str
    row_count: int = 100
    rules: Dict[str, FieldRule] = Field(default_factory=dict)
    parent_table: Optional[str] = None
    items_per_parent_range: Optional[List[int]] = Field(default=None, description="[min_items, max_items] per parent")
