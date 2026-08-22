from __future__ import annotations

import math

import pytest

from tarkka.domain.resource_acquisition import (
    AcquisitionBudgetState,
    ResourceAcquisitionPolicy,
)


def _policy(**kwargs) -> ResourceAcquisitionPolicy:
    return ResourceAcquisitionPolicy(
        allowed_domains=frozenset({"example.org"}),
        **kwargs,
    )


def test_default_policy_denies_network_targets_until_domain_scope_is_explicit() -> None:
    policy = ResourceAcquisitionPolicy()

    assert not policy.allows_uri("https://example.org/paper")
    assert not policy.allows_uri("http://example.org/paper")
    assert not policy.allows_uri("ftp://example.org/paper")
    assert not policy.allows_uri("/relative/path")


def test_domain_allowlist_includes_subdomains_but_not_suffix_or_userinfo_tricks() -> None:
    policy = _policy()

    assert policy.allows_uri("https://example.org/a")
    assert policy.allows_uri("https://data.example.org/a")
    assert not policy.allows_uri("https://notexample.org/a")
    assert not policy.allows_uri("https://example.org.attacker.test/a")
    assert not policy.allows_uri("https://example.org@attacker.test/a")
    assert not policy.allows_uri("https://user:secret@example.org/a")
    assert not policy.allows_uri("https://127.0.0.1/a")


def test_policy_normalizes_schemes_domains_and_idna() -> None:
    policy = ResourceAcquisitionPolicy(
        allowed_schemes=frozenset({"HTTPS:"}),
        allowed_domains=frozenset({"BÜCHER.Example."}),
    )

    assert policy.allowed_schemes == frozenset({"https"})
    assert policy.allowed_domains == frozenset({"xn--bcher-kva.example"})
    assert policy.allows_uri("https://shop.bücher.example/a")


def test_resolved_address_policy_blocks_ssrf_targets_by_default() -> None:
    policy = _policy()

    assert policy.allows_resolved_address("93.184.216.34")
    assert not policy.allows_resolved_address("127.0.0.1")
    assert not policy.allows_resolved_address("10.0.0.1")
    assert not policy.allows_resolved_address("169.254.169.254")
    assert not policy.allows_resolved_address("::1")
    assert not policy.allows_resolved_address("not-an-address")


def test_private_address_access_requires_explicit_policy() -> None:
    policy = _policy(allow_private_addresses=True)

    assert policy.allows_resolved_address("10.0.0.1")
    assert policy.allows_resolved_address("127.0.0.1")
    assert not policy.allows_resolved_address("0.0.0.0")
    assert not policy.allows_resolved_address("224.0.0.1")


def test_request_depth_byte_and_elapsed_budgets_are_hard() -> None:
    policy = _policy(max_depth=2, max_requests=2, max_bytes=100, max_elapsed_seconds=10)

    assert AcquisitionBudgetState().allows_request(
        policy,
        depth=2,
        expected_bytes=100,
    )
    assert not AcquisitionBudgetState().allows_request(policy, depth=3)
    assert not AcquisitionBudgetState(requests_used=2).allows_request(policy, depth=0)
    assert not AcquisitionBudgetState(bytes_used=90).allows_request(
        policy,
        depth=0,
        expected_bytes=11,
    )
    assert not AcquisitionBudgetState(elapsed_seconds=10).allows_request(
        policy,
        depth=0,
    )


def test_request_rate_interval_is_explicit_and_fail_closed_when_timing_is_unknown() -> None:
    policy = _policy(min_request_interval_seconds=1.0)
    state = AcquisitionBudgetState(requests_used=1)

    assert not state.allows_request(policy, depth=0)
    assert not state.allows_request(
        policy,
        depth=0,
        seconds_since_last_request=0.5,
    )
    assert state.allows_request(
        policy,
        depth=0,
        seconds_since_last_request=1.0,
    )


def test_retry_budget_is_per_resource() -> None:
    policy = _policy(max_retries=2)

    assert policy.allows_retry(0)
    assert policy.allows_retry(1)
    assert not policy.allows_retry(2)


def test_zero_request_budget_disallows_network_attempts() -> None:
    policy = _policy(max_requests=0)

    assert not AcquisitionBudgetState().allows_request(policy, depth=0)


def test_policy_rejects_invalid_bounds_and_allowlists() -> None:
    with pytest.raises(ValueError, match="max_depth"):
        _policy(max_depth=-1)
    with pytest.raises(ValueError, match="max_requests"):
        _policy(max_requests=-1)
    with pytest.raises(ValueError, match="max_bytes"):
        _policy(max_bytes=-1)
    with pytest.raises(ValueError, match="max_retries"):
        _policy(max_retries=-1)
    with pytest.raises(ValueError, match="max_elapsed_seconds"):
        _policy(max_elapsed_seconds=0)
    with pytest.raises(ValueError, match="max_elapsed_seconds"):
        _policy(max_elapsed_seconds=math.inf)
    with pytest.raises(ValueError, match="min_request_interval_seconds"):
        _policy(min_request_interval_seconds=-1)
    with pytest.raises(ValueError, match="allow_private_addresses"):
        _policy(allow_private_addresses=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least one URI scheme"):
        ResourceAcquisitionPolicy(allowed_schemes=frozenset())
    with pytest.raises(ValueError, match="valid URI schemes"):
        ResourceAcquisitionPolicy(allowed_schemes=frozenset({"123"}))
    with pytest.raises(ValueError, match="bare DNS"):
        ResourceAcquisitionPolicy(allowed_domains=frozenset({"https://example.org"}))
    with pytest.raises(ValueError, match="not IP addresses"):
        ResourceAcquisitionPolicy(allowed_domains=frozenset({"127.0.0.1"}))
    with pytest.raises(ValueError, match="valid DNS"):
        ResourceAcquisitionPolicy(allowed_domains=frozenset({"-bad.example"}))


def test_budget_state_rejects_invalid_counters_and_request_inputs() -> None:
    policy = _policy()
    with pytest.raises(ValueError, match="requests_used"):
        AcquisitionBudgetState(requests_used=-1)
    with pytest.raises(ValueError, match="bytes_used"):
        AcquisitionBudgetState(bytes_used=-1)
    with pytest.raises(ValueError, match="elapsed_seconds"):
        AcquisitionBudgetState(elapsed_seconds=math.inf)
    with pytest.raises(ValueError, match="request depth"):
        AcquisitionBudgetState().allows_request(policy, depth=-1)
    with pytest.raises(ValueError, match="expected_bytes"):
        AcquisitionBudgetState().allows_request(policy, depth=0, expected_bytes=-1)
    with pytest.raises(ValueError, match="seconds_since_last_request"):
        AcquisitionBudgetState().allows_request(
            policy,
            depth=0,
            seconds_since_last_request=-1,
        )
    with pytest.raises(ValueError, match="retries_used"):
        policy.allows_retry(-1)
