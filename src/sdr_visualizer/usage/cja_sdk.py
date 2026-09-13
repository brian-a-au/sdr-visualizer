"""Pinned CJA matcher; imported only inside the credential-free worker."""


def prepare(projects, deny):
    from cjapy import CJA
    from cjapy.projects import Project

    client = object.__new__(CJA)
    client.loggingEnabled = False
    client.filters = []
    client.calculatedMetrics = []
    client.projectsDetails = {}
    client.connector = deny
    client.getFilters = client.getCalculatedMetrics = client.getAllProjectDetails = deny
    parsed, excluded = [], False
    for project in projects:
        try:
            item = Project(project, dvIdSuffix=False)
            item.to_dict()  # Force shape errors per project, before the helper's generator.
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
        filters=[],
        calculatedMetrics=[],
        recursive=False,
        regexUsed=False,
        resetProjectDetails=False,
        dvIdSuffix=False,
    )
