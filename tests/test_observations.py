import json

from paper_reader import observations


def test_observations_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(observations, "CACHE_DIR", tmp_path / "cache")
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    obs = [{"summary": "s", "question": "q", "sources": ["p1"],
            "facts": [], "entities": [], "round_num": 0}]
    observations.save_observations(str(pdf), obs)
    assert observations.load_observations(str(pdf)) == obs


def test_load_observations_missing_or_corrupt(tmp_path, monkeypatch):
    monkeypatch.setattr(observations, "CACHE_DIR", tmp_path / "cache")
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    assert observations.load_observations(str(pdf)) == []

    (tmp_path / "cache").mkdir()
    key = observations._paper_key(str(pdf))
    observations.observations_path(key).write_text("{bad json", encoding="utf-8")
    assert observations.load_observations(str(pdf)) == []

    observations.clear_observations(key)
    assert not observations.observations_path(key).exists()
    # 幂等
    observations.clear_observations(key)


def test_image_descriptions_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(observations, "CACHE_DIR", tmp_path / "cache")
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    observations.save_image_descriptions(str(pdf), {"images/a.png": "描述"})
    assert observations.load_image_descriptions(str(pdf)) == {"images/a.png": "描述"}


def test_caches_noop_when_filepath_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(observations, "CACHE_DIR", tmp_path / "cache")
    missing = str(tmp_path / "nope.pdf")
    assert observations.load_observations(missing) == []
    assert observations.load_image_descriptions(missing) == {}
    observations.save_observations(missing, [{"summary": "s"}])
    observations.save_image_descriptions(missing, {"a": "b"})
    cache = tmp_path / "cache"
    assert not cache.exists() or list(cache.iterdir()) == []


def test_load_observations_filters_non_dict_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(observations, "CACHE_DIR", tmp_path / "cache")
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    observations.save_observations(str(pdf), [{"summary": "ok"}])
    key = observations._paper_key(str(pdf))
    observations.observations_path(key).write_text(
        json.dumps({"paper_id": key,
                    "observations": [{"summary": "ok"}, "junk", 42]}),
        encoding="utf-8")
    assert observations.load_observations(str(pdf)) == [{"summary": "ok"}]
