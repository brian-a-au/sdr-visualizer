"""Optional Workspace collection; importing this package performs no authentication."""


def collect_workspace_usage(
    snapshot,
    *,
    source="<unknown>",
    platform=None,
    organization_context,
    company_context=None,
    config_path=None,
    scope="all",
    project_ids=None,
    components=None,
):
    """Collect JSON-ready evidence for a parsed snapshot using the selected SDK.

    This explicit opt-in performs bounded API collection. Pass its returned
    mapping to ``visualize(..., workspace_usage=..., organization_context=...)``
    for offline rendering, or save it as JSON for CLI replay.
    """
    from sdr_visualizer.core.visualizer import build_implementation
    from sdr_visualizer.usage.collector import collect_workspace_usage as collect

    implementation = build_implementation(snapshot, source=source, platform=platform)
    return collect(
        implementation,
        organization_context=organization_context,
        company_context=company_context,
        config_path=config_path,
        scope=scope,
        project_ids=project_ids,
        components=components,
    ).evidence
