"""SeedProvider -- in-memory OCSF data generation and measure computation.

Faithfully ports the TypeScript SeedProvider from the v0 reference.
Uses the same mulberry32 PRNG seeds to produce identical data distributions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.config import (
    Cyber360Config,
    MeasureConfig,
    TrendConfig,
    build_change,
    format_measure_value,
    rag_for_measure,
    rollup_status,
)
from models.common import Kpi, KpiChange, KpiLineage, Paginated, TrendInfo, TrendPoint
from models.domain import BreakdownItem, DomainMetricsResponse
from models.identity import AccountRow, AccountsQuery
from models.incidents import (
    IncidentMttr,
    IncidentRecord,
    IncidentSeverityCounts,
    IncidentsResponse,
)
from models.scorecard import (
    ComplianceCounts,
    DomainHealth,
    DomainHealthHighlight,
    ScorecardOrg,
    ScorecardResponse,
)
from models.vulnerability import FindingRow, FindingsQuery

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOW = int(datetime(2026, 6, 23, 18, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
DAY = 86_400_000
WINDOW_DAYS = 30

ORG_UNITS = ["Acute Care", "Ambulatory", "Medical Group", "Pharmacy", "Revenue Cycle", "Corporate IT", "Research", "Supply Chain"]
AUTH_PROTOCOLS = ["SAML", "OIDC", "Kerberos", "LDAP"]
MFA_FACTORS = ["FIDO2", "Push", "TOTP", "SMS"]
SERVICES = ["Epic", "Workday", "ServiceNow", "Microsoft 365", "Citrix", "Cerner", "VPN"]
REGIONS = ["Utah", "Idaho", "Nevada", "Colorado", "Montana", "Wyoming"]
ASSET_TYPES = ["Server", "Workstation", "Medical Device", "Network", "Container"]
OS_NAMES = ["Windows Server", "RHEL", "Ubuntu", "VMware ESXi", "Windows 11"]


# ---------------------------------------------------------------------------
# Mulberry32 PRNG (deterministic, matches TypeScript implementation)
# ---------------------------------------------------------------------------

def mulberry32(seed: int):
    """Mulberry32 PRNG -- produces identical output to the JS version."""
    a = seed & 0xFFFFFFFF

    def next_val() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((a ^ (a >> 15)) * (1 | a)) & 0xFFFFFFFF
        t = (t + (((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        t = (t ^ (t >> 14)) & 0xFFFFFFFF
        return t / 4294967296

    return next_val


def pick(rng, items: list | tuple):
    return items[int(rng() * len(items))]


def rand_int(rng, lo: int, hi: int) -> int:
    return int(rng() * (hi - lo + 1)) + lo


def chance(rng, prob: float) -> bool:
    return rng() < prob


def time_days_ago(rng, days_ago: int, now: int) -> int:
    return now - days_ago * DAY - int(rng() * DAY)


def day_key(t: int) -> str:
    return datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def pct(n: int | float, d: int | float) -> float:
    return 0 if d == 0 else (n / d) * 100


# ---------------------------------------------------------------------------
# OCSF Record Types (simplified dicts for seed use)
# ---------------------------------------------------------------------------

@dataclass
class AuthEvent:
    time: int
    is_mfa: bool
    via_sso: bool
    auth_protocol: str
    org_unit: str
    status_success: bool


@dataclass
class AccountChange:
    time: int
    activity_id: int
    provisioning_hours: int | None


@dataclass
class AccountRecord:
    uid: str
    name: str
    org_unit: str
    is_privileged: bool
    in_pam_vault: bool
    sso_enrolled: bool
    last_activity: int | None
    owner_active: bool
    last_recertified: int | None
    status: str  # active, dormant, orphaned, disabled


@dataclass
class VulnFinding:
    finding_uid: str
    time: int
    severity_id: int  # 2=Low, 3=Medium, 4=High, 5=Critical
    status_id: int    # 1=New, 2=InProgress, 3=Exception, 4=Resolved
    cve_uid: str
    cvss_score: float
    is_kev: bool
    device_hostname: str
    device_type: str
    device_region: str
    first_seen: int
    resolved_time: int | None
    is_fix_available: bool
    remediation_due: int
    has_exception: bool


@dataclass
class AssetRecord:
    uid: str
    hostname: str
    type: str
    region: str
    last_scanned: int | None
    agent_installed: bool


@dataclass
class IdentitySeed:
    auth_events: list[AuthEvent] = field(default_factory=list)
    account_changes: list[AccountChange] = field(default_factory=list)
    accounts: list[AccountRecord] = field(default_factory=list)


@dataclass
class VulnerabilitySeed:
    findings: list[VulnFinding] = field(default_factory=list)
    assets: list[AssetRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Seed data generators
# ---------------------------------------------------------------------------

_identity_cache: IdentitySeed | None = None
_vuln_cache: VulnerabilitySeed | None = None


def get_identity_seed() -> IdentitySeed:
    global _identity_cache
    if _identity_cache:
        return _identity_cache

    rng = mulberry32(0x1DE17)

    # Auth events
    auth_events = []
    for i in range(8000):
        is_mfa = chance(rng, 0.992)
        via_sso = chance(rng, 0.91)
        success = chance(rng, 0.94)
        auth_events.append(AuthEvent(
            time=time_days_ago(rng, rand_int(rng, 0, WINDOW_DAYS - 1), NOW),
            is_mfa=is_mfa,
            via_sso=via_sso,
            auth_protocol=pick(rng, ["SAML", "OIDC"]) if via_sso else pick(rng, AUTH_PROTOCOLS),
            org_unit=pick(rng, ORG_UNITS),
            status_success=success,
        ))

    # Account changes
    account_changes = []
    activities = [1, 2, 3, 4, 6, 8]
    for i in range(1200):
        activity = pick(rng, activities)
        _ = chance(rng, 0.2)  # is_priv (consumed for RNG consistency)
        account_changes.append(AccountChange(
            time=time_days_ago(rng, rand_int(rng, 0, WINDOW_DAYS - 1), NOW),
            activity_id=activity,
            provisioning_hours=rand_int(rng, 36, 66) if activity == 1 else None,
        ))

    # Account inventory
    accounts = []
    TOTAL = 9000
    PRIVILEGED = 5142
    ORPHANED = 38
    DORMANT_ADMINS = 12

    for i in range(TOTAL):
        is_priv = i < PRIVILEGED
        is_orphaned = i >= TOTAL - ORPHANED
        is_dormant_admin = is_priv and i < DORMANT_ADMINS

        if is_dormant_admin:
            last_activity = time_days_ago(rng, rand_int(rng, 95, 200), NOW)
        elif is_orphaned:
            last_activity = time_days_ago(rng, rand_int(rng, 40, 120), NOW)
        else:
            last_activity = time_days_ago(rng, rand_int(rng, 0, 20), NOW)

        recertified = (
            time_days_ago(rng, rand_int(rng, 0, 89), NOW)
            if chance(rng, 0.94)
            else time_days_ago(rng, rand_int(rng, 91, 200), NOW)
        )

        status = "orphaned" if is_orphaned else ("dormant" if is_dormant_admin else "active")

        accounts.append(AccountRecord(
            uid=f"acct-{100000 + i}",
            name=f"svc.admin.{i}" if is_priv else f"caregiver.{i}",
            org_unit=pick(rng, ORG_UNITS),
            is_privileged=is_priv,
            in_pam_vault=chance(rng, 0.87) if is_priv else False,
            sso_enrolled=chance(rng, 0.91),
            last_activity=last_activity,
            owner_active=not is_orphaned,
            last_recertified=recertified,
            status=status,
        ))

    _identity_cache = IdentitySeed(
        auth_events=auth_events,
        account_changes=account_changes,
        accounts=accounts,
    )
    return _identity_cache


def _sla_days(sev: int) -> int:
    if sev == 5:
        return 15  # Critical
    if sev == 4:
        return 30  # High
    if sev == 3:
        return 60  # Medium
    return 90  # Low


def _cvss_for(rng, sev: int) -> float:
    if sev == 5:
        return round((9 + rng() * 1) * 10) / 10
    if sev == 4:
        return round((7 + rng() * 1.9) * 10) / 10
    if sev == 3:
        return round((4 + rng() * 2.9) * 10) / 10
    return round((0.1 + rng() * 3.8) * 10) / 10


def get_vulnerability_seed() -> VulnerabilitySeed:
    global _vuln_cache
    if _vuln_cache:
        return _vuln_cache

    rng = mulberry32(0x5EC1)
    findings: list[VulnFinding] = []
    seq = 0

    def make(sev: int, status: int, *, is_kev: bool = False, has_exception: bool = False):
        nonlocal seq
        seq += 1
        first_seen = time_days_ago(rng, rand_int(rng, 1, 90), NOW)
        due = first_seen + _sla_days(sev) * DAY
        resolved_time = None
        if status == 4:
            within_sla = chance(rng, 0.83)
            cap = min(_sla_days(sev) - 1, 16)
            patch_days = rand_int(rng, 2, cap) if within_sla else _sla_days(sev) + rand_int(rng, 1, 8)
            resolved_time = first_seen + patch_days * DAY

        hostname_type = pick(rng, ASSET_TYPES).lower().replace(" ", "")
        findings.append(VulnFinding(
            finding_uid=f"vf-{200000 + seq}",
            time=first_seen,
            severity_id=sev,
            status_id=status,
            cve_uid=f"CVE-2026-{rand_int(rng, 1000, 49999)}",
            cvss_score=_cvss_for(rng, sev),
            is_kev=is_kev,
            device_hostname=f"ih-{hostname_type}-{rand_int(rng, 100, 999)}",
            device_type=pick(rng, ASSET_TYPES),
            device_region=pick(rng, REGIONS),
            first_seen=first_seen,
            resolved_time=resolved_time,
            is_fix_available=chance(rng, 0.78),
            remediation_due=due,
            has_exception=has_exception,
        ))

    # Open criticals: 142 (18 KEV)
    for i in range(142):
        make(5, 1 if i < 18 else 2, is_kev=i < 18)
    # Open highs: 891
    for _ in range(891):
        make(4, 1 if chance(rng, 0.5) else 2)
    # Open mediums: 1400
    for _ in range(1400):
        make(3, 1 if chance(rng, 0.5) else 2)
    # Open lows: 900
    for _ in range(900):
        make(2, 1 if chance(rng, 0.5) else 2)
    # Exceptions: 24
    for _ in range(24):
        make(pick(rng, [4, 3]), 3, has_exception=True)
    # Resolved: 2600
    for _ in range(2600):
        make(pick(rng, [5, 4, 3, 2]), 4)

    # Assets
    assets = []
    TOTAL_ASSETS = 6767
    UNSCANNED = 203
    for i in range(TOTAL_ASSETS):
        unscanned = i < UNSCANNED
        if unscanned:
            last_scanned = None if chance(rng, 0.4) else time_days_ago(rng, rand_int(rng, 31, 120), NOW)
        else:
            last_scanned = time_days_ago(rng, rand_int(rng, 0, 29), NOW)
        assets.append(AssetRecord(
            uid=f"asset-{300000 + i}",
            hostname=f"ih-asset-{i}",
            type=pick(rng, ASSET_TYPES),
            region=pick(rng, REGIONS),
            last_scanned=last_scanned,
            agent_installed=chance(rng, 0.96),
        ))

    _vuln_cache = VulnerabilitySeed(findings=findings, assets=assets)
    return _vuln_cache


# ---------------------------------------------------------------------------
# Incident seed data
# ---------------------------------------------------------------------------

INCIDENTS = [
    IncidentRecord(uid="inc-1", priority="P1", label="Critical", domain="vulnerability", status="investigating", mttr_hours=4.2, opened_time=int(datetime(2026, 6, 23, 13, 45, tzinfo=timezone.utc).timestamp() * 1000), title="Exploited KEV on perimeter VPN appliance"),
    IncidentRecord(uid="inc-2", priority="P2", label="High", domain="identity", status="investigating", mttr_hours=6.1, opened_time=int(datetime(2026, 6, 23, 8, 10, tzinfo=timezone.utc).timestamp() * 1000), title="Suspicious privileged login from new geo"),
    IncidentRecord(uid="inc-3", priority="P2", label="High", domain="vulnerability", status="open", mttr_hours=6.1, opened_time=int(datetime(2026, 6, 22, 22, 30, tzinfo=timezone.utc).timestamp() * 1000), title="Unpatched critical CVE on Epic interface server"),
    IncidentRecord(uid="inc-4", priority="P2", label="High", domain="identity", status="contained", mttr_hours=6.1, opened_time=int(datetime(2026, 6, 22, 16, 0, tzinfo=timezone.utc).timestamp() * 1000), title="Orphaned admin account reactivated"),
    IncidentRecord(uid="inc-5", priority="P2", label="High", domain="vulnerability", status="open", mttr_hours=6.1, opened_time=int(datetime(2026, 6, 22, 9, 20, tzinfo=timezone.utc).timestamp() * 1000), title="Scan gap on clinical network segment"),
    IncidentRecord(uid="inc-6", priority="P3", label="Medium", domain="identity", status="open", mttr_hours=18.4, opened_time=int(datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc).timestamp() * 1000), title="MFA fatigue attempts against caregiver accounts"),
    IncidentRecord(uid="inc-7", priority="P4", label="Low", domain="vulnerability", status="open", mttr_hours=3.2, opened_time=int(datetime(2026, 6, 20, 6, 0, tzinfo=timezone.utc).timestamp() * 1000), title="Low-sev TLS configuration finding"),
]

INCIDENT_OPEN_COUNTS = IncidentSeverityCounts(P1=1, P2=4, P3=17, P4=43)
INCIDENT_MTTR = IncidentMttr(P1="4.2h", P2="6.1h", P3="18.4h", P4="3.2d")


# ---------------------------------------------------------------------------
# KPI builder
# ---------------------------------------------------------------------------

def _build_kpi(
    measure: MeasureConfig,
    raw: float,
    period: int,
    override_caption: str | None = None,
    override_trend: TrendConfig | None = None,
) -> Kpi:
    trend = override_trend or measure.trend
    return Kpi(
        key=measure.name,
        label=measure.label,
        value=format_measure_value(measure, raw),
        raw=raw,
        status=rag_for_measure(measure, raw),
        caption=override_caption or measure.caption,
        trend=TrendInfo(direction=trend.direction, label=trend.label) if trend else None,
        change=KpiChange(**build_change(measure, raw, period)),
        lineage=KpiLineage(
            measure=measure.name,
            expression=measure.expression,
            comment=measure.comment,
        ),
    )


# ---------------------------------------------------------------------------
# SeedProvider
# ---------------------------------------------------------------------------

class SeedProvider:
    """In-memory data provider using deterministic OCSF seed data."""

    source = "seed"

    def __init__(self, config: Cyber360Config):
        self.config = config

    # ── Identity computation ──

    def _compute_identity(self) -> dict[str, Any]:
        seed = get_identity_seed()
        total_auth = len(seed.auth_events)
        mfa_count = sum(1 for e in seed.auth_events if e.is_mfa)
        sso_count = sum(1 for e in seed.auth_events if e.via_sso)
        mfa_adoption = pct(mfa_count, total_auth)
        sso_integration = pct(sso_count, total_auth)

        privileged = [a for a in seed.accounts if a.is_privileged]
        priv_count = len(privileged)
        pam_covered = sum(1 for a in privileged if a.in_pam_vault)
        pam_coverage = pct(pam_covered, priv_count)
        orphaned = sum(1 for a in seed.accounts if a.status == "orphaned")
        dormant_admins = sum(
            1 for a in privileged
            if a.last_activity is not None and a.last_activity < NOW - 90 * DAY
        )
        recertified = sum(
            1 for a in seed.accounts
            if a.last_recertified is not None and a.last_recertified >= NOW - 90 * DAY
        )
        recert_pct = pct(recertified, len(seed.accounts))

        creates = [c for c in seed.account_changes if c.activity_id == 1 and c.provisioning_hours]
        avg_prov_hours = sum(c.provisioning_hours for c in creates) / max(len(creates), 1)
        avg_prov_days = avg_prov_hours / 24

        return {
            "seed": seed,
            "mfa_adoption": mfa_adoption,
            "sso_integration": sso_integration,
            "priv_count": priv_count,
            "pam_coverage": pam_coverage,
            "orphaned": orphaned,
            "dormant_admins": dormant_admins,
            "recert_pct": recert_pct,
            "avg_prov_days": avg_prov_days,
        }

    def _identity_values(self, c: dict[str, Any]) -> dict[str, float]:
        return {
            "mfa_adoption": c["mfa_adoption"],
            "privileged_accounts": c["priv_count"],
            "orphaned_accounts": c["orphaned"],
            "sso_integration": c["sso_integration"],
            "pam_vault_coverage": c["pam_coverage"],
            "avg_provisioning": c["avg_prov_days"],
            "access_recertification": c["recert_pct"],
            "dormant_admin_accounts": c["dormant_admins"],
        }

    # ── Vulnerability computation ──

    def _compute_vulnerability(self) -> dict[str, Any]:
        seed = get_vulnerability_seed()
        is_open = lambda s: s in (1, 2)

        critical_open = sum(1 for f in seed.findings if f.severity_id == 5 and is_open(f.status_id))
        high_open = sum(1 for f in seed.findings if f.severity_id == 4 and is_open(f.status_id))
        kev_unpatched = sum(1 for f in seed.findings if f.is_kev and is_open(f.status_id))
        exceptions = sum(1 for f in seed.findings if f.has_exception and f.status_id == 3)

        resolved = [f for f in seed.findings if f.status_id == 4 and f.resolved_time is not None]
        within_sla = sum(1 for f in resolved if f.resolved_time <= f.remediation_due)
        patch_sla = pct(within_sla, len(resolved))
        mttp = (
            sum(f.resolved_time - f.first_seen for f in resolved)
            / max(len(resolved), 1)
            / DAY
        )

        scanned = sum(
            1 for a in seed.assets
            if a.last_scanned is not None and a.last_scanned >= NOW - 30 * DAY
        )
        scan_coverage = pct(scanned, len(seed.assets))
        unscanned = sum(
            1 for a in seed.assets
            if a.last_scanned is None or a.last_scanned < NOW - 30 * DAY
        )

        return {
            "seed": seed,
            "critical_open": critical_open,
            "high_open": high_open,
            "kev_unpatched": kev_unpatched,
            "exceptions": exceptions,
            "patch_sla": patch_sla,
            "mttp": mttp,
            "scan_coverage": scan_coverage,
            "unscanned": unscanned,
        }

    def _vulnerability_values(self, c: dict[str, Any]) -> dict[str, float]:
        return {
            "critical_cves_open": c["critical_open"],
            "high_cves_open": c["high_open"],
            "kev_unpatched": c["kev_unpatched"],
            "patch_sla_compliance": c["patch_sla"],
            "mean_time_to_patch": c["mttp"],
            "scan_coverage": c["scan_coverage"],
            "exception_count": c["exceptions"],
            "assets_unscanned": c["unscanned"],
        }

    # ── Shared helpers ──

    def _domain_kpis(self, domain_key: str, values: dict[str, float], period: int) -> list[Kpi]:
        domain = self.config.get_domain(domain_key)
        if not domain:
            return []
        return [_build_kpi(m, values.get(m.name, 0), period) for m in domain.metric_view.measures]

    def _get_values_for_domain(self, domain_key: str) -> dict[str, float]:
        if domain_key == "identity":
            return self._identity_values(self._compute_identity())
        elif domain_key == "vulnerability":
            return self._vulnerability_values(self._compute_vulnerability())
        return {}

    # ── Public API ──

    async def get_scorecard(self, period: int = 30) -> ScorecardResponse:
        values_by_domain: dict[str, dict[str, float]] = {}
        for d in self.config.domains:
            values_by_domain[d.key] = self._get_values_for_domain(d.key)

        # Top-line KPIs
        top_line_kpis: list[Kpi] = []
        for t in self.config.top_line_kpis:
            measure = self.config.get_measure(t.domain, t.measure)
            if not measure:
                continue
            raw = values_by_domain.get(t.domain, {}).get(t.measure, 0)
            top_line_kpis.append(_build_kpi(measure, raw, period, t.caption, t.trend))

        # Domain health cards
        domains: list[DomainHealth] = []
        for domain in self.config.domains:
            values = values_by_domain.get(domain.key, {})
            kpis = self._domain_kpis(domain.key, values, period)

            compliance = ComplianceCounts(green=0, amber=0, red=0, total=len(kpis))
            for k in kpis:
                if k.status == "green":
                    compliance.green += 1
                elif k.status == "amber":
                    compliance.amber += 1
                else:
                    compliance.red += 1

            score_vals = [values.get(n, 0) for n in domain.health.score_measures]
            score = round(sum(score_vals) / max(len(score_vals), 1))

            highlights: list[DomainHealthHighlight] = []
            for name in domain.health.highlights:
                kpi = next((k for k in kpis if k.key == name), None)
                if kpi:
                    highlights.append(DomainHealthHighlight(
                        label=kpi.label, value=kpi.value, status=kpi.status
                    ))

            domains.append(DomainHealth(
                key=domain.key,
                label=domain.short,
                status=rollup_status([k.status for k in kpis]),
                score=score,
                compliance=compliance,
                highlights=highlights,
            ))

        return ScorecardResponse(
            org=ScorecardOrg(name=self.config.org.name, caregivers=68000, cyber_staff=200),
            top_line_kpis=top_line_kpis,
            domains=domains,
        )

    async def get_domain_metrics(self, domain_key: str, period: int = 30) -> DomainMetricsResponse:
        domain = self.config.get_domain(domain_key)
        if not domain:
            raise ValueError(f"Unknown domain: {domain_key}")

        if domain_key == "identity":
            return self._get_identity_metrics(period)
        elif domain_key == "vulnerability":
            return self._get_vulnerability_metrics(period)
        raise ValueError(f"No seed data for domain: {domain_key}")

    def _get_identity_metrics(self, period: int) -> DomainMetricsResponse:
        c = self._compute_identity()
        kpis = self._domain_kpis("identity", self._identity_values(c), period)
        seed: IdentitySeed = c["seed"]

        # Trend: MFA adoption + SSO by day
        by_day: dict[str, dict[str, int]] = {}
        for e in seed.auth_events:
            k = day_key(e.time)
            if k not in by_day:
                by_day[k] = {"mfa": 0, "sso": 0, "total": 0}
            by_day[k]["total"] += 1
            if e.is_mfa:
                by_day[k]["mfa"] += 1
            if e.via_sso:
                by_day[k]["sso"] += 1

        adoption_trend = sorted(
            [
                TrendPoint(
                    day=date,
                    values={
                        "mfa": round(pct(v["mfa"], v["total"]) * 10) / 10,
                        "sso": round(pct(v["sso"], v["total"]) * 10) / 10,
                    },
                )
                for date, v in by_day.items()
            ],
            key=lambda t: t.day,
        )

        # Breakdown: auth by protocol
        proto_map: dict[str, int] = {}
        for e in seed.auth_events:
            proto_map[e.auth_protocol] = proto_map.get(e.auth_protocol, 0) + 1
        auth_by_protocol = [BreakdownItem(name=k, value=v) for k, v in proto_map.items()]

        # Breakdown: accounts by status
        status_map: dict[str, int] = {}
        for a in seed.accounts:
            status_map[a.status] = status_map.get(a.status, 0) + 1
        accounts_by_status = [BreakdownItem(name=k, value=v) for k, v in status_map.items()]

        domain = self.config.get_domain("identity")
        return DomainMetricsResponse(
            key="identity",
            label=domain.label if domain else "Identity & Access Management",
            status=rollup_status([k.status for k in kpis]),
            kpis=kpis,
            trends={"adoption": adoption_trend},
            breakdowns={"authByProtocol": auth_by_protocol, "accountsByStatus": accounts_by_status},
        )

    def _get_vulnerability_metrics(self, period: int) -> DomainMetricsResponse:
        c = self._compute_vulnerability()
        kpis = self._domain_kpis("vulnerability", self._vulnerability_values(c), period)
        seed: VulnerabilitySeed = c["seed"]

        # Trend: findings by severity by day
        by_day: dict[str, dict[str, int]] = {}
        for f in seed.findings:
            k = day_key(f.first_seen)
            if k not in by_day:
                by_day[k] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
            if f.severity_id == 5:
                by_day[k]["critical"] += 1
            elif f.severity_id == 4:
                by_day[k]["high"] += 1
            elif f.severity_id == 3:
                by_day[k]["medium"] += 1
            else:
                by_day[k]["low"] += 1

        intake_trend = sorted(
            [TrendPoint(day=date, values=v) for date, v in by_day.items()],
            key=lambda t: t.day,
        )[-30:]

        # Breakdown: open by severity
        sev_map = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
        for f in seed.findings:
            if f.status_id not in (1, 2):
                continue
            if f.severity_id == 5:
                sev_map["Critical"] += 1
            elif f.severity_id == 4:
                sev_map["High"] += 1
            elif f.severity_id == 3:
                sev_map["Medium"] += 1
            else:
                sev_map["Low"] += 1
        open_by_severity = [BreakdownItem(name=k, value=v) for k, v in sev_map.items()]

        # Breakdown: by asset type
        type_map: dict[str, int] = {}
        for f in seed.findings:
            type_map[f.device_type] = type_map.get(f.device_type, 0) + 1
        by_asset_type = [BreakdownItem(name=k, value=v) for k, v in type_map.items()]

        domain = self.config.get_domain("vulnerability")
        return DomainMetricsResponse(
            key="vulnerability",
            label=domain.label if domain else "Vulnerability Management",
            status=rollup_status([k.status for k in kpis]),
            kpis=kpis,
            trends={"intake": intake_trend},
            breakdowns={"openBySeverity": open_by_severity, "findingsByAssetType": by_asset_type},
        )

    async def get_accounts(self, query: AccountsQuery) -> Paginated[AccountRow]:
        seed = get_identity_seed()
        rows = seed.accounts

        if query.status:
            rows = [a for a in rows if a.status == query.status]
        if query.privileged is not None:
            rows = [a for a in rows if a.is_privileged == query.privileged]

        # Sort: most interesting first
        rank = {"orphaned": 0, "dormant": 1, "disabled": 2, "active": 3}
        rows = sorted(rows, key=lambda a: rank.get(a.status, 3))

        page = query.page
        ps = query.page_size
        start = (page - 1) * ps
        page_rows = rows[start:start + ps]

        return Paginated(
            rows=[
                AccountRow(
                    uid=a.uid,
                    name=a.name,
                    org_unit=a.org_unit,
                    privileged=a.is_privileged,
                    sso_enrolled=a.sso_enrolled,
                    in_pam_vault=a.in_pam_vault,
                    last_activity=(
                        datetime.fromtimestamp(a.last_activity / 1000, tz=timezone.utc).isoformat()
                        if a.last_activity else None
                    ),
                    status=a.status,
                )
                for a in page_rows
            ],
            total=len(rows),
            page=page,
            page_size=ps,
        )

    async def get_findings(self, query: FindingsQuery) -> Paginated[FindingRow]:
        seed = get_vulnerability_seed()

        sev_name = {5: "Critical", 4: "High", 3: "Medium", 2: "Low"}
        status_name = {1: "New", 2: "In Progress", 3: "Exception", 4: "Resolved"}

        # Filter to open findings only
        rows = [f for f in seed.findings if f.status_id in (1, 2)]

        if query.severity:
            rows = [f for f in rows if sev_name.get(f.severity_id) == query.severity]
        if query.kev_only:
            rows = [f for f in rows if f.is_kev]
        if query.sla_breached_only:
            rows = [f for f in rows if NOW > f.remediation_due]

        # Sort: KEV first, then highest CVSS
        rows = sorted(rows, key=lambda f: (not f.is_kev, -f.cvss_score))

        page = query.page
        ps = query.page_size
        start = (page - 1) * ps
        page_rows = rows[start:start + ps]

        return Paginated(
            rows=[
                FindingRow(
                    finding_uid=f.finding_uid,
                    cve=f.cve_uid,
                    cvss=f.cvss_score,
                    severity=sev_name.get(f.severity_id, "Low"),
                    is_kev=f.is_kev,
                    host=f.device_hostname,
                    asset_type=f.device_type,
                    first_seen=datetime.fromtimestamp(f.first_seen / 1000, tz=timezone.utc).isoformat(),
                    age_days=int((NOW - f.first_seen) / DAY),
                    sla_due=datetime.fromtimestamp(f.remediation_due / 1000, tz=timezone.utc).isoformat(),
                    sla_breached=NOW > f.remediation_due,
                    fix_available=f.is_fix_available,
                    status=status_name.get(f.status_id, "New"),
                )
                for f in page_rows
            ],
            total=len(rows),
            page=page,
            page_size=ps,
        )

    async def get_incidents(self) -> IncidentsResponse:
        return IncidentsResponse(
            active=INCIDENTS,
            open_counts=INCIDENT_OPEN_COUNTS,
            mttr=INCIDENT_MTTR,
        )
