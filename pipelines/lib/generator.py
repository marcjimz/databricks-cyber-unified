"""Config-driven synthetic gold-table generator.

Produces deterministic rows for each security domain's gold table, anchored to
a caller-supplied ``now_ms``. The pipeline passes the real ``current_timestamp``
so the ``now() - INTERVAL N DAY`` windows (and the metric view's ``day``
dimension) always resolve against fresh data.

Grain (denormalized so every measure expression in the domain's metric view is
valid over a single ``source_table``):
  * ``phishing_detail`` -> one row per recipient-per-campaign event

Two consumers:
  * The Lakeflow pipeline's demo-load stage turns these rows into Spark
    DataFrames -> UC gold tables (only in the ``sandbox`` synthetic path; the
    ``edp_dev`` target reads the real CyberArk-federated source instead).
  * The standalone CSV emitter (``make generate-data``) writes them to
    ``data/<domain>/*.csv`` for reference.
"""

from __future__ import annotations

from datetime import datetime, timezone

DAY_MS = 86_400_000
WINDOW_DAYS = 30

# ── Phishing (simulated-campaign) synthetic universe ─────────────────────────
PHISH_REGIONS = ["Canyons", "Intermountain", "Wasatch", "Desert", "Highlands", "Valley"]
PHISH_GROUPS = ["A", "B", "C", "D", "E", "F"]
PHISH_CAMPAIGN_TYPES = ["Drive By", "Spear Phishing", "Credential Harvest", "Attachment"]
# (campaign name, email template name, template subject line)
PHISH_CAMPAIGNS = [
    ("Nov. 2024 Campaign Intermountain", "Microsoft Voicemail Notification", "You Have a New VN"),
    ("Q4 Credential Refresh", "Okta Password Expiry", "Action Required: Reset Your Password"),
    ("Payroll Update Drive", "Workday Payroll Notice", "Your December Pay Statement"),
    ("Benefits Enrollment Blast", "HR Open Enrollment", "Complete Your 2025 Benefits"),
    ("Shipping Notice Test", "DHL Delivery Alert", "Package Awaiting Delivery"),
]
# Simulated-phishing outcome mix (must sum to ~1.0). "No Action" dominates; a
# realistic minority click, a healthy share report, a few bounce.
PHISH_OUTCOMES = [
    ("No Action", 0.66),
    ("Reported", 0.18),
    ("Email Click", 0.11),
    ("Email Open", 0.04),
    ("Bounced", 0.01),
]
PHISH_FIRST_NAMES = [
    "Alton", "Marcy", "Devon", "Priya", "Luis", "Hana", "Grant", "Ada",
    "Theo", "Nadia", "Owen", "Rosa", "Kai", "Mira", "Seth", "Lena",
]
PHISH_LAST_NAMES = [
    "Burgett", "Nguyen", "Ramos", "Patel", "OConnor", "Kim", "Silva", "Novak",
    "Frost", "Abadi", "Delgado", "Haas", "Yoon", "Barros", "Whitaker", "Ferro",
]

# Phishing sizing (one row per recipient-per-campaign event).
PHISH_RECIPIENTS = 1800
PHISH_SEED = 0xF15A


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


def _weighted_pick(rng, weighted: list[tuple]):
    """Pick from a list of (value, weight) by cumulative weight."""
    total = sum(w for _, w in weighted)
    r = rng() * total
    upto = 0.0
    for value, weight in weighted:
        upto += weight
        if r < upto:
            return value
    return weighted[-1][0]


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
# Phishing gold rows (recipient-per-campaign-event grain)
# ---------------------------------------------------------------------------
#
# Columns mirror the CyberArk `phishing_detail` source so the synthetic sandbox
# table is schema-compatible with the real federated table the edp_dev target
# reads. The metric view (mv_phishing) derives its `day` dimension from
# `eventtimestamp` and its rate measures from `eventtype`.

def generate_phishing_rows(now_ms: int | None = None) -> list[dict]:
    """One row per recipient-per-campaign phishing-simulation event."""
    now_ms = now_ms or default_now_ms()
    rng = mulberry32(PHISH_SEED)
    rows: list[dict] = []

    for i in range(PHISH_RECIPIENTS):
        first = _pick(rng, PHISH_FIRST_NAMES)
        last = _pick(rng, PHISH_LAST_NAMES)
        email = f"{first[0].lower()}.{last.lower()}@imail.org"

        campaign_name, template_name, template_subject = _pick(rng, PHISH_CAMPAIGNS)
        campaign_type = _pick(rng, PHISH_CAMPAIGN_TYPES)

        # Campaign runs on a ~14-day window that started 0-30 days ago; the
        # send + event land inside it so `day` spreads across the reporting
        # windows the app filters on.
        start = _ts_days_ago(rng, _rand_int(rng, 0, 30), now_ms)
        start_ms = _ms(start)
        end_ms = start_ms + _rand_int(rng, 7, 21) * DAY_MS
        sent_ms = start_ms + _rand_int(rng, 0, 3) * DAY_MS + int(rng() * DAY_MS)
        # Event happens 0-2 days after send.
        event_ms = sent_ms + int(rng() * 2 * DAY_MS)

        eventtype = _weighted_pick(rng, PHISH_OUTCOMES)
        # Pass = the recipient did NOT fall for it (reported or took no action).
        passed = eventtype in ("Reported", "No Action")

        user_active = _chance(rng, 0.96)
        user_deleted = None if user_active else _ts_days_ago(rng, _rand_int(rng, 1, 400), now_ms)

        rows.append({
            "userfirstname": first,
            "userlastname": last,
            "useremailaddress": email,
            "useractiveflag": 1 if user_active else 0,
            "userdeletedate": _iso(user_deleted),
            "senttimestamp": _iso(_dt(sent_ms)),
            "eventtimestamp": _iso(_dt(event_ms)),
            "eventtype": eventtype,
            "autoenrollment": 1 if _chance(rng, 0.7) else 0,
            "campaignstartdate": _iso(_dt(start_ms)),
            "campaigntype": campaign_type,
            "campaignstatus": "Completed" if end_ms < now_ms else "Active",
            "templatename": template_name,
            "templatesubject": template_subject,
            "assessmentisarchived": "false" if _chance(rng, 0.9) else "true",
            "usertags": _pick(rng, ["E", "S", "M", "L"]),
            "sso_id": f"SSO{100000 + i}",
            "campaignenddate": _iso(_dt(end_ms)),
            "Pass": passed,
            "Pass_Rate": 1.0 if passed else 0.0,
            "Group": _pick(rng, PHISH_GROUPS),
            "Region": _pick(rng, PHISH_REGIONS),
            "campaignname": campaign_name,
        })

    return rows


def _dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    """ISO-8601 with a trailing Z (matches the CyberArk source's timestamp form)."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ---------------------------------------------------------------------------
# Registry: gold table (unqualified name) -> generator fn
# ---------------------------------------------------------------------------

GOLD_GENERATORS = {
    "phishing_detail": generate_phishing_rows,
}


def generate_gold(table: str, now_ms: int | None = None) -> list[dict]:
    """Generate rows for a gold table by its unqualified name."""
    gen = GOLD_GENERATORS.get(table)
    if gen is None:
        raise KeyError(
            f"No generator for gold table '{table}'. Known: {sorted(GOLD_GENERATORS)}"
        )
    return gen(now_ms)
