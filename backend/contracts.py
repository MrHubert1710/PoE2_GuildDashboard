"""Phase 0 boundaries. Implementations belong to later phases."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, Sequence


class Trigger(str, Enum):
    AUTOMATIC = 'automatic'
    MANUAL = 'manual'


@dataclass(frozen=True)
class SyncScope:
    provider: str
    owner: str
    resource: str
    # A guild-wide endpoint uses one scope even if several leagues request it.


@dataclass(frozen=True)
class AdapterCapabilities:
    history: bool = False
    leagues: bool = False
    categories: bool = False
    prices: bool = False
    refresh_tokens: bool = False
    # These describe an implemented adapter, not promises based on documentation.


@dataclass(frozen=True)
class CachePolicy:
    minimum_interval_seconds: int
    conditional_requests: bool = True
    respect_provider_headers: bool = True


@dataclass(frozen=True)
class LeagueReference:
    provider_id: str
    game: str
    realm: str
    name: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class SourceRecord:
    external_id: str
    league: LeagueReference
    occurred_at: datetime
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class HistoryPage:
    records: Sequence[SourceRecord]
    next_cursor: str | None
    # None means the page is the final one, not that local history is complete.


@dataclass(frozen=True)
class PriceCategory:
    provider_id: str
    label: str
    feed: str
    schema_version: str


@dataclass(frozen=True)
class PriceFetchResult:
    not_modified: bool
    fetched_at: datetime
    etag: str | None
    payload: Mapping[str, Any] | None


@dataclass(frozen=True)
class ReportSnapshot:
    league_id: str
    revision: str
    algorithm_version: str
    data: Mapping[str, Any]


@dataclass(frozen=True)
class EnqueueResult:
    outcome: str  # queued | coalesced | limited | unavailable
    job_id: str | None


@dataclass(frozen=True)
class JobLease:
    job_id: str
    fencing_token: str
    expires_at: datetime


@dataclass(frozen=True)
class StoredCredential:
    revision: str
    access_expires_at: datetime | None
    refresh_expires_at: datetime | None
    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)


class LeagueCatalog(Protocol):
    capabilities: AdapterCapabilities
    cache_policy: CachePolicy

    def list_leagues(self) -> Sequence[LeagueReference]: ...


class GuildHistorySource(Protocol):
    capabilities: AdapterCapabilities
    cache_policy: CachePolicy

    def fetch_page(self, scope: SyncScope, cursor: str | None) -> HistoryPage: ...


class PriceCatalog(Protocol):
    capabilities: AdapterCapabilities
    cache_policy: CachePolicy

    def list_categories(self, league: LeagueReference) -> Sequence[PriceCategory]: ...


class PriceSource(Protocol):
    capabilities: AdapterCapabilities
    cache_policy: CachePolicy

    def fetch(self, league: LeagueReference, category: PriceCategory,
              etag: str | None = None) -> PriceFetchResult: ...


class ReportService(Protocol):
    def get_report(self, league_id: str, revision: str | None = None) -> ReportSnapshot: ...


class JobQueue(Protocol):
    # Phase 3 facade resolves league policy and the server-owned SyncScope.
    # Leases include id/lease_token; publish receives a short-lived SQL transaction.
    def enqueue(self, league_id: str, kind: str = 'history', trigger: str = 'automatic') -> Mapping[str, Any]: ...
    def claim(self, worker_id: str) -> Mapping[str, Any] | None: ...
    def renew(self, lease: Mapping[str, Any]) -> None: ...
    def complete(self, lease: Mapping[str, Any], publish: Callable[[Any], Mapping[str, Any]]) -> None: ...
    def fail(self, lease: Mapping[str, Any], error_code: str = 'adapter_error', *,
             retryable: bool = True, retry_after: float = 0) -> None: ...


class CredentialStore(Protocol):
    def get(self, provider: str, owner: str) -> StoredCredential | None: ...
    def compare_and_swap(self, provider: str, owner: str, expected_revision: str,
                         credential: StoredCredential) -> bool: ...
