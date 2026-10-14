"""Schema 2 of the result repository (Analysis data contract): model status, N/A kind, element family,
system size and run provenance survive storage; the element family is canonical."""

from __future__ import annotations

import sqlite3

import pytest

from hea_calc.core import composition as C
from hea_calc.core.chunks import NA_CODES, STATUS_CODES, pack_results
from hea_calc.core.engine import (MODEL_KEYS, NA, NA_ERROR, NA_MISSING_DATA, NA_UNDEFINED, STATUS_DATA_SUSPECT,
                                  STATUS_EXTRAPOLATED, STATUS_IN_DOMAIN, default_engine)
from hea_calc.core.family import FAMILY_EPS, family_key, family_members
from hea_calc.core.provenance import dataset_ids, engine_version, run_provenance
from hea_calc.core.repository import SCHEMA_VERSION, RepositoryError, ResultRepository, check_schema
from hea_calc.core.results import ResultRow

S1 = {"Co": 1, "Cr": 1, "Fe": 1, "Mn": 1, "Ni": 1}
S2 = {"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1, "Si": 0.5}
S3 = {"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1, "W": 0.5}
S4 = {"Co": 1, "Cr": 1, "Cu": 1, "Fe": 1, "Ni": 1}
S5 = {"Co": 1, "Ni": 1}


@pytest.fixture(scope="module")
def engine():
    return default_engine()


# ---------------------------------------------------------------------- engine classification
def test_na_verdicts_carry_reason_and_never_a_caution(engine):
    """The single stored note per model is unambiguous only if this holds (core/chunks docstring)."""
    comps = [S1, S2, S3, S4, S5, {"Fe": 1, "H": 1}, {"Al": 1, "Ne": 1}, {"Fe": 1, "Nd": 1, "Co": 1}]
    for comp in comps:
        res = engine.calculate(comp)
        for k, o in res.models.items():
            if o.label == NA:
                assert o.reason and not o.caution, (comp, k)
                assert o.na_kind in (NA_MISSING_DATA, NA_UNDEFINED), (comp, k)
            else:
                assert not o.reason, (comp, k)
                assert o.na_kind is None


def test_canonical_sample_states(engine):
    s1 = engine.calculate(S1)
    assert all(o.label != NA and o.status == STATUS_IN_DOMAIN for o in s1.models.values())
    s2 = engine.calculate(S2)
    assert [k for k, o in s2.models.items() if o.label == NA] == ["M6", "M7"]
    assert {s2.models[k].na_kind for k in ("M6", "M7")} == {NA_MISSING_DATA}
    s3 = engine.calculate(S3)
    assert s3.models["M6"].status == s3.models["M7"].status == STATUS_DATA_SUSPECT
    s4 = engine.calculate(S4)
    assert s4.models["M7"].status == STATUS_EXTRAPOLATED and s4.models["M7"].label == "SS"
    s5 = engine.calculate(S5)
    assert s5.models["M1"].label == NA and s5.models["M1"].na_kind == NA_UNDEFINED


# ---------------------------------------------------------------------- element family
def test_family_is_alphabetical_and_order_independent():
    a = family_key(C.fractions({"Cr": 1, "Mn": 1, "Fe": 1, "Ni": 1}))
    b = family_key(C.fractions({"Ni": 1, "Fe": 1, "Mn": 1, "Cr": 1}))
    assert a == b == "Cr-Fe-Mn-Ni"


def test_family_drops_zero_and_residue_but_keeps_trace_additions():
    assert family_members({"Co": 0.5, "Ni": 0.5, "Al": 0.0}) == ("Co", "Ni")
    assert family_members({"Co": 0.5, "Ni": 0.5 - 1e-13, "Al": 1e-13}) == ("Co", "Ni")
    assert family_members({"Co": 0.49999, "Ni": 0.5, "Al": 1e-5}) == ("Al", "Co", "Ni")   # 0.001 at.%
    assert FAMILY_EPS == 1e-9
    assert family_key({}) is None


def test_family_independent_of_input_unit(engine):
    """at.%, atomic ratio and wt.% inputs of one alloy give the same normalised fractions -> family."""
    at = engine.calculate({"Al": 10, "Co": 22.5, "Cr": 22.5, "Fe": 22.5, "Ni": 22.5}).composition
    ratio = engine.calculate({"Al": 0.4444444444, "Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}).composition
    assert family_key(at) == family_key(ratio) == "Al-Co-Cr-Fe-Ni"
    wt = C.from_fractions(at, "wt")                       # the same alloy entered in wt.%
    via_wt = engine.calculate(C.to_fractions(wt, "wt")).composition
    assert family_key(via_wt) == "Al-Co-Cr-Fe-Ni"


# ---------------------------------------------------------------------- chunk + repository
def test_chunk_carries_status_na_and_family(engine):
    comps = [S1, S2, S3, {"Fe": 1}]
    ch = pack_results(comps, [engine.calculate(c) for c in comps])
    assert ch["families"] == ["Co-Cr-Fe-Mn-Ni", "Co-Cr-Fe-Ni-Si", "Co-Cr-Fe-Ni-W"]
    assert list(ch["fam_idx"]) == [0, 1, 2, -1]
    assert list(ch["n_els"]) == [5, 5, 5, -1]
    assert ch["status"]["M6"][2] == STATUS_CODES[STATUS_DATA_SUSPECT]
    assert ch["na_kind"]["M6"][1] == NA_CODES[NA_MISSING_DATA]
    assert ch["status"]["M6"][1] == -1
    assert all(ch["na_kind"][k][3] == NA_CODES[NA_ERROR] for k in MODEL_KEYS)


@pytest.fixture()
def repo(engine, tmp_path):
    r = ResultRepository(engine, root=tmp_path)
    yield r
    r.close()


def _store(repo, engine, comps, settings=None):
    rows = [ResultRow(C.alloy_name(c), c, engine.calculate(c), "single") for c in comps]
    run = repo.create_run("single", settings=settings or {}, elements=[], expected=len(rows))
    rng = repo.append_results(run, rows)
    repo.finalize_run(run, "complete")
    return run, rng


def test_status_na_kind_family_round_trip(repo, engine):
    run, rng = _store(repo, engine, [S1, S2, S3, S4, S5, {"Fe": 1}])
    recs = [repo.get_result(i) for i in rng]
    s1, s2, s3, s4, s5, err = recs
    assert all(s1.model_status(k) == STATUS_IN_DOMAIN for k in MODEL_KEYS)
    assert s1.family == "Co-Cr-Fe-Mn-Ni" and s1.n_elements == 5
    assert s2.model_status("M6") is None and s2.model_na_kind("M6") == NA_MISSING_DATA
    assert "Troparevsky" in s2.model_reason("M6") and s2.model_caution("M6") == ""
    assert s3.model_status("M6") == s3.model_status("M7") == STATUS_DATA_SUSPECT
    assert s3.model_label("M6") == "IM" and s3.model_caution("M6") and not s3.model_reason("M6")
    assert s4.model_status("M7") == STATUS_EXTRAPOLATED and s4.model_label("M7") == "SS"
    assert s5.model_na_kind("M1") == NA_UNDEFINED
    assert err.family is None and err.n_elements is None
    assert all(err.model_na_kind(k) == NA_ERROR and err.model_status(k) is None for k in MODEL_KEYS)
    # one families row per distinct family, with its size
    fam = dict(repo.con.execute("SELECT key, size FROM families").fetchall())
    assert fam["Co-Cr-Fe-Mn-Ni"] == 5 and len(fam) == 5


def test_status_queryable_in_sql(repo, engine):
    run, _rng = _store(repo, engine, [S1, S3, S3, S4])
    n = repo.con.execute("SELECT COUNT(*) FROM results WHERE run_id=? AND status_M6=?",
                         (run, STATUS_CODES[STATUS_DATA_SUSPECT])).fetchone()[0]
    assert n == 2
    sizes = repo.con.execute("SELECT n_elements, COUNT(*) FROM results WHERE run_id=? GROUP BY 1", (run,)).fetchall()
    assert sizes == [(5, 4)]


def test_run_provenance_is_stored(repo, engine):
    run, _ = _store(repo, engine, [S1])
    info = repo.get_run(run)
    prov = run_provenance()
    assert info.engine_version == engine_version() == prov["engine_version"]
    assert info.app_version == prov["app_version"]
    assert set(info.dataset_ids) == set(dataset_ids())
    assert all(v and v != "missing" for v in info.dataset_ids.values())


def test_engine_version_is_stable_and_short():
    assert engine_version() == engine_version()
    assert len(engine_version()) == 12


def test_schema_version_is_checked(repo):
    assert check_schema(repo.con) == SCHEMA_VERSION == 2
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO meta VALUES('schema_version', '1')")
    with pytest.raises(RepositoryError):
        check_schema(con)
