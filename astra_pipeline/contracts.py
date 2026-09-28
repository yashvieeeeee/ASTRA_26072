from enum import Enum
from typing import Literal
import numpy as np
import xarray as xr
from pydantic import BaseModel, Field, ConfigDict

class Mode(str, Enum):
    sample = "sample"
    historical = "historical"
    realtime = "realtime"

class SourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    mode: Mode
    is_synthetic: bool = False
    spatial_representation: Literal["grid", "point"]
    variables: list[str]
    units: dict[str, str]
    pending_source: bool = False

class FusedOutputMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grid_resolution_degrees: float = Field(0.25)
    latitude_bounds: tuple[float, float] = (6.0, 38.0)
    longitude_bounds: tuple[float, float] = (68.0, 98.0)
    temporal_bucket_minutes: int = 30
    input_window_minutes: int = 60
    features: list[str]

class DatasetContract(BaseModel):
    """Machine-readable schema for the xarray payload represented by metadata."""
    name: str
    representation: Literal["grid", "point"]
    required_variables: dict[str, str]  # variable -> unit
    is_synthetic: bool = False
    pending_source: bool = False

    def validate(self, dataset: xr.Dataset, metadata: SourceMetadata) -> None:
        if metadata.source != self.name or metadata.spatial_representation != self.representation:
            raise ValueError(f"{self.name}: metadata does not match fixed contract")
        if metadata.is_synthetic != self.is_synthetic or metadata.pending_source != self.pending_source:
            raise ValueError(f"{self.name}: synthetic/pending status changed")
        dims = {"time", "latitude", "longitude"} if self.representation == "grid" else {"time", "point"}
        if not dims.issubset(dataset.dims):
            raise ValueError(f"{self.name}: expected dimensions {dims}, got {set(dataset.dims)}")
        for variable, unit in self.required_variables.items():
            if variable not in dataset:
                raise ValueError(f"{self.name}: required variable {variable!r} absent")
            if dataset[variable].attrs.get("units") != unit:
                raise ValueError(f"{self.name}: {variable} must have units {unit!r}")
            if not np.issubdtype(dataset[variable].dtype, np.number):
                raise ValueError(f"{self.name}: {variable} must be numeric")

    def json_schema(self) -> dict:
        """A source-specific JSON Schema, with immutable source identity and fields."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": f"ASTRA {self.name} source contract",
            "type": "object",
            "properties": {
                "source": {"const": self.name},
                "spatial_representation": {"const": self.representation},
                "is_synthetic": {"const": self.is_synthetic},
                "pending_source": {"const": self.pending_source},
                "variables": {"type": "array", "const": list(self.required_variables)},
                "units": {"type": "object", "const": self.required_variables},
            },
            "required": ["source", "spatial_representation", "is_synthetic", "pending_source", "variables", "units"],
            "additionalProperties": False,
            "xarray_required_dimensions": ["time", "latitude", "longitude"] if self.representation == "grid" else ["time", "point"],
        }

def write_json_schemas(directory: str) -> None:
    import json
    from pathlib import Path
    path = Path(directory); path.mkdir(parents=True, exist_ok=True)
    (path / "source_metadata.schema.json").write_text(json.dumps(SourceMetadata.model_json_schema(), indent=2))
    (path / "fused_output.schema.json").write_text(json.dumps(FusedOutputMetadata.model_json_schema(), indent=2))
