"""Pinned AA matcher, independently characterized from CJA."""


def prepare(projects, deny):
    from aanalytics2 import Analytics
    from aanalytics2.projects import Project

    client = object.__new__(Analytics)
    client.loggingEnabled = False
    client.segments = []
    client.calculatedMetrics = []
    client.projectsDetails = {}
    client.connector = deny
    client.getSegments = client.getCalculatedMetrics = client.getAllProjectDetails = deny
    parsed, excluded = [], False
    for project in projects:
        try:
            item = Project(project, rsidSuffix=False)
            item.to_dict()
            if item.reportType != "desktop":
                excluded = True
                continue
            parsed.append(item)
        except Exception:
            excluded = True
    return client, parsed, excluded


def find(client, projects, component):
    return client.findComponentsUsage(
        components=[component["id"]],
        projectDetails=projects,
        segments=[],
        calculatedMetrics=[],
        recursive=False,
        regexUsed=False,
        verbose=False,
        resetProjectDetails=False,
        rsidSuffix=False,
    )
