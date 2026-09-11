(() => {
  "use strict";

  const ROLE_DEFINITIONS = Object.freeze({
    event: "Event", profile: "Profile", lookup: "Lookup", summary: "Summary",
    other: "Other", unspecified: "Unspecified",
  });

  function create(context) {
    const { hasOwn, maps, relationshipEdge, roleOrder } = context;
    const knownRoleKeys = new Set(roleOrder);

    function displayRole(value) {
      if (typeof value !== "string" || value.length === 0) return null;
      const key = value.toLowerCase();
      return hasOwn(ROLE_DEFINITIONS, key) ? ROLE_DEFINITIONS[key] : value;
    }

    function roleKey(value) {
      if (typeof value !== "string") return "unspecified";
      const normalized = value.toLowerCase();
      if (knownRoleKeys.has(normalized)) return normalized;
      return "other";
    }

    function relationshipRole(datasetId, connectionId) {
      const edge = relationshipEdge(datasetId, connectionId);
      const metadata = edge && edge.connection_metadata;
      if (!metadata || !hasOwn(metadata, "role")) {
        return {
          filterKey: "missing",
          filterLabel: "Not reported",
          styleKey: "unspecified",
          label: null,
        };
      }
      if (metadata.role === null) {
        return {
          filterKey: "null",
          filterLabel: "Reported null",
          styleKey: "unspecified",
          label: null,
        };
      }
      if (metadata.role === "") {
        return {
          filterKey: "empty",
          filterLabel: "Reported empty string",
          styleKey: "unspecified",
          label: null,
        };
      }
      const label = displayRole(metadata.role);
      const styleKey = roleKey(metadata.role);
      return {
        filterKey: knownRoleKeys.has(styleKey) ? styleKey : `custom:${metadata.role}`,
        filterLabel: label,
        styleKey,
        label,
      };
    }

    function incrementRoleCount(counts, role) {
      const entry = counts.get(role.filterKey) || {
        key: role.filterKey,
        label: role.filterLabel,
        styleKey: role.styleKey,
        count: 0,
      };
      entry.count += 1;
      counts.set(role.filterKey, entry);
    }

    function orderedRoleEntries(counts, includeZeroStates = true) {
      const ordered = [];
      for (const key of roleOrder) {
        const entry = counts.get(key);
        if (entry && (entry.count || includeZeroStates)) ordered.push(entry);
      }
      const custom = Array.from(counts.values())
        .filter((entry) => entry.styleKey === "other")
        .sort((left, right) => left.label.localeCompare(right.label));
      ordered.push(...custom);
      for (const key of ["missing", "null", "empty"]) {
        const entry = counts.get(key);
        if (entry && (entry.count || includeZeroStates)) ordered.push(entry);
      }
      return ordered;
    }

    function buildRoleIndex() {
      const counts = new Map();
      const legendCounts = new Map();
      const membership = new Map();
      const connectionCounts = new Map();
      let metadataRelationships = 0;
      const connectionsWithDatasets = new Set();
      for (const edge of maps.relationship.values()) {
        if (hasOwn(edge, "connection_metadata")) metadataRelationships += 1;
        connectionsWithDatasets.add(edge.target_id);
        const role = relationshipRole(edge.source_id, edge.target_id);
        incrementRoleCount(counts, role);
        if (role.label) incrementRoleCount(legendCounts, role);
        const roleMembership = membership.get(role.filterKey) || {
          dataset: new Set(),
          connection: new Set(),
          "data-view": new Set(),
        };
        roleMembership.dataset.add(edge.source_id);
        roleMembership.connection.add(edge.target_id);
        membership.set(role.filterKey, roleMembership);
        const rolesForConnection = connectionCounts.get(edge.target_id) || new Map();
        incrementRoleCount(rolesForConnection, role);
        connectionCounts.set(edge.target_id, rolesForConnection);
      }
      for (const key of roleOrder) {
        if (!counts.has(key)) {
          counts.set(key, { key, label: ROLE_DEFINITIONS[key], styleKey: key, count: 0 });
        }
      }
      for (const [key, label] of [
        ["missing", "Not reported"],
        ["null", "Reported null"],
        ["empty", "Reported empty string"],
      ]) {
        if (!counts.has(key)) {
          counts.set(key, { key, label, styleKey: "unspecified", count: 0 });
        }
      }
      for (const view of maps["data-view"].values()) {
        const rolesForConnection = connectionCounts.get(view.connection_id);
        if (!rolesForConnection) continue;
        for (const roleKey of rolesForConnection.keys()) {
          const roleMembership = membership.get(roleKey);
          if (roleMembership) roleMembership["data-view"].add(view.id);
        }
      }
      return Object.freeze({
        counts,
        legendCounts,
        membership,
        connectionEntries: new Map(
          Array.from(connectionCounts, ([connectionId, roleCounts]) => [
            connectionId,
            orderedRoleEntries(roleCounts, false),
          ])
        ),
        metadataRelationships,
        connectionsWithDatasets: connectionsWithDatasets.size,
        totalRelationships: maps.relationship.size,
      });
    }

    return Object.freeze({
      displayRole,
      incrementRoleCount,
      orderedRoleEntries,
      relationshipRole,
      roleIndex: buildRoleIndex(),
    });
  }

  window.SdrCjaLineageRoles = Object.freeze({ create });
})();
