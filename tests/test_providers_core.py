from __future__ import annotations

import pytest

from printlab_interface import secrets
from printlab_interface.providers import model_card
from printlab_interface.providers.key_pool import KeyEntry, KeyPool, classify_failure
from printlab_interface.providers.model_ref import ModelRefError, parse, validate_prefix


# ---- model refs -----------------------------------------------------------
def test_model_ref_splits_on_first_colon_only():
    ref = parse("ollama:llama3:8b-instruct")
    assert (ref.prefix, ref.model) == ("ollama", "llama3:8b-instruct") and str(ref) == "ollama:llama3:8b-instruct"


@pytest.mark.parametrize("bad", ["nocolon", ":model", "UPPER:m", "a b:m", "1x:m", "x:", "x: ", "x:" + "m" * 201, "x:a\nb", "", None, 5])
def test_model_ref_rejects_malformed(bad):
    with pytest.raises(ModelRefError):
        parse(bad)


def test_prefix_rules():
    assert validate_prefix("deep-seek_2") == "deep-seek_2"
    with pytest.raises(ModelRefError):
        validate_prefix("x" * 33)


# ---- model card -----------------------------------------------------------
def test_card_layers_override_wins_and_unknown_stays_none():
    card = model_card.resolve("gpt-4o-mini", litellm_provider="openai",
                              discovered={"max_output_tokens": 4000}, override={"max_output_tokens": 1000, "supports_vision": False})
    assert card.get("max_output_tokens") == 1000 and card.sources["max_output_tokens"] == "override"
    assert card.get("supports_vision") is False and card.sources["supports_vision"] == "override"
    assert card.get("max_input_tokens") == 128000 and card.sources["max_input_tokens"] == "catalog"
    nothing = model_card.resolve("totally-unknown-model-xyz")
    assert nothing.matched_catalog_key is None and nothing.get("max_output_tokens") is None
    assert nothing.get("supports_function_calling") is None  # unknown is not False


def test_card_drops_forbidden_unknown_and_invalid_fields_without_raising():
    card = model_card.resolve("x", override={"api_key": "sk-zzzzzzzzzzzz", "max_input_tokens": -5, "weird": 1, "supports_vision": "yes"})
    assert card.get("max_input_tokens") is None and card.get("supports_vision") is None
    text = " ".join(card.warnings)
    assert "api_key" in text and "weird" in text and "max_input_tokens" in text and "supports_vision" in text
    assert "sk-zzzz" not in str(card.as_dict())


def test_none_in_a_higher_layer_does_not_erase_a_lower_one():
    card = model_card.resolve("gpt-4o-mini", litellm_provider="openai", override={"max_input_tokens": None})
    assert card.get("max_input_tokens") == 128000


def test_output_ceiling_can_be_lowered_but_never_raised():
    card = model_card.resolve("gpt-4o-mini", litellm_provider="openai")
    limit = card.get("max_output_tokens")
    assert model_card.clamp_max_tokens(card, 100) == 100
    assert model_card.clamp_max_tokens(card, limit * 10) == limit
    assert model_card.clamp_max_tokens(card, None) == limit
    with pytest.raises(ValueError):
        model_card.clamp_max_tokens(card, 0)
    unknown = model_card.resolve("nope-model")
    assert model_card.clamp_max_tokens(unknown, 5000) == 5000 and model_card.clamp_max_tokens(unknown, None) is None


def test_importing_the_wrapper_does_not_open_network_connections():
    import socket, subprocess, sys, textwrap
    code = textwrap.dedent("""
        import socket
        calls = []
        real = socket.socket.connect
        def spy(self, addr, *a, **k):
            calls.append(addr); return real(self, addr, *a, **k)
        socket.socket.connect = spy
        import printlab_interface.providers._litellm
        print(len(calls))
    """)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert out.stdout.strip().splitlines()[-1] == "0", out.stdout + out.stderr


# ---- failure classification ----------------------------------------------
@pytest.mark.parametrize(
    "status,msg,retry,kind,cool",
    [(401, "", None, "invalid", 0), (402, "", None, "quota", 1800), (403, "", None, "forbidden", 600),
     (429, "You exceeded your current quota", None, "quota", 1800), (429, "slow down", None, "rate_limited", 60),
     (429, "slow down", 12, "rate_limited", 12), (429, "slow down", 99999, "rate_limited", 1800),
     (500, "", None, "neutral", 0), (None, "", None, "neutral", 0), (400, "bad", None, "neutral", 0)],
)
def test_failure_classification(status, msg, retry, kind, cool):
    fault = classify_failure(status, msg, retry)
    assert fault.kind == kind and fault.cooldown_s == cool


# ---- key pool -------------------------------------------------------------
class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def keys(*specs):
    return [KeyEntry(i, p) for i, p in specs]


def test_picks_lowest_priority_number_and_is_sticky_per_session():
    pool = KeyPool(clock=Clock())
    ks = keys(("a", 50), ("b", 10), ("c", 10))
    assert pool.select("p", ks, session="s1").id == "b"
    ks2 = keys(("a", 1), ("b", 10))  # a now outranks b, but s1 is pinned to b
    assert pool.select("p", ks2, session="s1").id == "b"
    assert pool.select("p", ks2, session="s2").id == "a"


def test_disabled_and_invalid_keys_are_never_selected():
    pool = KeyPool(clock=Clock())
    ks = [KeyEntry("a", 1, disabled=True), KeyEntry("b", 2, invalid=True), KeyEntry("c", 3)]
    assert pool.select("p", ks).id == "c"
    assert pool.select("p", [ks[0], ks[1]]) is None and pool.select("p", []) is None


def test_failed_key_cools_down_then_recovers():
    clock = Clock(); pool = KeyPool(clock=clock)
    ks = keys(("a", 1), ("b", 2))
    pool.report_failure("p", ks[0], 429, "slow", 30)
    assert pool.select("p", ks).id == "b"
    clock.t += 31
    assert pool.select("p", ks).id == "a"
    assert pool.cooldown_remaining("p", "a") == 0


def test_when_everything_cools_down_the_earliest_recovery_is_returned():
    clock = Clock(); pool = KeyPool(clock=clock)
    ks = keys(("a", 1), ("b", 2))
    pool.report_failure("p", ks[0], 429, "x", 500)
    pool.report_failure("p", ks[1], 429, "x", 100)
    assert pool.select("p", ks).id == "b"


def test_401_marks_the_key_invalid_and_success_clears_cooldown():
    pool = KeyPool(clock=Clock())
    ks = keys(("a", 1), ("b", 2))
    pool.report_failure("p", ks[0], 401)
    assert ks[0].invalid is True and pool.select("p", ks).id == "b"
    pool.report_failure("p", ks[1], 403)
    pool.report_success("p", "b")
    assert pool.cooldown_remaining("p", "b") == 0


def test_key_switch_only_when_key_at_fault_and_nothing_streamed():
    pool = KeyPool(clock=Clock())
    assert pool.should_try_next_key(classify_failure(429), output_started=False) is True
    assert pool.should_try_next_key(classify_failure(429), output_started=True) is False
    assert pool.should_try_next_key(classify_failure(500), output_started=False) is False


def test_exclude_prevents_retrying_the_same_key():
    pool = KeyPool(clock=Clock())
    ks = keys(("a", 1), ("b", 2))
    assert pool.select("p", ks, exclude={"a"}).id == "b" and pool.select("p", ks, exclude={"a", "b"}) is None


# ---- secrets --------------------------------------------------------------
def test_mask_never_reveals_short_secrets_and_only_edges_of_long_ones():
    assert secrets.mask("short") == "***" and secrets.mask("") == "***"
    masked = secrets.mask("sk-abcdefghijklmnopqrstuv")
    assert masked.startswith("sk-") and "abcdefghijklmn" not in masked


def test_seal_roundtrip_and_ciphertext_is_not_the_plaintext():
    sealed = secrets.seal("sk-roundtrip-secret-0123456789")
    assert "roundtrip" not in sealed and secrets.reveal(sealed) == "sk-roundtrip-secret-0123456789"
    assert secrets.seal("same") != secrets.seal("same") or sealed.startswith("dpapi1:")  # nonce or DPAPI entropy


def test_unknown_or_plain_stored_values_are_refused():
    for bad in ("plain-text-key", "", "dpapi1x:AAAA"):
        with pytest.raises(secrets.SecretError):
            secrets.reveal(bad)


def test_keyed_fallback_roundtrip_and_tamper_detection(monkeypatch):
    monkeypatch.setattr(secrets.sys, "platform", "linux")
    monkeypatch.setenv("PLI_SECRET_KEY", "a-long-enough-test-key-0123")
    sealed = secrets.seal("sk-fallback-secret-9999999")
    assert sealed.startswith("keyed1:") and secrets.reveal(sealed) == "sk-fallback-secret-9999999"
    import base64
    raw = bytearray(base64.b64decode(sealed[len("keyed1:"):])); raw[20] ^= 1
    with pytest.raises(secrets.SecretError, match="integrity"):
        secrets.reveal("keyed1:" + base64.b64encode(bytes(raw)).decode())
    monkeypatch.setenv("PLI_SECRET_KEY", "a-different-long-test-key-1")
    with pytest.raises(secrets.SecretError):
        secrets.reveal(sealed)


def test_keyed_fallback_refuses_without_a_key(monkeypatch):
    monkeypatch.setattr(secrets.sys, "platform", "linux")
    monkeypatch.delenv("PLI_SECRET_KEY", raising=False)
    with pytest.raises(secrets.SecretError, match="PLI_SECRET_KEY"):
        secrets.seal("sk-anything-123456789")


@pytest.mark.parametrize("bad", ["abc\n", "abc\r\n", "abc\x00", "ab\nc"])
def test_prefix_validation_rejects_trailing_newline_and_control_characters(bad):
    # `$` in a regex matches before a trailing newline; fullmatch must be used.
    with pytest.raises(ModelRefError):
        validate_prefix(bad)
    with pytest.raises(ModelRefError):
        parse(f"{bad}:model")
