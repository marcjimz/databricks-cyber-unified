"""Config-driven OCSF synthetic gold-table generator.

Produces deterministic OCSF-aligned rows for each security domain's gold
table. The distributions mirror the app's in-memory ``SeedProvider`` (same
mulberry32 PRNG seeds) so the ``seed`` and ``lakebase`` providers tell the
same story.

Two consumers:
  * The Lakeflow pipeline's demo-load stage (``00_gold.py``) turns these
    rows into Spark DataFrames -> UC gold tables.
  * The standalone CSV emitter (``make generate-data``) writes them to
    ``data/<domain>/*.csv`` for reference and bring-your-own-data examples.

Gold grain (denormalized so every measure expression in ``cyber360.yaml``
is valid over a single ``source_table``):
  * ``identity_access``          -> one row per account
  * ``vulnerability_management`` -> one row per finding

Timestamps are anchored to a caller-supplied ``now_ms``. The pipeline passes
the real ``current_timestamp`` so the ``now() - INTERVAL N DAY`` windows in
the measure expressions always resolve against fresh data.
"""

from __future__ import annotations

from datetime import datetime, timezone

DAY_MS = 86_400_000
WINDOW_DAYS = 30

ORG_UNITS = [
    "Acute Care", "Ambulatory", "Medical Group", "Pharmacy",
    "Revenue Cycle", "Corporate IT", "Research", "Supply Chain",
]
AUTH_PROTOCOLS = ["SAML", "OIDC", "Kerberos", "LDAP"]
REGIONS = ["Utah", "Idaho", "Nevada", "Colorado", "Montana", "Wyoming"]
ASSET_TYPES = ["Server", "Workstation", "Medical Device", "Network", "Container"]

# Identity account inventory sizing (mirrors SeedProvider).
ID_TOTAL = 9000
ID_PRIVILEGED = 5142
ID_ORPHANED = 38
ID_DORMANT_ADMINS = 12

# Vulnerability finding sizing (mirrors SeedProvider).
VULN_CRITICAL = 142
VULN_CRITICAL_KEV = 18
VULN_HIGH = 891
VULN_MEDIUM = 1400
VULN_LOW = 900
VULN_EXCEPTIONS = 24
VULN_RESOLVED = 2600

IDENTITY_SEED = 0x1DE17
VULN_SEED = 0x5EC1


def default_now_ms() -> int:
    """Current wall-clock time in epoch milliseconds (UTC)."""
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


# ---------------------------------------------------------------------------
# Mulberry32 PRNG (identical output to the TypeScript / SeedProvider version)
# ---------------------------------------------------------------------------

def mulberry32(seed: int):
    a = seed & 0xFFFFFFFF

    def next_val() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((a ^ (a >> 15)) * (1 | a)) & 0xFFFFFFFF
        t = (t + (((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        t = (t ^ (t >> 14)) & 0xFFFFFFFF
        return t / 4294967296

    return next_val


def _pick(rng, items):
    return items[int(rng() * len(items))]


def _rand_int(rng, lo: int, hi: int) -> int:
    return int(rng() * (hi - lo + 1)) + lo


def _chance(rng, prob: float) -> bool:
    return rng() < prob


def _ts_days_ago(rng, days_ago: int, now_ms: int) -> datetime:
    ms = now_ms - days_ago * DAY_MS - int(rng() * DAY_MS)
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _ms(dt: datetime | None) -> int | None:
    return None if dt is None else int(dt.timestamp() * 1000)


# ---------------------------------------------------------------------------
# Identity gold rows (account grain)
# ---------------------------------------------------------------------------

def generate_identity_rows(now_ms: int | None = None) -> list[dict]:
    """One row per account with all columns the identity measures reference."""
    now_ms = now_ms or default_now_ms()
    rng = mulberry32(IDENTITY_SEED)
    rows: list[dict] = []

    for i in range(ID_TOTAL):
        is_priv = i < ID_PRIVILEGED
        is_orphaned = i >= ID_TOTAL - ID_ORPHANED
        is_dormant_admin = is_priv and i < ID_DORMANT_ADMINS

        if is_dormant_admin:
            last_activity = _ts_days_ago(rng, _rand_int(rng, 95, 200), now_ms)
        elif is_orphaned:
            last_activity = _ts_days_ago(rng, _rand_int(rng, 40, 120), now_ms)
        else:
            last_activity = _ts_days_ago(rng, _rand_int(rng, 0, 20), now_ms)

        last_recertified = (
            _ts_days_ago(rng, _rand_int(rng, 0, 89), now_ms)
            if _chance(rng, 0.94)
            else _ts_days_ago(rng, _rand_int(rng, 91, 200), now_ms)
        )

        via_sso = _chance(rng, 0.91)
        is_mfa = _chance(rng, 0.992)
        provisioning_hours = _rand_int(rng, 36, 66) if _chance(rng, 0.15) else None
        status = "orphaned" if is_orphaned else ("dormant" if is_dormant_admin else "active")

        rows.append({
            "account_uid": f"acct-{100000 + i}",
            "account_name": f"svc.admin.{i}" if is_priv else f"caregiver.{i}",
            "time": last_activity,
            "actor_user_org_unit": _pick(rng, ORG_UNITS),
            "auth_protocol": _pick(rng, ["SAML", "OIDC"]) if via_sso else _pick(rng, AUTH_PROTOCOLS),
            "is_privileged": is_priv,
            "status": status,
            "is_mfa": is_mfa,
            "via_sso": via_sso,
            "owner_active": not is_orphaned,
            "in_pam_vault": _chance(rng, 0.87) if is_priv else False,
            "provisioning_hours": float(provisioning_hours) if provisioning_hours is not None else None,
            "last_recertified": last_recertified,
            "last_activity": last_activity,
        })

    return rows


# ---------------------------------------------------------------------------
# Vulnerability gold rows (finding grain)
# ---------------------------------------------------------------------------

def _sla_days(sev: int) -> int:
    return {5: 15, 4: 30, 3: 60}.get(sev, 90)


def _cvss_for(rng, sev: int) -> float:
    if sev == 5:
        return round((9 + rng() * 1) * 10) / 10
    if sev == 4:
        return round((7 + rng() * 1.9) * 10) / 10
    if sev == 3:
        return round((4 + rng() * 2.9) * 10) / 10
    return round((0.1 + rng() * 3.8) * 10) / 10


def generate_vulnerability_rows(now_ms: int | None = None) -> list[dict]:
    """One row per finding with all columns the vulnerability measures reference."""
    now_ms = now_ms or default_now_ms()
    rng = mulberry32(VULN_SEED)
    rows: list[dict] = []
    seq = 0

    def make(sev: int, status: int, *, is_kev: bool = False, has_exception: bool = False):
        nonlocal seq
        seq += 1
        first_seen = _ts_days_ago(rng, _rand_int(rng, 1, 90), now_ms)
        due = datetime.fromtimestamp((_ms(first_seen) + _sla_days(sev) * DAY_MS) / 1000, tz=timezone.utc)
        resolved_time = None
        if status == 4:
            within_sla = _chance(rng, 0.83)
            cap = min(_sla_days(sev) - 1, 16)
            patch_days = _rand_int(rng, 2, cap) if within_sla else _sla_days(sev) + _rand_int(rng, 1, 8)
            resolved_time = datetime.fromtimestamp(
                (_ms(first_seen) + patch_days * DAY_MS) / 1000, tz=timezone.utc
            )

        # Device scan recency: findings on unscanned/stale devices bring coverage down.
        if _chance(rng, 0.965):
            last_scanned = _ts_days_ago(rng, _rand_int(rng, 0, 29), now_ms)
        elif _chance(rng, 0.5):
            last_scanned = _ts_days_ago(rng, _rand_int(rng, 31, 120), now_ms)
        else:
            last_scanned = None

        hostname_type = _pick(rng, ASSET_TYPES).lower().replace(" ", "")
        rows.append({
            "finding_uid": f"vf-{200000 + seq}",
            "first_seen": first_seen,
            "severity_id": sev,
            "status_id": status,
            "cve_uid": f"CVE-2026-{_rand_int(rng, 1000, 49999)}",
            "cvss_score": _cvss_for(rng, sev),
            "cve_is_kev": is_kev,
            "device_hostname": f"ih-{hostname_type}-{_rand_int(rng, 100, 999)}",
            "device_type": _pick(rng, ASSET_TYPES),
            "device_region": _pick(rng, REGIONS),
            "resolved_time": resolved_time,
            "is_fix_available": _chance(rng, 0.78),
            "remediation_due": due,
            "has_exception": has_exception,
            "last_scanned": last_scanned,
        })

    for i in range(VULN_CRITICAL):
        make(5, 1 if i < VULN_CRITICAL_KEV else 2, is_kev=i < VULN_CRITICAL_KEV)
    for _ in range(VULN_HIGH):
        make(4, 1 if _chance(rng, 0.5) else 2)
    for _ in range(VULN_MEDIUM):
        make(3, 1 if _chance(rng, 0.5) else 2)
    for _ in range(VULN_LOW):
        make(2, 1 if _chance(rng, 0.5) else 2)
    for _ in range(VULN_EXCEPTIONS):
        make(_pick(rng, [4, 3]), 3, has_exception=True)
    for _ in range(VULN_RESOLVED):
        make(_pick(rng, [5, 4, 3, 2]), 4)

    return rows


# ---------------------------------------------------------------------------
# Registry: gold table (unqualified name) -> generator fn
# ---------------------------------------------------------------------------

GOLD_GENERATORS = {
    "identity_access": generate_identity_rows,
    "vulnerability_management": generate_vulnerability_rows,
}


def generate_gold(table: str, now_ms: int | None = None) -> list[dict]:
    """Generate rows for a gold table by its unqualified name."""
    gen = GOLD_GENERATORS.get(table)
    if gen is None:
        raise KeyError(
            f"No generator for gold table '{table}'. Known: {sorted(GOLD_GENERATORS)}"
        )
    return gen(now_ms)
