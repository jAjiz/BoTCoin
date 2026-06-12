"""Validation of the SearchSpace request grids (Pydantic, at the API boundary)
and the dict<->dataclass coercion that carries them to the worker."""

from dataclasses import asdict

import pytest
from pydantic import ValidationError

from api.schemas import CurrentParams as ApiCurrentParams
from api.schemas import GridSpec as ApiGridSpec
from api.schemas import OptimizerRequest as ApiOptimizerRequest
from api.schemas import RegimeSpace as ApiRegimeSpace
from api.schemas import SearchSpace as ApiSearchSpace
from trading.optimizer.search import (
    AutoSettings,
    CurrentParams,
    GridSpec,
    OptimizerRequest,
    RegimeParams,
    RegimeSpace,
    SearchSpace,
)


def _api_space() -> dict:
    return {
        "stop_pcts": {"start": 0.20, "end": 0.95, "step": 0.25},
        "k_act": {"start": 0.0, "end": 4.0, "step": 1.0},
        "min_margin": {"start": 0.0, "end": 0.01, "step": 0.002},
    }


# --- GridSpec validation ---------------------------------------------------


def test_gridspec_rejects_nonpositive_step() -> None:
    with pytest.raises(ValidationError):
        ApiGridSpec(start=0.0, end=1.0, step=0.0)


def test_gridspec_rejects_start_after_end() -> None:
    with pytest.raises(ValidationError):
        ApiGridSpec(start=1.0, end=0.0, step=0.1)


def test_gridspec_rejects_non_divisible_range() -> None:
    with pytest.raises(ValidationError):
        ApiGridSpec(start=0.0, end=1.0, step=0.3)


def test_gridspec_allows_fixed_value() -> None:
    """start == end fixes the dimension to a single value (not an error)."""
    g = ApiGridSpec(start=0.5, end=0.5, step=0.1)
    assert g.start == g.end == 0.5


# --- SearchSpace validation ------------------------------------------------


def test_searchspace_requires_at_least_one_branch() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        ApiSearchSpace(stop_pcts=ApiGridSpec(start=0.2, end=0.95, step=0.25), k_act=None, min_margin=None)


def test_searchspace_rejects_stop_out_of_bounds() -> None:
    with pytest.raises(ValidationError, match="within"):
        ApiSearchSpace(
            stop_pcts=ApiGridSpec(start=0.2, end=1.5, step=0.1),
            k_act=None,
            min_margin=ApiGridSpec(start=0.0, end=0.01, step=0.002),
        )


def test_searchspace_branches_are_required_fields() -> None:
    """k_act/min_margin have no defaults — they must be informed (even as null)."""
    with pytest.raises(ValidationError):
        ApiSearchSpace(stop_pcts=ApiGridSpec(start=0.2, end=0.95, step=0.25))


# --- OptimizerRequest mode/search_space interaction ------------------------


def test_request_model_allows_missing_search_space() -> None:
    """The model itself does NOT require search_space (the OPTIMIZE/AUTO rule is
    enforced at the route). This lets the same model echo historical requests back.
    See the route tests for the 422-on-submit behaviour."""
    for mode in ("OPTIMIZE", "AUTO", "CURRENT"):
        req = ApiOptimizerRequest(pair="XBTEUR", mode=mode)
        assert req.search_space is None


# --- dict -> dataclass coercion round-trip ---------------------------------


def test_dataclass_coerces_dict_search_space() -> None:
    """The search.py dataclass accepts the plain dict produced by model_dump/asdict
    (the API → worker boundary) and rebuilds typed GridSpec/SearchSpace."""
    req = OptimizerRequest(pair="XBTEUR", mode="OPTIMIZE", search_space=_api_space())
    assert isinstance(req.search_space, SearchSpace)
    assert isinstance(req.search_space.stop_pcts, GridSpec)
    assert req.search_space.k_act.step == 1.0


def test_dataclass_search_space_asdict_round_trips() -> None:
    """asdict (used by jobs.py for JSONB + worker pickling) fully dict-ifies the
    nested SearchSpace, and a null branch survives as None."""
    d = _api_space()
    d["k_act"] = None
    req = OptimizerRequest(pair="XBTEUR", mode="OPTIMIZE", search_space=d)

    rt = asdict(req)["search_space"]
    assert rt["stop_pcts"]["step"] == 0.25
    assert rt["k_act"] is None
    assert rt["min_margin"]["end"] == 0.01

    # round-trips back into an equivalent request (worker reconstruction path)
    req2 = OptimizerRequest(pair="XBTEUR", mode="OPTIMIZE", search_space=rt)
    assert req2.search_space.k_act is None
    assert req2.search_space.min_margin.step == 0.002


def _api_regime() -> dict:
    return {
        "er_window": {"start": 16, "end": 64, "step": 16},
        "chop_enter_pct": {"start": 0.25, "end": 0.50, "step": 0.25},
        "chop_dead_band": {"start": 0.05, "end": 0.10, "step": 0.05},
        "trend_pct": {"start": 0.60, "end": 0.70, "step": 0.10},
    }


# --- RegimeSpace validation ------------------------------------------------


def test_regimespace_rejects_er_window_below_2() -> None:
    with pytest.raises(ValidationError, match="er_window"):
        ApiRegimeSpace(
            er_window=ApiGridSpec(start=1, end=32, step=1),
            chop_enter_pct=ApiGridSpec(start=0.25, end=0.50, step=0.25),
            chop_dead_band=ApiGridSpec(start=0.05, end=0.10, step=0.05),
            trend_pct=ApiGridSpec(start=0.60, end=0.70, step=0.10),
        )


def test_regimespace_rejects_chop_out_of_bounds() -> None:
    with pytest.raises(ValidationError, match="within"):
        ApiRegimeSpace(
            er_window=ApiGridSpec(start=16, end=64, step=16),
            chop_enter_pct=ApiGridSpec(start=0.25, end=1.50, step=0.25),
            chop_dead_band=ApiGridSpec(start=0.05, end=0.10, step=0.05),
            trend_pct=ApiGridSpec(start=0.60, end=0.70, step=0.10),
        )


def test_regimespace_accepts_valid_grids() -> None:
    r = ApiRegimeSpace(**{k: ApiGridSpec(**v) for k, v in _api_regime().items()})
    assert r.er_window.start == 16
    assert r.chop_dead_band.end == 0.10


# --- SearchSpace with regime round-trip ------------------------------------


def test_dataclass_search_space_with_regime_round_trips() -> None:
    """RegimeSpace survives asdict → dict → dataclass re-hydration (worker path)."""
    d = {**_api_space(), "regime": _api_regime()}
    req = OptimizerRequest(pair="XBTEUR", mode="OPTIMIZE", search_space=d)

    assert isinstance(req.search_space.regime, RegimeSpace)
    assert req.search_space.regime.er_window.step == 16

    from dataclasses import asdict

    rt = asdict(req)["search_space"]
    assert rt["regime"]["chop_dead_band"]["end"] == 0.10

    req2 = OptimizerRequest(pair="XBTEUR", mode="OPTIMIZE", search_space=rt)
    assert req2.search_space.regime.trend_pct.start == 0.60


def test_dataclass_search_space_without_regime_is_none() -> None:
    req = OptimizerRequest(pair="XBTEUR", mode="OPTIMIZE", search_space=_api_space())
    assert req.search_space.regime is None


def test_dataclass_coerces_dict_auto_settings() -> None:
    """auto_settings, like search_space, accepts the plain dict round-trip."""
    req = OptimizerRequest(
        pair="XBTEUR",
        mode="AUTO",
        search_space=_api_space(),
        auto_settings={"n_seeds": 5, "min_agree": 4, "trial_step": 250, "max_trials": 3000},
    )
    assert isinstance(req.auto_settings, AutoSettings)
    assert req.auto_settings.n_seeds == 5
    assert asdict(req)["auto_settings"]["max_trials"] == 3000


# --- CurrentParams validation + round-trip ----------------------------------


def test_current_params_rejects_incomplete_stop_pcts() -> None:
    with pytest.raises(ValidationError, match="exactly the keys"):
        ApiCurrentParams(stop_pcts={"LL": 0.5, "LV": 0.5})


def test_current_params_rejects_stop_out_of_bounds() -> None:
    with pytest.raises(ValidationError, match="must be in"):
        ApiCurrentParams(stop_pcts={"LL": 0.5, "LV": 0.5, "MV": 0.5, "HV": 0.5, "HH": 1.5})


def test_dataclass_coerces_dict_current_params() -> None:
    """current_params, like search_space/auto_settings, accepts the plain dict
    round-trip and re-hydrates the nested RegimeParams (the API → worker boundary)."""
    api_req = ApiOptimizerRequest(
        pair="XBTEUR",
        mode="CURRENT",
        current_params={"min_margin": 0.004, "regime": {"er_window": 24, "chop_enter_pct": 0.30}},
    )
    req = OptimizerRequest(pair="XBTEUR", mode="CURRENT", current_params=api_req.current_params.model_dump())
    assert isinstance(req.current_params, CurrentParams)
    assert isinstance(req.current_params.regime, RegimeParams)
    assert req.current_params.min_margin == 0.004
    assert req.current_params.stop_pcts is None
    assert req.current_params.regime.er_window == 24
    assert req.current_params.regime.trend_pct == 0.66  # default fills in

    rt = asdict(req)["current_params"]
    assert rt["regime"]["chop_enter_pct"] == 0.30
    req2 = OptimizerRequest(pair="XBTEUR", mode="CURRENT", current_params=rt)
    assert req2.current_params.regime.er_window == 24


def test_dataclass_current_none_regime_stays_none() -> None:
    req = OptimizerRequest(pair="XBTEUR", mode="CURRENT", current_params={"k_act": 1.0, "regime": None})
    assert req.current_params.k_act == 1.0
    assert req.current_params.regime is None
