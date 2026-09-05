"""The curated model shortlist must survive NVIDIA's model churn.

NVIDIA retires hosted models on a few days' notice, so the shortlist is a
preference expressed against whatever the live catalog happens to hold, never
a promise that a name still exists.
"""
from app.provider_meta import NVIDIA_POPULAR, annotate_chat_models

_LIVE = [row[0] for row in NVIDIA_POPULAR]


def test_shortlist_leads_and_keeps_table_order():
    catalog = sorted(_LIVE) + ["zz/other-model", "aa/another-model"]
    ordered, meta = annotate_chat_models("nvidia", catalog)

    assert ordered[: len(_LIVE)] == _LIVE, "curated order, not alphabetical"
    assert all(meta[m]["popular"] for m in _LIVE)
    assert all(meta[m]["tag"] in ("fast", "medium", "slow") for m in _LIVE)
    # Nothing is dropped, and the rest keeps the provider's own order.
    assert sorted(ordered) == sorted(catalog)
    assert ordered[len(_LIVE):] == ["zz/other-model", "aa/another-model"]


def test_retired_model_disappears_instead_of_being_offered():
    """A model absent from the live catalog must not reach the dropdown: it is
    end-of-life and every call to it would return 410."""
    live_minus_first = [row[0] for row in NVIDIA_POPULAR][1:]
    ordered, meta = annotate_chat_models("nvidia", live_minus_first + ["x/y"])

    assert NVIDIA_POPULAR[0][0] not in ordered
    assert NVIDIA_POPULAR[0][0] not in meta


def test_untabled_provider_is_untouched():
    """Groq, OpenAI, Anthropic and Ollama keep their flat list verbatim."""
    catalog = ["b-model", "a-model"]
    for provider in ("groq", "openai", "anthropic", "ollama_cloud", "google_genai"):
        ordered, meta = annotate_chat_models(provider, catalog)
        assert ordered == catalog and meta == {}


def test_shortlist_entries_are_well_formed():
    seen = set()
    for model_id, tag, note in NVIDIA_POPULAR:
        assert model_id not in seen, f"duplicate shortlist entry: {model_id}"
        seen.add(model_id)
        assert "/" in model_id
        assert tag in ("fast", "medium", "slow")
        assert note and len(note) < 70, "notes render on one dropdown help line"
