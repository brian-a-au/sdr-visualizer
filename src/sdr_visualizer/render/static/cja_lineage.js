(() => { "use strict";
  const BATCH_SIZE = 100;
  const ROLE_DEFINITIONS = Object.freeze({
    event: "Event", profile: "Profile", lookup: "Lookup", summary: "Summary",
    other: "Other", unspecified: "Unspecified",
  });
  const ROLE_ORDER = ["event", "profile", "lookup", "summary"], KNOWN_ROLE_KEYS = new Set(ROLE_ORDER);
  const dataElement = document.getElementById("sdr-lineage-data");
  const stage = document.getElementById("lineage-stage");
  const search = document.getElementById("lineage-search");
  if (!dataElement || !stage || !search) return;

  const payload = JSON.parse(dataElement.textContent);
  const el = {
    results: document.getElementById("lineage-results"),
    status: document.getElementById("lineage-status"),
    details: document.getElementById("lineage-details"),
    heading: document.getElementById("lineage-selection-heading"),
    selectionId: document.getElementById("lineage-selection-id"),
    parent: document.getElementById("lineage-parent"),
    datasets: document.getElementById("lineage-datasets"),
    siblings: document.getElementById("lineage-siblings"),
    relationship: document.getElementById("lineage-relationship-details"),
    relationshipHeading: document.getElementById("lineage-relationship-heading"),
    relationshipId: document.getElementById("lineage-relationship-id"),
    relationshipSummary: document.getElementById("lineage-relationship-summary"),
    relationshipContext: document.getElementById("lineage-relationship-context"),
    relationshipMetadata: document.getElementById("lineage-relationship-metadata"),
    routeControls: document.getElementById("lineage-route-controls"),
    routeCopy: document.getElementById("lineage-route-copy"),
    clearRoute: document.getElementById("lineage-clear-route"),
    clearSelection: document.getElementById("lineage-clear-selection"),
    showOverview: document.getElementById("lineage-show-overview"),
    fullGraph: document.getElementById("lineage-full-graph"),
    cameraControls: document.getElementById("lineage-camera-controls"),
    zoomIn: document.getElementById("lineage-zoom-in"), zoomOut: document.getElementById("lineage-zoom-out"),
    resetCamera: document.getElementById("lineage-reset-camera"), flowPause: document.getElementById("lineage-flow-pause"),
    stageToolbar: document.getElementById("lineage-stage-toolbar"), stageKey: document.getElementById("lineage-stage-key"),
    keyDatasets: document.getElementById("lineage-key-datasets"), keyConnections: document.getElementById("lineage-key-connections"),
    keyDataViews: document.getElementById("lineage-key-data-views"), themeToggle: document.getElementById("lineage-theme-toggle"),
    motionCopy: document.getElementById("lineage-motion-copy"), roleLegend: document.getElementById("lineage-role-legend"),
    roleLegendItems: document.getElementById("lineage-role-legend-items"),
    roleCoverageCopy: document.getElementById("lineage-role-coverage-copy"),
    globalRoleFilters: document.getElementById("lineage-global-role-filters"),
  };
  const maps = {
    dataset: new Map(payload.entities.datasets.map((item) => [item.id, item])),
    connection: new Map(payload.entities.connections.map((item) => [item.id, item])),
    "data-view": new Map(payload.entities.data_views.map((item) => [item.id, item])),
    local: new Map(payload.geometry.local_by_connection.map((item) => [item.connection_id, item])),
    relationship: new Map(
      payload.edges
        .filter((item) => item.kind === "dataset-connection")
        .map((item) => [relationshipKey(item.source_id, item.target_id), item])
    ),
  };
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const darkMode = window.matchMedia("(prefers-color-scheme: dark)");
  const state = {
    selectedConnectionId: null, selectedDataViewId: null, activeDatasetId: null, paused: false,
    initiatingResult: null, initiatingDataset: null,
    resultLimit: BATCH_SIZE,
    datasetLimit: BATCH_SIZE,
    connectionViewLimit: BATCH_SIZE,
    datasetRoleFilter: "all",
    globalRoleFilter: "all",
    siblingLimit: BATCH_SIZE,
    siblingQuery: "",
    fullGraph: false, flowPaused: false,
    camera: null, initialCamera: null, activeCanvas: null, pointer: null,
    theme: darkMode.matches ? "dark" : "light",
    themeOverridden: false,
    ambientJourneyComparisons: 0,
  };

  document.documentElement.dataset.theme = state.theme;

  stage.dataset.preparedConnections = String(payload.geometry.local_by_connection.length);
  stage.dataset.fullGraphGated = String(payload.gating.full_graph_gated);

  function empty(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function addText(parent, tag, text, className) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text;
    parent.appendChild(node);
    return node;
  }

  function setStatus(text) {
    el.status.textContent = text;
  }

  function normalizeSearch(value) {
    return String(value)
      .normalize("NFKC")
      .toLowerCase()
      .replace(/\u00df/g, "ss");
  }

  function setFullGraph(active) {
    state.fullGraph = active;
    if (!active) state.flowPaused = false;
    el.fullGraph.setAttribute("aria-pressed", String(active));
  }

  function entityLabel(kind, id) {
    const item = maps[kind].get(id);
    return item ? item.name || item.display_name || item.id : id;
  }

  function selectedView() {
    return state.selectedDataViewId ? maps["data-view"].get(state.selectedDataViewId) : null;
  }

  function datasetIds(view) {
    return view && view.connection_id
      ? payload.adjacency.dataset_ids_by_connection[view.connection_id] || []
      : [];
  }

  function relationshipEdge(datasetId, connectionId) {
    return maps.relationship.get(relationshipKey(datasetId, connectionId));
  }

  function relationshipKey(datasetId, connectionId) {
    return `${datasetId}\u0000${connectionId}`;
  }

  function hasOwn(value, key) {
    return value !== null && typeof value === "object" && Object.prototype.hasOwnProperty.call(value, key);
  }

  function displayRole(value) {
    if (typeof value !== "string" || value.length === 0) return null;
    return ROLE_DEFINITIONS[value.toLowerCase()] || value;
  }

  function roleKey(value) {
    if (typeof value !== "string") return "unspecified";
    const normalized = value.toLowerCase();
    if (KNOWN_ROLE_KEYS.has(normalized)) return normalized;
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
      filterKey: KNOWN_ROLE_KEYS.has(styleKey) ? styleKey : `custom:${metadata.role}`,
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
    for (const key of ROLE_ORDER) {
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

  function orderedRoleEntries(counts, includeZeroStates = true) {
    const ordered = [];
    for (const key of ROLE_ORDER) {
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

  const roleIndex = buildRoleIndex();

  function connectionMatchesGlobalRole(connectionId) {
    if (state.globalRoleFilter === "all") return true;
    const membership = roleIndex.membership.get(state.globalRoleFilter);
    return Boolean(membership && membership.connection.has(connectionId));
  }

  function entityMatchesGlobalRole(kind, id) {
    if (state.globalRoleFilter === "all") return true;
    const membership = roleIndex.membership.get(state.globalRoleFilter);
    return Boolean(membership && membership[kind] && membership[kind].has(id));
  }

  function renderGlobalRoleCoverage() {
    const stats = roleIndex;
    el.roleCoverageCopy.textContent = `${stats.metadataRelationships} of ${stats.totalRelationships} dataset relationships include Connection metadata. ${stats.connectionsWithDatasets} of ${maps.connection.size} Connections have accessible backing datasets.`;
    empty(el.globalRoleFilters);
    const entries = [
      {
        key: "all",
        label: "All",
        styleKey: "unspecified",
        count: stats.totalRelationships,
      },
      ...orderedRoleEntries(stats.counts),
    ];
    for (const entry of entries) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "global-role-filter";
      if (entry.key !== "all" && entry.styleKey !== "unspecified") {
        button.classList.add(`relationship-role--${entry.styleKey}`);
      }
      button.dataset.globalRoleKey = entry.key;
      button.setAttribute("aria-pressed", String(state.globalRoleFilter === entry.key));
      button.textContent = `${entry.label} ${entry.count}`;
      if (entry.count === 0) {
        button.disabled = true;
        button.setAttribute("aria-disabled", "true");
      }
      button.addEventListener("click", () => {
        if (state.globalRoleFilter === entry.key) return;
        state.globalRoleFilter = entry.key;
        renderGlobalRoleCoverage();
        if (stage.dataset.state === "overview") renderConnectionOverview();
        else if (state.fullGraph) drawFullGraph();
        else if (selectedView()) renderLocalGraph();
        const replacement = Array.from(el.globalRoleFilters.querySelectorAll("button")).find(
          (candidate) => candidate.dataset.globalRoleKey === entry.key
        );
        if (replacement) replacement.focus();
        setStatus(entry.key === "all"
          ? "All Connection roles are visible."
          : `${entry.label} relationships are emphasized across the current lineage view.`);
      });
      el.globalRoleFilters.appendChild(button);
    }
  }

  function renderRoleLegend() {
    empty(el.roleLegendItems);
    const entries = Array.from(roleIndex.legendCounts.values()).sort((left, right) => {
      const leftIndex = ROLE_ORDER.indexOf(left.styleKey);
      const rightIndex = ROLE_ORDER.indexOf(right.styleKey);
      return (leftIndex < 0 ? ROLE_ORDER.length : leftIndex)
        - (rightIndex < 0 ? ROLE_ORDER.length : rightIndex)
        || left.label.localeCompare(right.label);
    });
    for (const { count, label, styleKey } of entries) {
      const item = document.createElement("li");
      item.className = `relationship-role--${styleKey}`;
      const swatch = document.createElement("span");
      swatch.className = "role-legend-swatch";
      swatch.setAttribute("aria-hidden", "true");
      item.append(swatch, document.createTextNode(`${label} ${count}`));
      el.roleLegendItems.appendChild(item);
    }
    el.roleLegend.hidden = el.roleLegendItems.childElementCount === 0;
  }

  function siblingIds(view) {
    return view && view.connection_id
      ? (payload.adjacency.data_view_ids_by_connection[view.connection_id] || []).filter(
          (id) => id !== view.id
        )
      : [];
  }

  function renderResults() {
    empty(el.results);
    const query = normalizeSearch(search.value.trim());
    if (!query) {
      addText(el.results, "p", "Enter a name or stable identifier to search the selected entity type.", "hint");
      return;
    }
    const kind = document.getElementById("lineage-search-kind").value;
    const matches = Array.from(maps[kind].values()).filter((item) =>
      normalizeSearch(item.search_text).includes(query)
    );
    const list = document.createElement("ul");
    list.className = "result-list";
    for (const item of matches.slice(0, state.resultLimit)) {
      const row = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      if (kind === "data-view") {
        button.dataset.dataViewId = item.id;
        button.setAttribute("aria-pressed", String(state.selectedDataViewId === item.id));
      } else if (kind === "connection") button.dataset.searchConnectionId = item.id;
      else button.dataset.searchDatasetId = item.id;
      addText(button, "span", entityLabel(kind, item.id), "result-name");
      addText(button, "span", item.id, "stable-id");
      button.addEventListener("click", () => {
        if (kind === "data-view") selectDataView(item.id, button);
        else if (kind === "connection") selectConnection(item.id);
        else inspectSearchDataset(item.id);
      });
      row.appendChild(button);
      list.appendChild(row);
    }
    el.results.appendChild(list);
    if (matches.length === 0) addText(el.results, "p", "No matching entities.", "hint");
    if (state.resultLimit < matches.length) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "load-more";
      button.textContent = `Show next ${Math.min(BATCH_SIZE, matches.length - state.resultLimit)} results`;
      button.addEventListener("click", () => {
        state.resultLimit += BATCH_SIZE;
        renderResults();
        const next = el.results.querySelector(".load-more");
        if (next) next.focus();
        else search.focus();
      });
      el.results.appendChild(button);
    }
    const shown = Math.min(matches.length, state.resultLimit);
    setStatus(`${matches.length} ${kind} ${matches.length === 1 ? "result" : "results"}; showing ${shown}. Current selection is preserved.`);
  }

  function inspectSearchDataset(id) {
    empty(el.results);
    const heading = addText(el.results, "h3", entityLabel("dataset", id));
    heading.tabIndex = -1;
    addText(el.results, "p", id, "stable-id");
    const connections = Array.from(maps.connection.values()).filter((connection) =>
      maps.relationship.has(relationshipKey(id, connection.id))
    );
    addText(el.results, "p", `${connections.length} accessible Connections use this dataset. Choose a Connection to inspect its Data Views and relationship metadata.`, "hint");
    const list = document.createElement("ul");
    list.className = "result-list";
    for (const connection of connections) {
      const row = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.searchConnectionId = connection.id;
      const views = payload.adjacency.data_view_ids_by_connection[connection.id] || [];
      addText(button, "span", `${entityLabel("connection", connection.id)} · ${views.length} Data Views`, "result-name");
      addText(button, "span", connection.id, "stable-id");
      button.addEventListener("click", () => selectConnection(connection.id));
      row.appendChild(button);
      list.appendChild(row);
    }
    el.results.appendChild(list);
    heading.focus();
    setStatus(`${entityLabel("dataset", id)}: ${connections.length} accessible Connections. Roles belong to individual dataset–Connection relationships.`);
  }

  function renderParent(view) {
    empty(el.parent);
    if (!view.connection_id) {
      addText(el.parent, "p", "Parent connection unavailable: no connection identifier was reported.", "availability availability--missing");
      return;
    }
    const connection = maps.connection.get(view.connection_id);
    if (!connection) {
      addText(el.parent, "p", "Parent connection unavailable: the reported identifier could not be resolved.", "availability availability--missing");
      addText(el.parent, "p", view.connection_id, "stable-id");
      return;
    }
    if (connection.detail_availability === "unavailable") {
      addText(el.parent, "p", "Connection name unavailable for this accessible parent.", "availability availability--unavailable");
    } else {
      addText(el.parent, "p", connection.display_name, "entity-name");
    }
    addText(el.parent, "p", connection.id, "stable-id");
  }

  function renderDatasets(view) {
    empty(el.datasets);
    if (view.dataset_availability === "unavailable") {
      addText(el.datasets, "p", "Backing datasets unavailable for this data view's parent connection.", "availability availability--unavailable");
      return;
    }
    const ids = datasetIds(view);
    if (view.dataset_availability === "reported-empty" || ids.length === 0) {
      addText(el.datasets, "p", "No backing datasets were reported for this connection.", "availability availability--empty");
      return;
    }
    const roleCounts = new Map();
    for (const id of ids) {
      const role = relationshipRole(id, view.connection_id);
      incrementRoleCount(roleCounts, role);
    }
    if (ids.length > 1) {
      const filter = document.createElement("div");
      filter.className = "dataset-role-filter ui";
      const label = document.createElement("label");
      label.setAttribute("for", "lineage-role-filter");
      label.textContent = "Connection role";
      const select = document.createElement("select");
      select.id = "lineage-role-filter";
      const options = [["all", `All roles (${ids.length})`]];
      const roleOptions = Array.from(roleCounts.entries()).sort((left, right) => {
        const leftIndex = ROLE_ORDER.indexOf(left[1].styleKey);
        const rightIndex = ROLE_ORDER.indexOf(right[1].styleKey);
        const leftRank = leftIndex < 0 ? ROLE_ORDER.length : leftIndex;
        const rightRank = rightIndex < 0 ? ROLE_ORDER.length : rightIndex;
        return leftRank - rightRank || left[1].label.localeCompare(right[1].label);
      });
      for (const [key, entry] of roleOptions) {
        options.push([key, `${entry.label} (${entry.count})`]);
      }
      for (const [value, text] of options) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = text;
        select.appendChild(option);
      }
      select.value = state.datasetRoleFilter;
      select.addEventListener("change", () => {
        state.datasetRoleFilter = select.value;
        state.datasetLimit = BATCH_SIZE;
        const activeRole = state.activeDatasetId
          ? relationshipRole(state.activeDatasetId, view.connection_id).filterKey
          : null;
        if (state.activeDatasetId && select.value !== "all" && activeRole !== select.value) {
          state.activeDatasetId = null;
          state.paused = false;
          state.initiatingDataset = null;
          setFullGraph(false);
        }
        renderDetails();
        renderLocalGraph();
        document.getElementById("lineage-role-filter").focus();
        const selectedRole = roleCounts.get(select.value);
        const shown = select.value === "all" ? ids.length : (selectedRole ? selectedRole.count : 0);
        setStatus(`${shown} of ${ids.length} backing datasets match ${select.value === "all" ? "all Connection roles" : selectedRole.label} for ${view.name}.`);
      });
      filter.append(label, select);
      el.datasets.appendChild(filter);
    }
    const filteredIds = state.datasetRoleFilter === "all"
      ? ids
      : ids.filter(
          (id) => relationshipRole(id, view.connection_id).filterKey === state.datasetRoleFilter
        );
    const selectedOutsideBatch =
      state.activeDatasetId &&
      filteredIds.includes(state.activeDatasetId) &&
      !filteredIds.slice(0, state.datasetLimit).includes(state.activeDatasetId);
    const visibleIds = selectedOutsideBatch
      ? [state.activeDatasetId, ...filteredIds.filter((id) => id !== state.activeDatasetId)].slice(
          0,
          state.datasetLimit
        )
      : filteredIds.slice(0, state.datasetLimit);
    addText(
      el.datasets,
      "p",
      state.datasetRoleFilter === "all"
        ? `${ids.length} backing ${ids.length === 1 ? "dataset" : "datasets"}; showing ${visibleIds.length}. Select one to trace its lineage route.`
        : `${filteredIds.length} of ${ids.length} backing datasets match ${roleCounts.get(state.datasetRoleFilter).label}; showing ${visibleIds.length}. Select one to trace its lineage route.`,
      "detail-summary"
    );
    const list = document.createElement("ul");
    list.className = "entity-list dataset-list";
    for (const id of visibleIds) {
      const item = maps.dataset.get(id);
      if (!item) continue;
      const row = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.datasetId = id;
      button.setAttribute("aria-pressed", String(state.activeDatasetId === id));
      const role = relationshipRole(id, view.connection_id);
      button.setAttribute(
        "aria-label",
        `Trace dataset ${item.name}, stable identifier ${item.id}${role.label ? `, CJA Connection role ${role.label}` : ""}`
      );
      addText(button, "span", item.name, "entity-name");
      if (role.label) addText(button, "span", `${role.label} role`, `relationship-role relationship-role--${role.styleKey}`);
      addText(button, "span", item.id, "stable-id");
      button.addEventListener("click", () => selectRoute(id, button));
      row.appendChild(button);
      list.appendChild(row);
    }
    el.datasets.appendChild(list);
    if (state.datasetLimit < filteredIds.length) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "load-more";
      button.textContent = `Show next ${Math.min(BATCH_SIZE, filteredIds.length - state.datasetLimit)} datasets`;
      button.setAttribute(
        "aria-label",
        state.datasetRoleFilter === "all"
          ? `Show next ${Math.min(BATCH_SIZE, filteredIds.length - state.datasetLimit)} of ${filteredIds.length} backing datasets`
          : `Show next ${Math.min(BATCH_SIZE, filteredIds.length - state.datasetLimit)} of ${filteredIds.length} matching backing datasets`
      );
      button.addEventListener("click", () => {
        state.datasetLimit += BATCH_SIZE;
        renderDatasets(view);
        const next = el.datasets.querySelector(".load-more");
        if (next) next.focus();
        else {
          el.datasets.tabIndex = -1;
          el.datasets.focus();
        }
        setStatus(
          `${Math.min(filteredIds.length, state.datasetLimit)} of ${filteredIds.length} matching backing datasets are shown for ${view.name}.`
        );
      });
      el.datasets.appendChild(button);
    }
  }

  function renderSiblingResults(view, results) {
    const ids = siblingIds(view);
    empty(results);
    const query = normalizeSearch(state.siblingQuery.trim());
    const filteredIds = query
      ? ids.filter((id) => {
          const item = maps["data-view"].get(id);
          return item && normalizeSearch(item.search_text).includes(query);
        })
      : ids;
    addText(
      results,
      "p",
      `${filteredIds.length} of ${ids.length} siblings match the current filter.`,
      "detail-summary"
    );
    const list = document.createElement("ul");
    list.className = "entity-list sibling-list";
    for (const id of filteredIds.slice(0, state.siblingLimit)) {
      const item = maps["data-view"].get(id);
      if (!item) continue;
      const row = document.createElement("li");
      addText(row, "span", item.name, "entity-name");
      addText(row, "span", item.id, "stable-id");
      list.appendChild(row);
    }
    results.appendChild(list);
    if (state.siblingLimit < filteredIds.length) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "load-more";
      button.textContent = `Show next ${Math.min(BATCH_SIZE, filteredIds.length - state.siblingLimit)} siblings`;
      button.addEventListener("click", () => {
        state.siblingLimit += BATCH_SIZE;
        renderSiblingResults(view, results);
        const next = results.querySelector(".load-more");
        if (next) next.focus();
        else {
          results.tabIndex = -1;
          results.focus();
        }
      });
      results.appendChild(button);
    }
  }

  function renderSiblings(view) {
    empty(el.siblings);
    const ids = siblingIds(view);
    addText(el.siblings, "p", `${ids.length} sibling data ${ids.length === 1 ? "view" : "views"} share this connection.`, "detail-summary");
    if (ids.length === 0) return;

    const label = document.createElement("label");
    label.setAttribute("for", "lineage-sibling-filter");
    label.textContent = "Filter sibling data views";
    const filter = document.createElement("input");
    filter.id = "lineage-sibling-filter";
    filter.type = "search";
    filter.className = "sibling-filter";
    filter.autocomplete = "off";
    filter.value = state.siblingQuery;
    const results = document.createElement("div");
    results.id = "lineage-sibling-results";
    results.setAttribute("role", "region");
    results.setAttribute("aria-label", "Filtered sibling data views");
    filter.setAttribute("aria-controls", results.id);
    filter.addEventListener("input", () => {
      state.siblingQuery = filter.value;
      state.siblingLimit = BATCH_SIZE;
      renderSiblingResults(view, results);
    });
    el.siblings.append(label, filter, results);
    renderSiblingResults(view, results);
  }

  function renderRouteControls(view) {
    if (!state.activeDatasetId) {
      el.routeControls.hidden = true;
      return;
    }
    el.routeControls.hidden = false;
    const dataset = maps.dataset.get(state.activeDatasetId);
    const connection = maps.connection.get(view.connection_id);
    el.routeCopy.textContent = `Selected route: ${dataset.name} → ${connection ? connection.display_name : view.connection_id} → ${view.name}. Static edge emphasis is authoritative; marker timing has no operational meaning.`;
  }

  function reportedAt(value, path) {
    let current = value;
    for (const key of path) {
      if (!hasOwn(current, key)) return { present: false, value: undefined };
      current = current[key];
    }
    return { present: true, value: current };
  }

  function formatReported(value) {
    if (value === null) return "Reported null";
    if (value === true) return "True";
    if (value === false) return "False";
    if (value === "") return "Reported empty string";
    if (Array.isArray(value)) return value.length ? value.join(", ") : "Reported empty list";
    if (typeof value === "object") return Object.keys(value).length ? JSON.stringify(value) : "Reported empty object";
    return String(value);
  }

  function appendMetadataGroup(parent, title, value, fields) {
    const card = document.createElement("section");
    card.className = "metadata-card";
    addText(card, "h5", title);
    if (value === null || (typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0)) {
      const message = value === null
        ? formatReported(value)
        : "Reported object has no recognized fields.";
      addText(card, "p", message, "metadata-empty");
      parent.appendChild(card);
      return;
    }
    const list = document.createElement("dl");
    for (const [label, path, transform, groupStateOnly] of fields) {
      const reported = reportedAt(value, path);
      if (!reported.present) continue;
      if (
        groupStateOnly &&
        reported.value !== null &&
        !(typeof reported.value === "object" &&
          !Array.isArray(reported.value) &&
          Object.keys(reported.value).length === 0)
      ) continue;
      addText(list, "dt", label);
      const shown = transform && reported.value !== null ? transform(reported.value) : reported.value;
      addText(list, "dd", formatReported(shown));
    }
    if (list.childElementCount === 0) {
      addText(card, "p", "Reported object has no recognized fields.", "metadata-empty");
    }
    else card.appendChild(list);
    parent.appendChild(card);
  }

  function addSummaryChip(text) {
    addText(el.relationshipSummary, "span", text, "relationship-summary-chip");
  }

  function renderRelationshipSummary(metadata) {
    empty(el.relationshipSummary);
    if (!metadata || typeof metadata !== "object") return;
    if (hasOwn(metadata, "role")) {
      const role = displayRole(metadata.role);
      addSummaryChip(`${role || formatReported(metadata.role)} role`);
    }
    const schemaName = reportedAt(metadata, ["schema", "name"]);
    const schemaId = reportedAt(metadata, ["schema", "id"]);
    if (schemaName.present || schemaId.present) {
      addSummaryChip(`Schema: ${formatReported(schemaName.present ? schemaName.value : schemaId.value)}`);
    }
    const namespace = reportedAt(metadata, ["identity", "namespace"]);
    const visitorId = reportedAt(metadata, ["identity", "visitorId"]);
    if (namespace.present || visitorId.present) {
      addSummaryChip(`Identity: ${formatReported(namespace.present ? namespace.value : visitorId.value)}`);
    }
    const lookupKey = reportedAt(metadata, ["lookup", "keyField"]);
    if (lookupKey.present) addSummaryChip(`Lookup key: ${formatReported(lookupKey.value)}`);
    const streaming = reportedAt(metadata, ["ingestion", "streaming"]);
    if (streaming.present) addSummaryChip(`Streaming: ${formatReported(streaming.value)}`);
    const completed = reportedAt(metadata, ["ingestion", "backfillSummary", "completed"]);
    const total = reportedAt(metadata, ["ingestion", "backfillSummary", "total"]);
    if (completed.present && total.present) {
      addSummaryChip(`Backfill: ${formatReported(completed.value)} of ${formatReported(total.value)} completed`);
    }
    const sourceType = reportedAt(metadata, ["dataSource", "type"]);
    const sourceId = reportedAt(metadata, ["dataSource", "id"]);
    if (sourceType.present || sourceId.present) {
      addSummaryChip(`Source: ${formatReported(sourceType.present ? sourceType.value : sourceId.value)}`);
    }
  }

  function renderRelationshipContext(view, metadata) {
    el.relationshipContext.hidden = true;
    el.relationshipContext.textContent = "";
    if (!metadata || typeof metadata !== "object") return;
    const parent = reportedAt(metadata, ["lookup", "parentDatasetId"]);
    if (!parent.present || typeof parent.value !== "string" || !parent.value) return;
    const dataset = maps.dataset.get(parent.value);
    const parentLabel = dataset ? `${dataset.name} (${parent.value})` : parent.value;
    const accessibleHere = datasetIds(view).includes(parent.value);
    el.relationshipContext.textContent = `Lookup parent: ${parentLabel}. ${accessibleHere ? "It is present in this Connection's accessible backing set." : "It is not in this Connection's accessible backing set."}`;
    el.relationshipContext.hidden = false;
  }

  function renderRelationshipMetadata(view) {
    if (!state.activeDatasetId || !view.connection_id) {
      el.relationship.hidden = true;
      empty(el.relationshipSummary);
      el.relationshipContext.hidden = true;
      empty(el.relationshipMetadata);
      return;
    }
    const dataset = maps.dataset.get(state.activeDatasetId);
    const connection = maps.connection.get(view.connection_id);
    const edge = relationshipEdge(state.activeDatasetId, view.connection_id);
    el.relationship.hidden = false;
    el.relationshipHeading.textContent = `${dataset.name} → ${connection ? connection.display_name : view.connection_id}`;
    el.relationshipId.textContent = `${state.activeDatasetId} → ${view.connection_id}`;
    empty(el.relationshipMetadata);
    if (!edge || !hasOwn(edge, "connection_metadata")) {
      renderRelationshipSummary(null);
      renderRelationshipContext(view, null);
      addText(el.relationshipMetadata, "p", "No connection-scoped dataset metadata was reported for this relationship.", "availability availability--unavailable");
      return;
    }
    const metadata = edge.connection_metadata;
    renderRelationshipSummary(metadata);
    renderRelationshipContext(view, metadata);
    if (metadata === null || Object.keys(metadata).length === 0) {
      const message = metadata === null
        ? formatReported(metadata)
        : "Reported connection metadata object has no recognized fields.";
      addText(el.relationshipMetadata, "p", message, "availability availability--empty");
      return;
    }
    if (hasOwn(metadata, "role")) {
      appendMetadataGroup(el.relationshipMetadata, "Connection role", { role: metadata.role }, [
        ["Reported role", ["role"], (value) => displayRole(value) ?? value],
      ]);
    }
    if (hasOwn(metadata, "schema")) {
      appendMetadataGroup(el.relationshipMetadata, "Schema", metadata.schema, [
        ["Schema ID", ["id"]], ["Schema name", ["name"]], ["Reference ID", ["ref", "id"]],
        ["Reference content type", ["ref", "contentType"]],
        ["Schema reference", ["ref"], null, true],
      ]);
    }
    if (hasOwn(metadata, "identity")) {
      appendMetadataGroup(el.relationshipMetadata, "Identity configuration", metadata.identity, [
        ["Timestamp field", ["timestampId"]], ["Visitor ID field", ["visitorId"]],
        ["Namespace", ["namespace"]], ["Use primary ID namespace", ["usePrimaryIdNamespace"]],
        ["Identity map", ["identityMap"]], ["Namespace column", ["namespaceColumn"]],
      ]);
    }
    if (hasOwn(metadata, "lookup")) {
      appendMetadataGroup(el.relationshipMetadata, "Lookup configuration", metadata.lookup, [
        ["Key field", ["keyField"]], ["Parent fields", ["parentFields"]],
        ["Parent dataset ID", ["parentDatasetId"]], ["Parent dataset type", ["parentDatasetType"]],
      ]);
    }
    if (hasOwn(metadata, "ingestion")) {
      appendMetadataGroup(el.relationshipMetadata, "Ingestion observations", metadata.ingestion, [
        ["Streaming", ["streaming"]], ["Backfills total", ["backfillSummary", "total"]],
        ["Backfills failed", ["backfillSummary", "failed"]],
        ["Backfills in progress", ["backfillSummary", "inProgress"]],
        ["Backfills completed", ["backfillSummary", "completed"]],
        ["Backfill summary invalid", ["backfillSummary", "invalid"]],
        ["Backfill summary", ["backfillSummary"], null, true],
        ["Last ingested", ["lastIngestedTime"]], ["Streaming enabled at", ["streamingEnabledAt"]],
      ]);
    }
    if (hasOwn(metadata, "dataSource")) {
      appendMetadataGroup(el.relationshipMetadata, "Data source", metadata.dataSource, [
        ["Source ID", ["id"]], ["Type", ["type"]], ["Description", ["description"]],
      ]);
    }
  }

  function renderDetails() {
    const view = selectedView();
    if (!view) {
      el.details.hidden = true;
      return;
    }
    el.details.hidden = false;
    document.getElementById("lineage-back-connection").hidden = !maps.connection.has(view.connection_id);
    el.heading.textContent = view.name;
    el.selectionId.textContent = view.id;
    renderParent(view);
    renderDatasets(view);
    renderSiblings(view);
    renderRelationshipMetadata(view);
    renderRouteControls(view);
  }

  function parentSummary(view) {
    if (!view.connection_id) return "Parent connection unavailable.";
    const connection = maps.connection.get(view.connection_id);
    if (!connection) return `Parent connection ${view.connection_id} unavailable.`;
    if (connection.detail_availability === "unavailable") return `Parent connection name unavailable; stable identifier ${connection.id}.`;
    return `Parent connection ${connection.display_name}, ${connection.id}.`;
  }

  function datasetSummary(view, ids) {
    if (view.dataset_availability === "unavailable") return "Backing datasets unavailable.";
    if (view.dataset_availability === "reported-empty" || ids.length === 0) return "No backing datasets were reported.";
    return `${ids.length} backing datasets.`;
  }

  function selectDataView(id, control) {
    const nextView = maps["data-view"].get(id);
    state.selectedDataViewId = id;
    if (nextView && nextView.connection_id) state.selectedConnectionId = nextView.connection_id;
    state.activeDatasetId = null;
    state.paused = false;
    state.initiatingResult = control;
    state.initiatingDataset = null;
    state.datasetLimit = BATCH_SIZE;
    state.datasetRoleFilter = "all";
    state.siblingLimit = BATCH_SIZE;
    state.siblingQuery = "";
    setFullGraph(false);
    el.showOverview.setAttribute("aria-pressed", "false");
    renderResults();
    renderDetails();
    renderLocalGraph();
    const view = selectedView();
    setStatus(`${view.name}, ${view.id}, selected. ${parentSummary(view)} ${datasetSummary(view, datasetIds(view))} ${siblingIds(view).length} sibling data views.`);
  }

  function selectRoute(id, control) {
    state.activeDatasetId = id;
    state.paused = false;
    state.initiatingDataset = control;
    setFullGraph(false);
    renderDetails();
    renderLocalGraph();
    setStatus(`${reducedMotion.matches ? "Static route selected" : "Lineage trace selected"}: ${entityLabel("dataset", id)} to ${selectedView().name}.`);
  }

  function clearRoute(restoreFocus) {
    const datasetId = state.activeDatasetId;
    const focusTarget = state.initiatingDataset;
    state.activeDatasetId = null;
    state.paused = false;
    state.initiatingDataset = null;
    setFullGraph(false);
    renderDetails();
    renderLocalGraph();
    const view = selectedView();
    if (view) setStatus(`${view.name} remains selected. No dataset route is selected.`);
    if (!restoreFocus) return;
    if (focusTarget && focusTarget.isConnected) {
      focusTarget.focus();
      return;
    }
    const replacement = Array.from(el.datasets.querySelectorAll("button")).find(
      (button) => button.dataset.datasetId === datasetId
    );
    if (replacement) {
      replacement.focus();
      return;
    }
    const filter = document.getElementById("lineage-role-filter");
    if (filter) {
      filter.focus();
      return;
    }
    el.datasets.tabIndex = -1;
    el.datasets.focus();
  }

  function clearSelection(restoreFocus) {
    const selectedId = state.selectedDataViewId;
    const focusTarget = state.initiatingResult;
    state.selectedDataViewId = null;
    state.activeDatasetId = null;
    state.paused = false;
    state.initiatingResult = null;
    state.initiatingDataset = null;
    state.datasetLimit = BATCH_SIZE;
    state.siblingLimit = BATCH_SIZE;
    state.siblingQuery = "";
    setFullGraph(false);
    renderResults();
    renderDetails();
    renderConnectionOverview();
    setStatus("Selection cleared. Static overview; no data view is selected.");
    if (!restoreFocus) return;
    if (focusTarget && focusTarget.isConnected) {
      focusTarget.focus();
      return;
    }
    const replacement = Array.from(el.results.querySelectorAll("button")).find(
      (button) => button.dataset.dataViewId === selectedId
    );
    if (replacement) {
      replacement.focus();
      return;
    }
    const connection = state.selectedConnectionId
      ? stage.querySelector(`[data-connection-id="${CSS.escape(state.selectedConnectionId)}"]`)
      : null;
    (connection || search).focus();
  }

  function connectionRoleBand(connectionId) {
    const roles = roleIndex.connectionEntries.get(connectionId) || [];
    if (roles.length === 0) return null;
    const band = document.createElement("span");
    band.className = "connection-overview-role-band";
    band.setAttribute("role", "img");
    band.setAttribute(
      "aria-label",
      `Role mix: ${roles.map((role) => `${role.label} ${role.count}`).join(", ")}`
    );
    for (const role of roles) {
      const segment = document.createElement("span");
      segment.className = "connection-overview-role-segment";
      if (role.styleKey !== "unspecified") {
        segment.classList.add(`relationship-role--${role.styleKey}`);
      }
      segment.style.flexGrow = String(role.count);
      segment.setAttribute("aria-hidden", "true");
      band.appendChild(segment);
    }
    return band;
  }

  function appendConnectionRoles(parent, connectionId) {
    const roles = document.createElement("div");
    roles.className = "connection-overview-roles";
    for (const role of roleIndex.connectionEntries.get(connectionId) || []) {
      const chip = addText(
        roles,
        "span",
        `${role.label} ${role.count}`,
        "connection-overview-role"
      );
      if (role.styleKey !== "unspecified") {
        chip.classList.add(`relationship-role--${role.styleKey}`);
      }
    }
    if (roles.childElementCount === 0) {
      const connection = maps.connection.get(connectionId);
      const message = connection && connection.dataset_availability === "reported-empty"
        ? "No backing datasets reported" : "Dataset details unavailable";
      addText(roles, "span", message, "connection-overview-counts");
    }
    parent.appendChild(roles);
  }

  function clearConnectionSelection(restoreFocus) {
    const connectionId = state.selectedConnectionId;
    state.selectedConnectionId = null;
    state.connectionViewLimit = BATCH_SIZE;
    renderConnectionOverview();
    setStatus("Connection details closed. Choose another Connection or search for a Data View.");
    if (!restoreFocus || !connectionId) return;
    const replacement = stage.querySelector(
      `[data-connection-id="${CSS.escape(connectionId)}"]`
    );
    if (replacement) replacement.focus();
  }

  function selectConnection(connectionId) {
    if (selectedView()) clearSelection(false);
    if (!connectionMatchesGlobalRole(connectionId)) {
      state.globalRoleFilter = "all";
      renderGlobalRoleCoverage();
    }
    if (state.selectedConnectionId !== connectionId) state.connectionViewLimit = BATCH_SIZE;
    state.selectedConnectionId = connectionId;
    renderConnectionOverview();
    const heading = document.getElementById("lineage-connection-inspector-heading");
    if (heading) heading.focus();
    const connection = maps.connection.get(connectionId);
    const views = payload.adjacency.data_view_ids_by_connection[connectionId] || [];
    setStatus(`${connection ? connection.display_name || connection.id : connectionId} selected. Choose one of ${views.length} accessible data ${views.length === 1 ? "view" : "views"} to draw its bounded lineage neighborhood.`);
  }

  function renderConnectionInspector(connection) {
    const datasets = payload.adjacency.dataset_ids_by_connection[connection.id] || [];
    const views = payload.adjacency.data_view_ids_by_connection[connection.id] || [];
    const inspector = document.createElement("aside");
    inspector.id = "lineage-connection-inspector";
    inspector.className = "connection-inspector";
    inspector.setAttribute("aria-labelledby", "lineage-connection-inspector-heading");

    const header = document.createElement("div");
    header.className = "connection-inspector-header";
    const heading = document.createElement("div");
    addText(heading, "p", "Selected Connection", "eyebrow");
    const title = addText(
      heading,
      "h4",
      connection.display_name || connection.id,
      "connection-inspector-heading"
    );
    title.id = "lineage-connection-inspector-heading";
    title.tabIndex = -1;
    addText(heading, "p", connection.id, "stable-id");
    const close = document.createElement("button");
    close.type = "button";
    close.className = "connection-inspector-close";
    close.textContent = "Close details";
    close.addEventListener("click", () => clearConnectionSelection(true));
    header.append(heading, close);
    inspector.appendChild(header);

    addText(
      inspector,
      "p",
      `${datasets.length} backing ${datasets.length === 1 ? "dataset" : "datasets"}; ${views.length} accessible data ${views.length === 1 ? "view" : "views"}.`,
      "connection-inspector-summary"
    );
    const band = connectionRoleBand(connection.id);
    if (band) inspector.appendChild(band);
    appendConnectionRoles(inspector, connection.id);

    const viewsHeading = addText(
      inspector,
      "h5",
      "Choose a Data View",
      "connection-inspector-views-heading"
    );
    viewsHeading.id = "lineage-connection-inspector-views-heading";
    const list = document.createElement("ul");
    list.className = "connection-inspector-views";
    list.setAttribute("aria-labelledby", viewsHeading.id);
    for (const id of views.slice(0, state.connectionViewLimit)) {
      const view = maps["data-view"].get(id);
      if (!view) continue;
      const row = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.dataViewId = id;
      button.setAttribute(
        "aria-label",
        `Inspect Data View ${view.name}, stable identifier ${view.id}`
      );
      addText(button, "span", view.name, "connection-inspector-view-name");
      addText(button, "span", view.id, "stable-id");
      button.addEventListener("click", () => selectDataView(id, button));
      row.appendChild(button);
      list.appendChild(row);
    }
    if (list.childElementCount === 0) {
      addText(
        inspector,
        "p",
        "No accessible Data Views were reported for this Connection.",
        "availability availability--empty"
      );
    } else {
      addText(
        inspector,
        "p",
        `${views.length} accessible data ${views.length === 1 ? "view" : "views"}; showing ${Math.min(views.length, state.connectionViewLimit)}.`,
        "detail-summary"
      );
      inspector.appendChild(list);
      if (state.connectionViewLimit < views.length) {
        const more = document.createElement("button");
        more.type = "button";
        more.className = "load-more";
        more.textContent = `Show next ${Math.min(BATCH_SIZE, views.length - state.connectionViewLimit)} Data Views`;
        more.addEventListener("click", () => {
          state.connectionViewLimit += BATCH_SIZE;
          renderConnectionOverview();
          const next = document.querySelector("#lineage-connection-inspector .load-more");
          const heading = document.getElementById("lineage-connection-inspector-heading");
          (next || heading).focus();
        });
        inspector.appendChild(more);
      }
    }
    return inspector;
  }

  function renderConnectionOverview() {
    setFullGraph(false);
    empty(stage);
    clearDiagramControls();
    stage.dataset.state = "overview";
    el.showOverview.setAttribute("aria-pressed", "true");
    const connections = Array.from(maps.connection.values());
    const visible = connections.filter((connection) => connectionMatchesGlobalRole(connection.id));
    if (
      state.selectedConnectionId &&
      !visible.some((connection) => connection.id === state.selectedConnectionId)
    ) {
      state.selectedConnectionId = null;
    }
    const overview = document.createElement("section");
    overview.className = "connection-overview";
    overview.setAttribute("aria-labelledby", "lineage-connection-overview-heading");
    const header = document.createElement("div");
    header.className = "connection-overview-header";
    const heading = document.createElement("div");
    addText(heading, "p", "Accessible scope", "eyebrow");
    const title = addText(heading, "h3", "Connection overview");
    title.id = "lineage-connection-overview-heading";
    const filterEntry = state.globalRoleFilter === "all"
      ? null
      : roleIndex.counts.get(state.globalRoleFilter);
    const summary = addText(
      header,
      "p",
      filterEntry
        ? `${visible.length} of ${connections.length} Connections shown for ${filterEntry.label}.`
        : `${visible.length} of ${connections.length} Connections shown.`
    );
    summary.id = "lineage-connection-overview-summary";
    header.prepend(heading);
    const body = document.createElement("div");
    body.className = "connection-overview-body";
    const grid = document.createElement("div");
    grid.className = "connection-overview-grid";
    for (const connection of visible) {
      const datasets = payload.adjacency.dataset_ids_by_connection[connection.id] || [];
      const views = payload.adjacency.data_view_ids_by_connection[connection.id] || [];
      const card = document.createElement("button");
      card.type = "button";
      card.className = "connection-overview-card";
      card.dataset.connectionId = connection.id;
      card.setAttribute("aria-pressed", String(state.selectedConnectionId === connection.id));
      card.setAttribute("aria-controls", "lineage-connection-inspector");
      card.title = connection.display_name || connection.id;
      card.setAttribute(
        "aria-label",
        `Select Connection ${connection.display_name || connection.id}: ${datasets.length} backing datasets and ${views.length} accessible data views`
      );
      addText(card, "span", connection.display_name || connection.id, "connection-overview-name");
      addText(card, "span", connection.id, "stable-id connection-overview-id");
      addText(
        card,
        "span",
        `${datasets.length} backing ${datasets.length === 1 ? "dataset" : "datasets"}; ${views.length} data ${views.length === 1 ? "view" : "views"}`,
        "connection-overview-counts"
      );
      const band = connectionRoleBand(connection.id);
      if (band) card.appendChild(band);
      appendConnectionRoles(card, connection.id);
      if (state.selectedConnectionId === connection.id) {
        addText(card, "span", "Selected", "connection-overview-selected");
      }
      card.addEventListener("click", () => selectConnection(connection.id));
      grid.appendChild(card);
    }
    if (visible.length === 0) {
      addText(grid, "p", "No accessible Connections match this role state.", "overview-state");
    }
    body.appendChild(grid);
    if (state.selectedConnectionId) {
      const connection = maps.connection.get(state.selectedConnectionId);
      if (connection) {
        body.classList.add("has-selection");
        body.appendChild(renderConnectionInspector(connection));
      }
    }
    overview.append(header, body);
    stage.appendChild(overview);
  }

  function isRouteEdge(edge, view) {
    if (!state.activeDatasetId || !view.connection_id) return false;
    return (
      (edge.source_ref === `dataset:${state.activeDatasetId}` && edge.target_ref === `connection:${view.connection_id}`) ||
      (edge.source_ref === `connection:${view.connection_id}` && edge.target_ref === `data-view:${view.id}`)
    );
  }

  const {
    applyCamera,
    clearDiagramControls,
    clearPan,
    drawFullGraph,
    panCamera,
    renderLocalGraph,
    stageDimensions,
    zoomCamera,
  } = window.SdrCjaLineageGraph.create({
    addText,
    empty,
    el,
    entityMatchesGlobalRole,
    entityLabel,
    isRouteEdge,
    maps,
    payload,
    reducedMotion,
    relationshipRole,
    renderRouteControls,
    selectedView,
    setFullGraph,
    setStatus,
    stage,
    state,
  });

  document.getElementById("lineage-search-kind").addEventListener("change", () => {
    state.resultLimit = BATCH_SIZE;
    renderResults();
  });
  document.getElementById("lineage-back-connection").addEventListener("click", () => {
    const view = selectedView();
    if (view && view.connection_id) selectConnection(view.connection_id);
  });
  search.addEventListener("input", () => {
    state.resultLimit = BATCH_SIZE;
    renderResults();
  });
  el.clearSelection.addEventListener("click", () => clearSelection(true));
  el.clearRoute.addEventListener("click", () => clearRoute(true));
  el.showOverview.addEventListener("click", () => {
    if (selectedView()) clearSelection(false);
    else renderConnectionOverview();
    setStatus("Aggregated Connection overview shown. Choose a Connection, then choose a Data View, or search for a specific Data View.");
    el.showOverview.focus();
  });
  el.fullGraph.addEventListener("click", drawFullGraph);
  el.zoomIn.addEventListener("click", () => {
    zoomCamera(0.75);
    setStatus("Diagram zoomed in. Node labels remain available in full on hover and to assistive technology.");
  });
  el.zoomOut.addEventListener("click", () => {
    zoomCamera(4 / 3);
    setStatus("Diagram zoomed out.");
  });
  el.resetCamera.addEventListener("click", () => {
    if (!state.initialCamera) return;
    state.camera = { ...state.initialCamera };
    applyCamera();
    stage.focus();
    setStatus("Diagram view reset to its readable starting position.");
  });
  el.flowPause.addEventListener("click", () => {
    const svg = stage.querySelector("svg");
    if (!svg || reducedMotion.matches) return;
    if (state.fullGraph) state.flowPaused = !state.flowPaused;
    else state.paused = !state.paused;
    const paused = state.fullGraph ? state.flowPaused : state.paused;
    if (paused) svg.pauseAnimations();
    else svg.unpauseAnimations();
    stage.classList.toggle("is-flow-paused", paused);
    el.flowPause.setAttribute("aria-pressed", String(paused));
    el.flowPause.textContent = paused ? "Resume flow" : "Pause flow";
    setStatus(paused
      ? "Lineage motion paused; static highlighted routes remain visible."
      : "Lineage motion resumed; motion indicates lineage direction only.");
  });
  el.themeToggle.addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    state.themeOverridden = true;
    document.documentElement.dataset.theme = state.theme;
    el.themeToggle.setAttribute("aria-pressed", String(state.theme === "dark"));
    el.themeToggle.textContent = state.theme === "dark" ? "Light mode" : "Dark mode";
    setStatus(`${state.theme === "dark" ? "Dark" : "Light"} display mode enabled; the ${document.documentElement.dataset.colorPack} color pack remains active.`);
  });
  stage.addEventListener("pointerdown", (event) => {
    if (!state.camera || event.button !== 0) return;
    state.pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, camera: { ...state.camera } };
    stage.classList.add("is-panning");
    stage.setPointerCapture(event.pointerId);
  });
  stage.addEventListener("pointermove", (event) => {
    if (!state.pointer || state.pointer.id !== event.pointerId || !state.camera) return;
    const dimensions = stageDimensions();
    state.camera.x = state.pointer.camera.x - (event.clientX - state.pointer.x) * state.pointer.camera.width / dimensions.width;
    state.camera.y = state.pointer.camera.y - (event.clientY - state.pointer.y) * state.pointer.camera.height / dimensions.height;
    applyCamera();
  });
  const endPan = (event) => {
    if (!state.pointer || state.pointer.id !== event.pointerId) return;
    clearPan();
  };
  stage.addEventListener("pointerup", endPan);
  stage.addEventListener("pointercancel", endPan);
  document.addEventListener("keydown", (event) => {
    if (document.activeElement === stage && state.camera) {
      const cameraKeys = {
        ArrowLeft: [-0.12, 0],
        ArrowRight: [0.12, 0],
        ArrowUp: [0, -0.12],
        ArrowDown: [0, 0.12],
      };
      if (cameraKeys[event.key]) {
        event.preventDefault();
        panCamera(...cameraKeys[event.key]);
        return;
      }
      if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        zoomCamera(0.75);
        return;
      }
      if (event.key === "-" || event.key === "_") {
        event.preventDefault();
        zoomCamera(4 / 3);
        return;
      }
      if (event.key === "0" && state.initialCamera) {
        event.preventDefault();
        state.camera = { ...state.initialCamera };
        applyCamera();
        return;
      }
    }
    if (event.key !== "Escape") return;
    if (state.activeDatasetId) {
      event.preventDefault();
      clearRoute(true);
    } else if (state.selectedDataViewId) {
      event.preventDefault();
      clearSelection(true);
    } else if (state.selectedConnectionId) {
      event.preventDefault();
      clearConnectionSelection(true);
    }
  });
  const motionChanged = () => {
    clearPan();
    state.paused = false;
    if (state.fullGraph) {
      drawFullGraph();
      setStatus(reducedMotion.matches
        ? "Reduced motion enabled; representative journeys remain statically highlighted."
        : "Reduced motion disabled; representative journey motion is available and may be paused.");
      return;
    }
    if (!state.activeDatasetId) return;
    renderDetails();
    renderLocalGraph();
    setStatus(reducedMotion.matches ? "Static route selected; the moving marker is omitted by reduced-motion preference." : "Lineage trace marker available; static selected route remains authoritative.");
  };
  if (reducedMotion.addEventListener) reducedMotion.addEventListener("change", motionChanged);
  else reducedMotion.addListener(motionChanged);
  const colorSchemeChanged = () => {
    if (state.themeOverridden) return;
    state.theme = darkMode.matches ? "dark" : "light";
    document.documentElement.dataset.theme = state.theme;
    el.themeToggle.setAttribute("aria-pressed", String(state.theme === "dark"));
    el.themeToggle.textContent = state.theme === "dark" ? "Light mode" : "Dark mode";
  };
  if (darkMode.addEventListener) darkMode.addEventListener("change", colorSchemeChanged);
  else darkMode.addListener(colorSchemeChanged);
  colorSchemeChanged();

  renderRoleLegend();
  renderGlobalRoleCoverage();
  renderResults();
  if (payload.counts.connections) renderConnectionOverview();
  window.__cjaLineagePoc = Object.freeze({
    getState: () => ({
      selectedConnectionId: state.selectedConnectionId,
      selectedDataViewId: state.selectedDataViewId, activeDatasetId: state.activeDatasetId,
      datasetRoleFilter: state.datasetRoleFilter,
      globalRoleFilter: state.globalRoleFilter,
      paused: state.paused,
      fullGraph: state.fullGraph,
      svgCount: stage.querySelectorAll("svg").length,
      svgNodeCount: stage.querySelectorAll(".lineage-node").length,
      svgEdgeCount: stage.querySelectorAll(".lineage-edge").length,
      markerCount: stage.querySelectorAll(".route-marker").length,
      journeyCount: stage.querySelectorAll(".journey-guide").length,
      cometCount: stage.querySelectorAll(".journey-comet").length,
      flowPaused: state.flowPaused,
      theme: state.theme,
      camera: state.camera ? { ...state.camera } : null,
      ambientJourneyComparisons: state.ambientJourneyComparisons,
    }),
  });
})();
