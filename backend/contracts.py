"""Phase 0 boundaries. Implementations belong to later phases."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence


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
    def enqueue(self, scope: SyncScope, trigger: Trigger) -> EnqueueResult: ...
    def claim(self, worker_id: str) -> JobLease | None: ...
    def renew(self, lease: JobLease) -> JobLease: ...
    def complete(self, lease: JobLease, result_revision: str) -> None: ...
    def fail(self, lease: JobLease, error_code: str) -> None: ...


class CredentialStore(Protocol):
    def get(self, provider: str, owner: str) -> StoredCredential | None: ...
    def compare_and_swap(self, provider: str, owner: str, expected_revision: str,
                         credential: StoredCredential) -> bool: ...
