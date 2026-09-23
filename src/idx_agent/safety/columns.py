"""Column allowlist, deny-list, and agent-contact set (SAFETY_INVARIANTS.md, WO-002).

Every query names its columns from ALLOWLIST[table]; `check_column` and the WO-004
query builders raise on any other name. DENYLIST: never selected, logged, or returned.
AGENT_CONTACT: in the data, but never in a reply, email, fixture, screenshot, or log.
Names confirmed against docs/data/schema_notes.md (profiling run of 2026-09-23).
"""

from __future__ import annotations

# Columns the contracts need (Listing, SoldComp, MarketStats). Nothing else is selected.
# The *_d columns are the generated DATE columns from scripts/migrations/001.
ALLOWLIST: dict[str, frozenset[str]] = {
    "rets_property": frozenset(
        {
            "L_ListingID",  # join key (cast) to california_sold.ListingKey
            "L_DisplayId",  # public listing id
            "L_Address",  # street address; blank in replies if a display flag forbids
            "L_City",
            "L_Zip",
            "L_SystemPrice",  # list price
            "L_Keyword2",  # bedrooms
            "LM_Dec_3",  # bathrooms (decimal; never compared with the sold table)
            "LM_Int2_3",  # living area (sqft)
            "L_Type_",  # property subtype (RESO vocabulary)
            "L_Class",
            "L_Status",
            "StandardStatus",
            "L_Remarks",  # untrusted text; returned to the model, never logged
            "L_Photos",  # JSON array
            "PhotoCount",
            "YearBuilt",
            "DaysOnMarket",
            "AssociationFee",
            "AssociationFeeFrequency",
            "LotSizeSquareFeet",
            "LotSizeUnits",
            "LivingAreaUnits",
            "LMD_MP_Latitude",
            "LMD_MP_Longitude",
            "PoolPrivateYN",
            "ViewYN",
            "FireplaceYN",
            "ModificationTimestamp",
            "ListingContractDate",
            "listing_contract_date_d",
            "modification_d",
        }
    ),
    "california_sold": frozenset(
        {
            "ListingKey",
            "UnparsedAddress",
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
            "LotSizeSquareFeet",
            "PropertyType",
            "PropertySubType",
            "YearBuilt",
            "AssociationFee",
            "Latitude",
            "Longitude",
            "PoolPrivateYN",
            "ViewYN",
            "FireplaceYN",
        }
    ),
}

# Never selected, logged, or returned. The profiling run found none of the candidate
# names from SAFETY_INVARIANTS.md in either table; they stay listed so a future refresh
# of the data cannot bring one in unnoticed. Checked first in `check_column`.
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

# Present in the data layer, never returned. Exactly the names the profiling run found
# by pattern (*Agent*, *Office*, LA1_*, LO1_*) in each table.
AGENT_CONTACT: frozenset[str] = frozenset(
    {
        # rets_property
        "LA1_UserFirstName",
        "LA1_UserLastName",
        "LO1_OrganizationName",
        "ListAgentOfficePhone",
        "ListOfficeEmail",
        "ListAgentEmail",
        "ListAgentDirectPhone",
        "ListAgentAOR",
        "ListAgentFullName",
        "CoListAgentFullName",
        "ListAgentKey",
        # california_sold
        "ListAgentFirstName",
        "ListAgentLastName",
        "ListOfficeName",
        "BuyerOfficeName",
        "BuyerAgentFirstName",
        "BuyerAgentLastName",
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
