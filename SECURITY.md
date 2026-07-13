# Security policy

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Report privately via GitHub security advisories:
https://github.com/brian-a-au/sdr-visualizer/security/advisories/new

Do not open a public issue for a vulnerability. You should hear back within
a week.

## Threat model notes

The generated report is a static HTML file that embeds snapshot data.
Snapshot text is treated as hostile: `<` is emitted as the JSON escape
`\u003c` in the embedded payload, template values are Jinja-autoescaped,
and the client escapes every payload-derived string it interpolates. Two stored-XSS classes were found and fixed before 0.3.0;
reports that bypass this escaping are exactly what this policy is for.
The report makes no network requests, so exfiltration requires a separate
delivery channel — but script execution in a viewer's browser is still a
real impact.
