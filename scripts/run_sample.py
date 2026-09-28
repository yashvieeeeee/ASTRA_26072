from pathlib import Path
from astra_pipeline import PreprocessingPipeline, default_adapters
from astra_pipeline.contracts import write_json_schemas

root=Path(__file__).resolve().parents[1]
write_json_schemas(root / "schemas")
for adapter in default_adapters():
    (root / "schemas" / f"{adapter.contract.name}.contract.schema.json").write_text(
        __import__("json").dumps(adapter.contract.json_schema(), indent=2)
    )
pipeline=PreprocessingPipeline()
fused=pipeline.run("sample")
inputs=pipeline.build_sequences(fused)
print(f"Fused: {dict(fused.atmospheric_state.sizes)}")
print(f"Sequences: {dict(inputs.inputs.sizes)}")
