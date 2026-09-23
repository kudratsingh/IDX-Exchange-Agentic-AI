"""Column allowlist, deny-list, and agent-contact set (SAFETY_INVARIANTS.md, WO-002).

Every query names its columns from ALLOWLIST[table]; `check_column` and the WO-004
query builders raise on any other name. DENYLIST: never selected, logged, or returned.
AGENT_CONTACT: in the data, but never in a reply, email, fixture, screenshot, or log.
"""

from __future__ import annotations

# Columns the contracts need (Listing, SoldComp, MarketStats). Nothing else is selected.
# PROVISIONAL (names from ARCHITECTURE.md, CONTRACTS.md): tests/test_columns.py checks
# each against docs/data/schema_notes.md; names absent from the notes are removed.
ALLOWLIST: dict[str, frozenset[str]] = {
    "rets_property": frozenset(
        {
            "L_ListingID",
            "L_DisplayId",
            "L_City",
            "L_Zip",
            "L_SystemPrice",
            "L_Keyword2",  # bedrooms
            "LM_Dec_3",  # bathrooms (decimal; never compared with the sold table)
            "LM_Int2_3",  # living area
            "L_Type_",  # property subtype
            "L_Class",
            "L_Status",
            "StandardStatus",
            "L_Remarks",  # untrusted text; returned to the model, never logged
            "L_Photos",
            "L_UpdateDate",
            "ModificationTimestamp",
            "ListingContractDate",
            "listing_contract_date_d",
            "modification_d",
        }
    ),
    "california_sold": frozenset(
        {
            "ListingKey",
            "ListingId",
            "City",
            "PostalCode",
            "ClosePrice",
            "CloseDate",
            "close_date_d",
            "ListPrice",
            "OriginalListPrice",
            "PurchaseContractDate",
            "purchase_contract_date_d",
            "ListingContractDate",
            "listing_contract_date_d",
            "DaysOnMarket",
            "BedroomsTotal",
            "BathroomsTotalInteger",
            "LivingArea",
            "PropertyType",
            "PropertySubType",
            "YearBuilt",
            "StandardStatus",
            "ModificationTimestamp",
        }
    ),
}

# Never selected, logged, or returned. Candidates from SAFETY_INVARIANTS.md,
# confirmed against the profiling run. Checked first in `check_column`.
DENYLIST: frozenset[str] = frozenset(
    {
        "AccessCode",
        "LockBoxSerialNumber",
        "LockBoxLocation",
        "LockBoxType",
        "PrivateRemarks",
        "PrivateOfficeRemarks",
        "ShowingInstructions",
        "OwnerName",
        "OwnerPhone",
        "OccupantName",
        "OccupantPhone",
    }
)

# Present in the data layer, never returned. Name patterns from the profiling run
# (`*Agent*Email`, `*Agent*Phone`, `*Agent*Name`, `LA1_*`) resolve to these once known.
AGENT_CONTACT: frozenset[str] = frozenset(
    {
        "ListAgentEmail",
        "ListAgentDirectPhone",
        "ListAgentOfficePhone",
        "ListAgentFullName",
        "ListAgentFirstName",
        "ListAgentLastName",
        "ListOfficeName",
        "ListOfficePhone",
        "ListOfficeEmail",
        "BuyerAgentEmail",
        "BuyerAgentDirectPhone",
        "BuyerAgentFullName",
        "LA1_AgentID",
        "LA1_LoginName",
        "LA1_UserFirstName",
        "LA1_UserLastName",
        "LA1_Email",
        "LA1_PhoneNumber1",
        "LO1_OrganizationName",
        "LO1_PhoneNumber1",
    }
)

# Union of every table's allowlist; tests use it to prove no overlap with the
# deny-list or agent-contact set.
ALL_ALLOWED: frozenset[str] = frozenset().union(*ALLOWLIST.values())


def check_column(table: str, column: str) -> str:
    """Return the column if it is allowlisted for the table; raise otherwise.

    Checks in order: 1. deny-listed, 2. agent contact, 3. unknown table,
    4. not in that table's allowlist. Each failure raises ValueError naming the
    reason. The WO-004 query builders run every selected column through it.
    """
    if column in DENYLIST:
        raise ValueError(f"column {column!r} is deny-listed")
    if column in AGENT_CONTACT:
        raise ValueError(
            f"column {column!r} is an agent contact field and is never selected"
        )
    allowed = ALLOWLIST.get(table)
    if allowed is None:
        raise ValueError(f"unknown table {table!r}")
    if column not in allowed:
        raise ValueError(f"column {column!r} is not allowlisted for {table}")
    return column
