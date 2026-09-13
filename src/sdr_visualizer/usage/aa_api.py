"""AA organization/company and exact (including virtual) suite verification."""

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.usage.transport import TransportError


def verify_identity(transport, headers, instance_id, org_id, company_id):
    discovery = transport.get_json(transport.route_url("discovery"), headers=headers)
    data = discovery.data
    if not isinstance(data, dict) or not isinstance(data.get("imsOrgs"), list):
        raise TransportError("Workspace identity response is malformed")
    organizations = data["imsOrgs"]
    if any(
        not isinstance(org, dict) or not isinstance(org.get("imsOrgId"), str)
        for org in organizations
    ):
        raise TransportError("Workspace identity response is malformed")
    selected = [org for org in organizations if org["imsOrgId"] == org_id]
    if len(selected) != 1:
        raise InvalidSnapshotError("Workspace organization identity mismatch")
    companies = selected[0].get("companies")
    if not isinstance(companies, list) or any(
        not isinstance(c, dict) or not isinstance(c.get("globalCompanyId"), str) for c in companies
    ):
        raise TransportError("Workspace identity response is malformed")
    if sum(c["globalCompanyId"] == company_id for c in companies) != 1:
        raise InvalidSnapshotError("Workspace company identity mismatch")
    receipt = transport.get_json(transport.route_url("suite", instance_id), headers=headers)
    suite = receipt.data
    if not isinstance(suite, dict) or not isinstance(suite.get("rsid"), str):
        raise TransportError("Workspace identity response is malformed")
    if suite["rsid"] != instance_id:
        raise InvalidSnapshotError("Workspace report suite identity mismatch")
    return receipt
