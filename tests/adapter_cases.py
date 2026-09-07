"""Synthetic adapter regressions; no customer data."""


def aa_case():
    return {
        "report_suite": {"rsid": "synthetic"},
        "dimensions": [{"id": "variables/page"}],
        "metrics": [
            {"id": "metrics/" + name} for name in ("revenue", "visitors", "orders", "documentation")
        ],
        "segments": [
            {
                "id": "segments/page",
                "definition": {
                    "func": "streq",
                    "val": {"func": "attr", "name": "variables/page"},
                    "str": "metrics/documentation",
                },
            }
        ],
        "calculated_metrics": [
            {
                "id": "calc/ratio",
                "definition": {
                    "formula": {
                        "func": "divide",
                        "col1": {"func": "metric", "name": "metrics/revenue"},
                        "col2": {"func": "metric", "name": "metrics/visitors"},
                    }
                },
            }
        ],
    }


def cja_case():
    return {
        "metadata": {"Data View ID": "synthetic"},
        "metrics": [],
        "dimensions": [{"id": "variables/channel"}],
        "segments": {
            "segments": [
                {
                    "segment_id": "segments/channel",
                    "dimension_references": ["dimensions/channel"],
                    "definition_json": {
                        "func": "streq",
                        "val": {"func": "attr", "name": "dimensions/channel"},
                        "str": "organic",
                    },
                }
            ]
        },
    }
