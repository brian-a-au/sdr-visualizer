"""CJA identity verification before Workspace traversal."""

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.usage.transport import TransportError


def verify_identity(transport, headers, instance_id, org_id, company_id):
    receipt = transport.get_json(transport.route_url("dataview", instance_id), headers=headers)
    data = receipt.data
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        raise TransportError("Workspace identity response is malformed")
    if data["id"] != instance_id:
        raise InvalidSnapshotError("Workspace data view identity mismatch")
    return receipt
