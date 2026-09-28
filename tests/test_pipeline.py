import numpy as np
import pytest
from astra_pipeline import PreprocessingPipeline
from astra_pipeline.adapters import EUMETSATIODCAdapter, GPMAdapter, INSATAdapter, default_adapters
from astra_pipeline.domain import LATITUDES, LONGITUDES

def test_sample_pipeline_runs_without_credentials_and_marks_caveats():
    fused = PreprocessingPipeline().run("sample")
    assert fused.atmospheric_state.sizes["feature"] >= 17
    assert fused.attrs["source_status"]["synthetic_lightning"]["synthetic"] is True
    assert fused.attrs["source_status"]["ground_stations_pending"]["pending"] is True
    assert all(status["mode"] == "sample" and status["is_synthetic"] is True for status in fused.attrs["source_status"].values())

def test_lightning_sample_does_not_claim_uncomputed_cape_precipitation_formula():
    dataset = next(adapter for adapter in default_adapters() if adapter.contract.name == "synthetic_lightning").load("sample")
    assert dataset.attrs["formula"] == "deterministic spatial-temporal sample fixture; not CAPE × precipitation_rate"

def test_coverage_is_reported_and_low_source_coverage_is_marked_degraded():
    fused = PreprocessingPipeline(min_valid_fraction=.5).run("sample")
    assert len(fused.attrs["fused_valid_fraction"]) == fused.sizes["time"]
    lightning = fused.attrs["source_status"]["synthetic_lightning"]
    assert lightning["coverage_state"] == "degraded"
    assert all(value < .5 for value in lightning["valid_fraction_by_frame"])

def test_output_is_full_pan_india_not_a_regional_subset():
    fused = PreprocessingPipeline().run("sample")
    assert np.array_equal(fused.latitude.values, LATITUDES)
    assert np.array_equal(fused.longitude.values, LONGITUDES)
    assert (float(fused.latitude.min()), float(fused.latitude.max())) == (6.0, 38.0)
    assert (float(fused.longitude.min()), float(fused.longitude.max())) == (68.0, 98.0)

def test_coverage_assertion_fails_loudly_for_narrow_source():
    class NarrowGPM(GPMAdapter):
        def sample(self): return super().sample().sel(latitude=slice(20, 30), longitude=slice(75, 85))
    with pytest.raises(ValueError, match="Pan-India coverage violation"):
        PreprocessingPipeline([NarrowGPM()]).run("sample")

def test_last_hour_sequence_shape():
    pipeline=PreprocessingPipeline(); inputs=pipeline.build_sequences(pipeline.run())
    assert inputs.inputs.sizes["input_step"] == 4
    assert inputs.inputs.sizes["sequence"] == 2

def test_eumetsat_is_default_satellite_and_keeps_mosdac_contract(monkeypatch):
    monkeypatch.delenv("ASTRA_SATELLITE_PROVIDER", raising=False)
    monkeypatch.delenv("ASTRA_SATELLITE_CONFIG", raising=False)
    monkeypatch.delenv("ASTRA_MOSDAC_CONFIG", raising=False)
    selected = default_adapters()[1]
    assert isinstance(selected, EUMETSATIODCAdapter)
    assert selected.contract == INSATAdapter.contract
    assert set(selected.load().data_vars) == set(INSATAdapter().load().data_vars)

def test_satellite_provider_can_switch_to_mosdac_with_config_flag(tmp_path, monkeypatch):
    config = tmp_path / "satellite.json"
    config.write_text('{"satellite_provider": "mosdac"}')
    monkeypatch.setenv("ASTRA_SATELLITE_CONFIG", str(config))
    monkeypatch.delenv("ASTRA_SATELLITE_PROVIDER", raising=False)
    assert isinstance(default_adapters()[1], INSATAdapter)
