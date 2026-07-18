/* sdr-visualizer client-side logic.
 *
 * Reads the embedded JSON payload, drives catalog rendering, search,
 * filtering, sorting, and the detail panel. No framework, no fetches,
 * no external state.
 */
(function () {
  "use strict";

  var dataNode = document.getElementById("sdr-data");
  if (!dataNode) {
    console.error("sdr-visualizer: payload script element missing");
    return;
  }
  var payload;
  try {
    payload = JSON.parse(dataNode.textContent);
  } catch (e) {
    console.error("sdr-visualizer: payload is not valid JSON", e);
    return;
  }

  /* ----- Build a flat catalog list ----- */

  var catalog = [];
  payload.components.forEach(function (c) { catalog.push(c); });
  payload.segments.forEach(function (s) { catalog.push(s); });
  payload.calculated_metrics.forEach(function (c) { catalog.push(c); });

  // Map id -> entry for O(1) lookup (used by detail panel reference links).
  // Precompute per-entry search/sort keys in the same pass: one O(n) walk at
  // load is cheaper than shipping a server-built index (which duplicated
  // name/description/formula text in the payload) and far cheaper than
  // recomputing per keystroke.
  var byId = {};
  catalog.forEach(function (entry) {
    byId[entry.id] = entry;
    entry._search = [
      entry.id || "",
      entry.name || "",
      entry.description || "",
      entry.formula_text || "",
      (entry.tags || []).join(" "),
    ].join(" ").toLowerCase();
    entry._sortName = (entry.name || "").toLowerCase();
  });

  /* ----- DOM refs ----- */

  var $body = document.getElementById("catalog-body");
  var $empty = document.getElementById("catalog-empty");
  var $resultCount = document.getElementById("result-count");
  var $search = document.getElementById("search-input");
  var $typeFilter = document.getElementById("type-filter");
  var $descriptionFilter = document.getElementById("description-filter");
  var $referencesFilter = document.getElementById("references-filter");
  var $modifiedFilter = document.getElementById("modified-filter");
  var $detailPanel = document.getElementById("detail-panel");
  var $detailOverlay = document.getElementById("detail-overlay");
  var $detailBody = document.getElementById("detail-body");
  var $detailClose = document.getElementById("detail-close");
  var $headers = document.querySelectorAll(".catalog-table th.sortable");

  /* ----- State ----- */

  var sortKey = "type";
  var sortDir = "asc";
  // Always sort by name as a secondary key for stable ordering.
  // Master list kept in sorted order; re-sorted only when the sort key or
  // direction changes. applyFilters() filters it without re-sorting.
  var sortedCatalog = catalog.slice();
  var lastFiltered = [];
  // Cap rendered rows — innerHTML parse + layout cost grows linearly and
  // blows the §6 filter budget past a few thousand rows. "Show all" opts out.
  var ROW_RENDER_CAP = 1000;

  /* ----- Shareable URL state (#q=...&types=...) -----
   * Catalog filters, sort, active view, and open detail entry live in
   * location.hash so a filtered view can be shared as a link. Restored
   * once at load; not a hashchange listener (back/forward not in scope).
   */

  var activeView = "catalog";
  var openDetailId = null;

  function updateHash() {
    var params = new URLSearchParams();
    var q = ($search.value || "").trim();
    if (q) params.set("q", q);
    var types = selectedTypes();
    if (types.length !== $typeFilter.querySelectorAll("input").length) params.set("types", types.join(","));
    if ($descriptionFilter.value !== "all") params.set("desc", $descriptionFilter.value);
    if ($referencesFilter.value !== REFS_DEFAULT) params.set("refs", $referencesFilter.value);
    if ($modifiedFilter.value !== "all") params.set("mod", $modifiedFilter.value);
    if (sortKey !== "type" || sortDir !== "asc") {
      params.set("sort", sortKey);
      params.set("dir", sortDir);
    }
    if (activeView !== "catalog") params.set("view", activeView);
    if (openDetailId) params.set("detail", openDetailId);
    var encoded = params.toString();
    try {
      history.replaceState(null, "", encoded ? "#" + encoded : location.pathname + location.search);
    } catch (e) {
      /* file:// in some browsers disallows replaceState; sharing just won't work there.
         Safari also rate-throttles replaceState, so the hash may lag during very rapid
         typing and self-corrects on pause. */
    }
  }

  function setSelectIfValid(select, value) {
    if (!value) return;
    for (var i = 0; i < select.options.length; i++) {
      if (select.options[i].value === value) {
        select.value = value;
        return;
      }
    }
  }

  function restoreFromHash() {
    if (!location.hash || location.hash.length < 2) return null;
    var params = new URLSearchParams(location.hash.slice(1));
    if (params.get("q")) $search.value = params.get("q");
    var typesParam = params.get("types");
    if (typesParam !== null) {
      var wanted = {};
      var validCount = 0;
      typesParam.split(",").forEach(function (t) {
        if (Object.prototype.hasOwnProperty.call(KNOWN_TYPES, t)) { wanted[t] = true; validCount++; }
      });
      // Apply when at least one token is valid, or when the param is the
      // explicit empty state ("types=", every type unchecked). All-garbage
      // tokens still fall back to the default all-checked state.
      if (validCount > 0 || typesParam === "") {
        $typeFilter.querySelectorAll("input").forEach(function (input) {
          input.checked = !!wanted[input.value];
        });
      }
    }
    setSelectIfValid($descriptionFilter, params.get("desc"));
    setSelectIfValid($referencesFilter, params.get("refs"));
    setSelectIfValid($modifiedFilter, params.get("mod"));
    var VALID_SORT_KEYS = { name: true, type: true, in_degree: true, modified_at: true };
    var sortParam = params.get("sort");
    if (sortParam && Object.prototype.hasOwnProperty.call(VALID_SORT_KEYS, sortParam)) {
      sortKey = sortParam;
      sortDir = params.get("dir") === "desc" ? "desc" : "asc";
    }
    return params;
  }

  // Honor --exclude-orphans by defaulting the references-filter dropdown.
  if (payload.meta && payload.meta.exclude_orphans_default) {
    var refSelect = document.getElementById("references-filter");
    if (refSelect) refSelect.value = "referenced";
  }

  // The references dropdown's at-rest value depends on a build flag
  // (--exclude-orphans). Only encode refs into the hash when the user
  // diverges from THIS build's default, so shared URLs don't impose one
  // build's default onto another's.
  var REFS_DEFAULT = (payload.meta && payload.meta.exclude_orphans_default) ? "referenced" : "all";

  // Allowed type tokens for URL restore, derived from the rendered
  // checkboxes so the template stays the single source of truth.
  var KNOWN_TYPES = {};
  $typeFilter.querySelectorAll("input").forEach(function (input) {
    KNOWN_TYPES[input.value] = true;
  });

  /* ----- Helpers ----- */

  function escapeHtml(value) {
    if (value == null) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatTypeLabel(type, derivedKind) {
    switch (type) {
      case "metric": return "Metric";
      case "dimension": return "Dimension";
      case "derived_field":
        if (derivedKind === "dimension") return "Derived dimension";
        if (derivedKind === "metric") return "Derived metric";
        return "Derived field";
      case "segment": return "Segment";
      case "calculated_metric": return "Calc metric";
      default: return type;
    }
  }

  function formatDate(value) {
    if (!value) return "—";
    // The display is date-only and server timestamps lead with the date
    // ("YYYY-MM-DD..." — ISO or the cja_auto_sdr space shape), so take the
    // prefix directly. Date-parsing naive strings is engine-dependent:
    // Safari rejects the space shape outright, and Chrome reads it as LOCAL
    // time while the server-computed modified_ts assumed UTC — the shown
    // date could disagree with the modified filter by a day.
    var m = /^(\d{4}-\d{2}-\d{2})/.exec(String(value));
    if (m) return m[1];
    var date = new Date(value);
    if (isNaN(date.getTime())) return value;
    var y = date.getUTCFullYear();
    var mo = String(date.getUTCMonth() + 1).padStart(2, "0");
    var d = String(date.getUTCDate()).padStart(2, "0");
    return y + "-" + mo + "-" + d;
  }

  function tagsOf(entry) {
    return entry.tags || [];
  }

  /* ----- Filtering ----- */

  function selectedTypes() {
    var checked = $typeFilter.querySelectorAll("input:checked");
    var out = [];
    for (var i = 0; i < checked.length; i++) out.push(checked[i].value);
    return out;
  }

  function applyFilters() {
    var query = ($search.value || "").trim().toLowerCase();
    var types = selectedTypes();
    var typeSet = {};
    types.forEach(function (t) { typeSet[t] = true; });
    var descriptionMode = $descriptionFilter.value;
    var referencesMode = $referencesFilter.value;
    var modifiedMode = $modifiedFilter.value;
    var modifiedDays = modifiedMode === "all" ? Infinity : Number(modifiedMode);
    var nowMs = Date.now();

    var filtered = sortedCatalog.filter(function (entry) {
      var typeMatches = typeSet[entry.type] || (entry.derived_kind && typeSet[entry.derived_kind]);
      if (!typeMatches) return false;

      if (query && entry._search.indexOf(query) === -1) return false;

      if (descriptionMode === "has" && !entry.description) return false;
      if (descriptionMode === "missing" && entry.description) return false;

      if (referencesMode === "referenced" && !((entry.in_degree || 0) > 0)) return false;
      if (referencesMode === "orphaned" && (entry.in_degree || 0) > 0) return false;

      if (modifiedDays !== Infinity) {
        if (!entry.modified_ts) return false;
        if ((nowMs - entry.modified_ts) / 86400000 > modifiedDays) return false;
      }

      return true;
    });

    lastFiltered = filtered;
    updateHash();
    renderRows(filtered, false);
  }

  function resort() {
    sortedCatalog.sort(compareEntries);
  }

  function compareEntries(a, b) {
    var primary = compareByKey(a, b, sortKey);
    if (primary !== 0) return sortDir === "desc" ? -primary : primary;
    if (sortKey !== "name") return compareByKey(a, b, "name");
    return 0;
  }

  function compareByKey(a, b, key) {
    var av = a[key];
    var bv = b[key];
    if (key === "in_degree") {
      av = av || 0;
      bv = bv || 0;
      return av - bv;
    }
    if (key === "modified_at") {
      return (a.modified_ts || 0) - (b.modified_ts || 0);
    }
    if (key === "name") {
      av = a._sortName;
      bv = b._sortName;
    } else {
      av = (av || "").toString().toLowerCase();
      bv = (bv || "").toString().toLowerCase();
    }
    if (av < bv) return -1;
    if (av > bv) return 1;
    return 0;
  }

  /* ----- Rendering ----- */

  function renderRows(entries, showAll) {
    var truncated = !showAll && entries.length > ROW_RENDER_CAP;
    var visible = truncated ? entries.slice(0, ROW_RENDER_CAP) : entries;
    var html = visible.map(rowHtml).join("");
    if (truncated) {
      html += '<tr class="catalog-truncated"><td colspan="7">Showing ' +
        ROW_RENDER_CAP + " of " + entries.length +
        ' rows · <button type="button" id="show-all-rows" class="ghost-button ui">Show all</button></td></tr>';
    }
    $body.innerHTML = html;
    $empty.hidden = entries.length > 0;
    $resultCount.textContent = entries.length === catalog.length
      ? entries.length + " components"
      : entries.length + " of " + catalog.length;
    updateHeaderSortIndicators();
  }

  function rowHtml(entry) {
    // Row HTML is a pure function of the entry — build once, reuse on every
    // subsequent filter/sort render.
    if (entry._rowHtml === undefined) entry._rowHtml = buildRowHtml(entry);
    return entry._rowHtml;
  }

  function buildRowHtml(entry) {
    var allTags = tagsOf(entry);
    var tags = allTags.slice(0, 4).map(function (t) {
      return '<span class="tag">' + escapeHtml(t) + "</span>";
    }).join("");
    if (allTags.length > 4) {
      tags += '<span class="tag">+' + (allTags.length - 4) + "</span>";
    }
    var desc = entry.description;
    var descHtml = desc
      ? escapeHtml(desc)
      : (entry.formula_text
          ? '<span class="mono">' + escapeHtml(entry.formula_text) + "</span>"
          : '<span class="is-missing-marker">(no description)</span>');
    var descClass = desc || entry.formula_text ? "col-description" : "col-description is-missing";
    var refs = entry.in_degree || 0;
    return (
      '<tr data-id="' + escapeHtml(entry.id) + '">' +
        '<td class="col-name">' +
          '<div class="row-name-cell">' +
            '<span>' + escapeHtml(entry.name) + "</span>" +
          "</div>" +
          '<span class="row-id mono">' + escapeHtml(entry.id) + "</span>" +
        "</td>" +
        '<td class="col-type"><span class="dot dot-' + escapeHtml(entry.type) + '"></span>' + escapeHtml(formatTypeLabel(entry.type, entry.derived_kind)) + "</td>" +
        '<td class="' + descClass + '">' + descHtml + "</td>" +
        '<td class="col-tags">' + tags + "</td>" +
        '<td class="col-refs num' + (refs === 0 ? " zero" : "") + '">' + refs + "</td>" +
        '<td class="col-modified">' + escapeHtml(formatDate(entry.modified_at)) + "</td>" +
        '<td class="col-owner">' + escapeHtml(entry.owner || "—") + "</td>" +
      "</tr>"
    );
  }

  function updateHeaderSortIndicators() {
    $headers.forEach(function (th) {
      th.classList.remove("is-sorted", "is-desc");
      if (th.getAttribute("data-sort") === sortKey) {
        th.classList.add("is-sorted");
        if (sortDir === "desc") th.classList.add("is-desc");
      }
    });
  }

  /* ----- Detail panel ----- */

  function openDetail(id) {
    var entry = byId[id];
    if (!entry) return;
    openDetailId = id;
    updateHash();
    $detailBody.innerHTML = detailHtml(entry);
    $detailPanel.classList.add("is-open");
    $detailPanel.setAttribute("aria-hidden", "false");
    $detailOverlay.classList.add("is-open");
    $detailOverlay.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function closeDetail() {
    openDetailId = null;
    updateHash();
    $detailPanel.classList.remove("is-open");
    $detailPanel.setAttribute("aria-hidden", "true");
    $detailOverlay.classList.remove("is-open");
    $detailOverlay.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  function detailHtml(entry) {
    var typeColor = '<span class="dot dot-' + escapeHtml(entry.type) + '"></span>';
    var pieces = [
      '<div class="detail-eyebrow">' + typeColor + escapeHtml(formatTypeLabel(entry.type, entry.derived_kind)) + "</div>",
      '<h2 class="detail-name">' + escapeHtml(entry.name) + "</h2>",
      '<div class="detail-id mono">' + escapeHtml(entry.id) + "</div>",
    ];

    if (entry.description) {
      pieces.push('<div class="detail-section"><h3>Description</h3><p class="detail-description">' + escapeHtml(entry.description) + "</p></div>");
    } else {
      pieces.push('<div class="detail-section"><h3>Description</h3><p class="detail-description is-missing">No description.</p></div>');
    }

    if (entry.type === "calculated_metric") {
      if (entry.formula_text) {
        pieces.push('<div class="detail-section"><h3>Formula</h3><div class="formula-block">' + escapeHtml(entry.formula_text) + "</div></div>");
      }
      var formulaTree = (payload.formula_trees || {})[entry.id];
      if (formulaTree) {
        pieces.push('<div class="detail-section"><h3>Anatomy</h3><div class="formula-tree">' + renderFormulaTree(formulaTree) + "</div></div>");
      }
      var calcMeta = '<dl class="detail-grid">';
      calcMeta += "<dt>Attribution</dt><dd>" + escapeHtml(entry.attribution_model || "—") + "</dd>";
      calcMeta += "<dt>Allocation</dt><dd>" + escapeHtml(entry.allocation || "—") + "</dd>";
      if (typeof entry.complexity_score === "number") {
        calcMeta += "<dt>Complexity</dt><dd>" + entry.complexity_score + "</dd>";
      }
      calcMeta += "</dl>";
      pieces.push('<div class="detail-section"><h3>Properties</h3>' + calcMeta + "</div>");
    } else if (entry.type === "segment") {
      var segMeta = '<dl class="detail-grid">';
      segMeta += "<dt>Nesting depth</dt><dd>" + (entry.nesting_depth || 0) + "</dd>";
      segMeta += "<dt>Containers</dt><dd>" + escapeHtml((entry.container_types || []).join(", ") || "—") + "</dd>";
      segMeta += "</dl>";
      pieces.push('<div class="detail-section"><h3>Properties</h3>' + segMeta + "</div>");

      var segTree = (payload.segment_trees || {})[entry.id];
      if (segTree) {
        pieces.push('<div class="detail-section"><h3>Anatomy</h3><div class="anatomy">' + renderSegmentTree(segTree) + "</div></div>");
      }
    } else {
      var compMeta = '<dl class="detail-grid">';
      compMeta += "<dt>Type</dt><dd>" + escapeHtml(formatTypeLabel(entry.type, entry.derived_kind)) + "</dd>";
      compMeta += "<dt>Data type</dt><dd>" + escapeHtml(entry.data_type || "—") + "</dd>";
      if (entry.polarity) compMeta += "<dt>Polarity</dt><dd>" + escapeHtml(entry.polarity) + "</dd>";
      compMeta += "</dl>";
      pieces.push('<div class="detail-section"><h3>Properties</h3>' + compMeta + "</div>");
    }

    var meta = '<dl class="detail-grid">';
    meta += "<dt>References in</dt><dd>" + (entry.in_degree || 0) + "</dd>";
    meta += "<dt>References out</dt><dd>" + (entry.out_degree || 0) + "</dd>";
    meta += "<dt>Owner</dt><dd>" + escapeHtml(entry.owner || "—") + "</dd>";
    meta += "<dt>Modified</dt><dd>" + escapeHtml(formatDate(entry.modified_at)) + "</dd>";
    meta += "<dt>Created</dt><dd>" + escapeHtml(formatDate(entry.created_at)) + "</dd>";
    if (tagsOf(entry).length) {
      meta += "<dt>Tags</dt><dd>" + tagsOf(entry).map(function (t) {
        return '<span class="tag">' + escapeHtml(t) + "</span>";
      }).join(" ") + "</dd>";
    }
    meta += "</dl>";
    pieces.push('<div class="detail-section"><h3>Catalog</h3>' + meta + "</div>");

    var refs = entry.references || [];
    if (refs.length) {
      var listed = refs.map(function (r) {
        var label = byId[r] ? byId[r].name + " · " + r : r;
        var resolvable = !!byId[r];
        return "<li>" + (resolvable
          ? '<button type="button" class="ref-link" data-id="' + escapeHtml(r) + '">' + escapeHtml(label) + "</button>"
          : '<span class="ref-dangling mono">' + escapeHtml(r) + " (not in inventory)</span>") + "</li>";
      }).join("");
      pieces.push('<div class="detail-section"><h3>References</h3><ul class="detail-references">' + listed + "</ul></div>");
    }

    return pieces.join("");
  }

  /* ----- Anatomy renderers (segment + formula trees) ----- */

  function renderSegmentTree(node) {
    if (!node || typeof node !== "object") return "";
    switch (node.kind) {
      case "container": {
        var ctx = node.context || "";
        var inner = node.child ? renderSegmentTree(node.child) : "";
        return (
          '<div class="anatomy-container" data-context="' + escapeHtml(ctx) + '">' +
            '<div class="anatomy-label">' + escapeHtml(ctx) + "</div>" +
            inner +
          "</div>"
        );
      }
      case "logical": {
        var op = node.op || "and";
        var children = (node.children || []).map(renderSegmentTree).join("");
        return (
          '<div class="anatomy-logical">' +
            '<span class="anatomy-logical-op anatomy-op-' + escapeHtml(op) + '">' + escapeHtml(op) + "</span>" +
            '<div class="anatomy-children">' + children + "</div>" +
          "</div>"
        );
      }
      case "criterion": {
        var target = node.target_label || "value";
        var opLabel = node.op || "";
        var value = node.value !== undefined && node.value !== null ? JSON.stringify(node.value) : "";
        return (
          '<div class="anatomy-criterion">' +
            '<span class="criterion-target">' + escapeHtml(target) + "</span>" +
            '<span class="criterion-op">' + escapeHtml(opLabel) + "</span>" +
            (value ? '<span class="criterion-value">' + escapeHtml(value) + "</span>" : "") +
          "</div>"
        );
      }
      case "segment_ref": {
        var sid = node.segment_id || "";
        var resolvable = !!byId[sid];
        return (
          '<div class="anatomy-segment-ref">' +
            (resolvable
              ? '<button type="button" class="ref-link" data-id="' + escapeHtml(sid) + '">' + escapeHtml(sid) + "</button>"
              : '<span class="ref-dangling">' + escapeHtml(sid) + " (not in inventory)</span>") +
          "</div>"
        );
      }
      case "unknown":
      default:
        return '<div class="anatomy-unknown">' +
          (node.func ? "Unrecognized: " + escapeHtml(node.func) : "Unrecognized expression") +
          "</div>";
    }
  }

  function renderFormulaTree(node) {
    if (!node || typeof node !== "object") return "";
    switch (node.kind) {
      case "operation": {
        var op = node.op || "?";
        var args = (node.args || []).map(renderFormulaTree).join("");
        return (
          '<div class="formula-op">' +
            '<span class="formula-op-name">' + escapeHtml(op) + "</span>" +
          "</div>" +
          '<div class="formula-args">' + args + "</div>"
        );
      }
      case "metric_ref": {
        var mid = node.metric_id || "";
        var label = node.label || mid;
        var resolvable = !!byId[mid];
        return (
          '<div class="formula-metric-ref">' +
            (resolvable
              ? '<button type="button" class="ref-link" data-id="' + escapeHtml(mid) + '">' + escapeHtml(label) + "</button>"
              : '<button type="button" class="is-dangling" disabled>' + escapeHtml(label) + " (not in inventory)</button>") +
          "</div>"
        );
      }
      case "constant": {
        return '<div class="formula-constant">' + escapeHtml(JSON.stringify(node.value)) + "</div>";
      }
      case "segment_scope": {
        var sid = node.segment_id || "";
        var inner = node.child ? renderFormulaTree(node.child) : "";
        return (
          '<div class="formula-segment-scope">' +
            "scoped to " + escapeHtml(sid) +
          "</div>" + inner
        );
      }
      case "unknown":
      default:
        return '<div class="anatomy-unknown">' +
          (node.func ? "Unrecognized: " + escapeHtml(node.func) : "Unrecognized expression") +
          "</div>";
    }
  }

  /* ----- Wiring ----- */

  // Shared by the catalog and graph search boxes — the two are documented
  // as matching, so the value lives in one place.
  var SEARCH_DEBOUNCE_MS = 120;

  var searchDebounceTimer = null;
  $search.addEventListener("input", function () {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(applyFilters, SEARCH_DEBOUNCE_MS);
  });
  $typeFilter.addEventListener("change", applyFilters);
  $descriptionFilter.addEventListener("change", applyFilters);
  $referencesFilter.addEventListener("change", applyFilters);
  $modifiedFilter.addEventListener("change", applyFilters);

  $headers.forEach(function (th) {
    th.addEventListener("click", function () {
      var key = th.getAttribute("data-sort");
      if (sortKey === key) {
        sortDir = sortDir === "asc" ? "desc" : "asc";
      } else {
        sortKey = key;
        sortDir = key === "in_degree" || key === "modified_at" ? "desc" : "asc";
      }
      resort();
      applyFilters();
    });
  });

  $body.addEventListener("click", function (event) {
    if (event.target.closest("#show-all-rows")) {
      renderRows(lastFiltered, true);
      return;
    }
    var row = event.target.closest("tr[data-id]");
    if (row) openDetail(row.getAttribute("data-id"));
  });

  $detailClose.addEventListener("click", closeDetail);
  $detailOverlay.addEventListener("click", closeDetail);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeDetail();
  });

  $detailBody.addEventListener("click", function (event) {
    var btn = event.target.closest("button.ref-link");
    if (btn) openDetail(btn.getAttribute("data-id"));
  });

  var initialHashParams = restoreFromHash();
  resort();
  applyFilters();

  // Perf instrumentation consumed by scripts/perf_browser_check.py.
  // Not a public API. timeFilter bypasses the input debounce so the §6
  // filter-latency budget measures the actual work.
  window.__sdrPerf = {
    timeFilter: function (query) {
      clearTimeout(searchDebounceTimer);
      $search.value = query;
      var t0 = performance.now();
      applyFilters();
      return performance.now() - t0;
    },
    // Includes the truncation indicator row when the result set is capped.
    rowCount: function () { return $body.children.length; },
  };

  /* ===========================================================
   * Graph view (D3 force-directed)
   * =========================================================== */

  var GRAPH_NODE_THRESHOLD = (payload.meta && typeof payload.meta.max_graph_nodes === "number")
    ? payload.meta.max_graph_nodes
    : 1000;

  var $viewButtons = document.querySelectorAll(".view-button[data-view]");
  var $catalogView = document.getElementById("catalog-view");
  var $graphView = document.getElementById("graph-view");
  var $changesView = document.getElementById("changes-view");
  var $trendView = document.getElementById("trend-view");
  var $graphCanvas = document.getElementById("graph-canvas");
  var $graphSearch = document.getElementById("graph-search");
  var $graphTypeFilter = document.getElementById("graph-type-filter");
  var $graphOrphanFilter = document.getElementById("graph-orphan-filter");
  var $graphReset = document.getElementById("graph-reset");
  var $graphStats = document.getElementById("graph-stats");
  var $graphDegraded = document.getElementById("graph-degraded");
  var $graphRenderAnyway = document.getElementById("graph-render-anyway");

  var graphState = {
    initialized: false,
    simulation: null,
    nodeSel: null,
    linkSel: null,
    zoom: null,
    g: null,
    nodes: [],
    links: [],
    neighborMap: {},
    selectedTypes: {},
    orphanMode: "connected",
    query: "",
    hoverId: null,
  };

  function showView(name) {
    activeView = name;
    $catalogView.hidden = name !== "catalog";
    $graphView.hidden = name !== "graph";
    if ($changesView) $changesView.hidden = name !== "changes";
    if ($trendView) $trendView.hidden = name !== "trend";
    $viewButtons.forEach(function (b) {
      b.classList.toggle("is-active", b.getAttribute("data-view") === name);
    });
    if (name === "graph" && !graphState.initialized) {
      maybeInitGraph();
    }
    updateHash();
  }

  $viewButtons.forEach(function (b) {
    b.addEventListener("click", function () { showView(b.getAttribute("data-view")); });
  });

  function maybeInitGraph() {
    var totalNodes = catalog.length;
    if (totalNodes > GRAPH_NODE_THRESHOLD) {
      $graphDegraded.hidden = false;
      return;
    }
    initGraph();
  }

  // Wired once — re-entering the graph view before opting in must not
  // stack duplicate listeners. initGraph() self-guards on re-entry.
  $graphRenderAnyway.addEventListener("click", function () {
    $graphDegraded.hidden = true;
    initGraph();
  });

  function initGraph() {
    if (graphState.initialized) return;
    graphState.initialized = true;
    if (!window.d3) {
      console.error("sdr-visualizer: D3 not loaded; graph view unavailable");
      return;
    }
    var d3 = window.d3;

    // Node copies derived from the catalog (id/type/name/in_degree all live
    // there) — D3 mutates node objects, so don't share with the catalog.
    var srcEdges = (payload.graph && payload.graph.edges) || [];
    graphState.nodes = catalog.map(function (n) {
      return {
        id: n.id,
        type: n.type,
        derived_kind: n.derived_kind,
        label: n.name,
        in_degree: n.in_degree || 0,
        // Lowercased once for the graph search — recomputeGraphFilter must
        // not allocate per-node strings on every pass (same pattern as the
        // catalog's entry._search blob).
        _lc: ((n.name || "") + " " + n.id).toLowerCase(),
      };
    });
    graphState.links = srcEdges.map(function (e) { return { source: e.source, target: e.target }; });

    // Adjacency for hover-highlight. Null-prototype objects: ids come from
    // untrusted snapshots, and a component id like "constructor" would
    // otherwise hit inherited Object.prototype members in truthiness checks.
    graphState.neighborMap = Object.create(null);
    srcEdges.forEach(function (e) {
      (graphState.neighborMap[e.source] = graphState.neighborMap[e.source] || Object.create(null))[e.target] = true;
      (graphState.neighborMap[e.target] = graphState.neighborMap[e.target] || Object.create(null))[e.source] = true;
    });

    // One-time neighbor counts — recomputeGraphFilter runs per filter change and
    // must not allocate Object.keys() per node.
    graphState.nodes.forEach(function (n) {
      var m = graphState.neighborMap[n.id];
      n._neighborCount = m ? Object.keys(m).length : 0;
    });

    // SVG setup
    var svg = d3.select($graphCanvas);
    var rect = $graphCanvas.getBoundingClientRect();
    var width = rect.width || 800;
    var height = rect.height || 560;
    svg.attr("viewBox", "0 0 " + width + " " + height);

    var g = svg.append("g");
    graphState.g = g;

    graphState.zoom = d3.zoom()
      .scaleExtent([0.2, 6])
      .on("zoom", function (event) {
        g.attr("transform", event.transform);
        g.classed("graph-labels-all", event.transform.k >= 1.4);
      });
    svg.call(graphState.zoom);

    var color = {
      metric: "#2a2a2a",
      dimension: "#4a6f6f",
      derived_field: "#5e6b78",
      segment: "#8a6a4a",
      calculated_metric: "#a08018",
    };

    var linkSel = g.append("g").attr("stroke", "#c8c4b8").attr("stroke-opacity", 0.6)
      .selectAll("line")
      .data(graphState.links)
      .enter().append("line")
      .attr("class", "graph-edge");
    graphState.linkSel = linkSel;

    var nodeSel = g.append("g")
      .selectAll("g.graph-node")
      .data(graphState.nodes)
      .enter().append("g")
      .attr("class", "graph-node");
    graphState.nodeSel = nodeSel;

    nodeSel.append("circle")
      .attr("r", function (d) { return Math.max(3, Math.min(14, 3 + Math.sqrt(d.in_degree))); })
      .attr("fill", function (d) { return color[d.type] || "#6b6b66"; });

    nodeSel.append("text")
      .attr("dx", function (d) { return Math.max(4, Math.min(16, 4 + Math.sqrt(d.in_degree))); })
      .attr("dy", "0.32em")
      .text(function (d) { return d.label; });

    // Label culling: painting a text element per node is the dominant frame
    // cost at scale. Show labels for the highest-in-degree nodes by default;
    // zooming past 1.4x reveals all (see the zoom handler); hover/highlight
    // always reveals via CSS.
    var LABEL_BUDGET = 60;
    if (graphState.nodes.length > 200) {
      var labeled = Object.create(null);
      graphState.nodes.slice()
        .sort(function (a, b) { return b.in_degree - a.in_degree; })
        .slice(0, LABEL_BUDGET)
        .forEach(function (n) { labeled[n.id] = true; });
      nodeSel.classed("is-labeled", function (d) { return !!labeled[d.id]; });
    } else {
      nodeSel.classed("is-labeled", true);
    }

    nodeSel.on("mouseover", function (event, d) { graphState.hoverId = d.id; scheduleGraphPaint(); })
      .on("mouseout", function () { graphState.hoverId = null; scheduleGraphPaint(); })
      .on("click", function (event, d) { openDetail(d.id); });

    nodeSel.call(d3.drag()
      .on("start", function (event, d) {
        if (!graphState.simulation) return;
        if (!event.active) graphState.simulation.alphaTarget(0.3).restart();
        d.fx = d.x; d.fy = d.y;
      })
      .on("drag", function (event, d) {
        if (graphState.simulation) {
          d.fx = event.x; d.fy = event.y;
        } else {
          // Radial mode: no simulation — move the node and repaint.
          d.x = event.x; d.y = event.y;
          tick();
        }
      })
      .on("end", function (event, d) {
        if (!graphState.simulation) return;
        if (!event.active) graphState.simulation.alphaTarget(0);
        d.fx = null; d.fy = null;
      }));

    // SPEC §14 Q2: force-directed looks weird with very few nodes — below 20,
    // skip the simulation and place nodes evenly on a circle. d3.forceLink is
    // still used (when simulating) to resolve edge endpoints; in radial mode
    // we resolve them ourselves before painting.
    var RADIAL_THRESHOLD = 20;
    if (graphState.nodes.length > 0 && graphState.nodes.length < RADIAL_THRESHOLD) {
      graphState.simulation = null;
      radialLayout();
      tick();
    } else {
      // Degraded physics — a coarser Barnes-Hut theta and faster alpha decay
      // trade a little layout quality for ~30% cheaper ticks and earlier
      // settling — applies on either axis: above the opt-in gate
      // (GRAPH_NODE_THRESHOLD, --max-graph-nodes — the user was warned), or
      // above the 1,000-node line where tick cost was measured to hurt
      // (§6's interactive ceiling). Raising --max-graph-nodes to skip the
      // "Render anyway" click must not silently buy full-precision physics
      // at 5k nodes.
      var isLargeGraph = graphState.nodes.length > Math.min(GRAPH_NODE_THRESHOLD, 1000);
      graphState.simulation = d3.forceSimulation(graphState.nodes)
        .force("link", d3.forceLink(graphState.links).id(function (d) { return d.id; }).distance(60).strength(0.5))
        .force("charge", d3.forceManyBody().strength(-90).theta(isLargeGraph ? 1.2 : 0.9))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force("collide", d3.forceCollide().radius(function (d) {
          return Math.max(6, 5 + Math.sqrt(d.in_degree)) + 2;
        }))
        .alphaDecay(isLargeGraph ? 0.08 : 0.05)
        .on("tick", tick)
        .on("end", function () {
          // Async settling can move a hovered node out from under a
          // stationary pointer with no mouseout. When the simulation ends,
          // drop a hover the browser no longer reports as hovered.
          if (graphState.hoverId !== null && !$graphCanvas.querySelector("g.graph-node:hover")) {
            graphState.hoverId = null;
            scheduleGraphPaint();
          }
        })
        .stop();

      // Warm-start: run the early high-energy ticks synchronously before
      // first paint so the graph appears mostly settled instead of exploding
      // into place — until near-settled (alpha threshold, immune to decay
      // retunes) or the time budget elapses, whichever comes first. A fixed
      // tick count froze the view switch for seconds at 5k nodes (~18ms/
      // tick); graphs that can't settle in budget hand the remainder to the
      // async simulation (one tick per frame, page stays interactive).
      // Manual tick() does not dispatch the tick event, so paint once
      // explicitly, then restart wherever the warm-up got to (floored at low
      // alpha for the gentle finish fully-warmed graphs get).
      var WARM_BUDGET_MS = 150;
      var SETTLE_ALPHA = 0.02;
      var warmStart = performance.now();
      while (
        graphState.simulation.alpha() > SETTLE_ALPHA &&
        performance.now() - warmStart < WARM_BUDGET_MS
      ) {
        graphState.simulation.tick();
      }
      tick();
      graphState.simulation.alpha(Math.max(0.12, graphState.simulation.alpha())).restart();
    }

    function radialLayout() {
      var n = graphState.nodes.length;
      var radius = Math.max(60, Math.min(width, height) / 2 - 80);
      graphState.nodes.forEach(function (d, i) {
        var angle = (i / n) * 2 * Math.PI - Math.PI / 2;
        d.x = width / 2 + radius * Math.cos(angle);
        d.y = height / 2 + radius * Math.sin(angle);
      });
      // Without a simulation, link source/target stay as id strings —
      // resolve them to node objects so tick() can read .x/.y.
      var nodeById = Object.create(null);
      graphState.nodes.forEach(function (d) { nodeById[d.id] = d; });
      graphState.links.forEach(function (l) {
        if (typeof l.source === "string") l.source = nodeById[l.source];
        if (typeof l.target === "string") l.target = nodeById[l.target];
      });
    }

    function tick() {
      linkSel
        .attr("x1", function (d) { return d.source.x; })
        .attr("y1", function (d) { return d.source.y; })
        .attr("x2", function (d) { return d.target.x; })
        .attr("y2", function (d) { return d.target.y; });
      nodeSel.attr("transform", function (d) { return "translate(" + d.x + "," + d.y + ")"; });
    }

    // Wire filter UI. Search debounced like the catalog's — each keystroke
    // otherwise costs a full recompute + paint pass over every node and edge.
    // Any filter change cancels an active hover (matching pre-rewrite
    // behavior): paintGraph gives hover precedence, so a stale hoverId would
    // otherwise keep the new filter state invisible until the next mouseout.
    // The repaint lands on the next animation frame (scheduleGraphPaint).
    var graphSearchTimer = null;
    function onGraphFilterChange() {
      // A pending search timer is either superseded by this change (the
      // recompute reads the query live) or would later fire as a no-op that
      // wrongly cancels a hover — kill it.
      clearTimeout(graphSearchTimer);
      graphState.hoverId = null;
      recomputeGraphFilter();
      scheduleGraphPaint();
    }
    selectedTypesFromUI();
    graphState.orphanMode = $graphOrphanFilter.value;
    recomputeGraphFilter();
    paintGraph();
    $graphTypeFilter.addEventListener("change", function () { selectedTypesFromUI(); onGraphFilterChange(); });
    $graphOrphanFilter.addEventListener("change", function () { graphState.orphanMode = $graphOrphanFilter.value; onGraphFilterChange(); });
    $graphSearch.addEventListener("input", function () {
      clearTimeout(graphSearchTimer);
      graphSearchTimer = setTimeout(function () {
        // No-op edits (select-all + retype the same text) must not cancel a
        // hover the user started after typing.
        if ($graphSearch.value.trim().toLowerCase() !== graphState.query) onGraphFilterChange();
      }, SEARCH_DEBOUNCE_MS);
    });
    $graphReset.addEventListener("click", function () {
      svg.transition().duration(150).call(graphState.zoom.transform, d3.zoomIdentity);
      if (graphState.simulation) {
        graphState.simulation.alpha(0.6).restart();
      } else {
        radialLayout();
        tick();
      }
    });

    $graphStats.textContent = graphState.nodes.length + " nodes · " + graphState.links.length + " edges";
  }

  function selectedTypesFromUI() {
    graphState.selectedTypes = {};
    var checked = $graphTypeFilter.querySelectorAll("input:checked");
    for (var i = 0; i < checked.length; i++) graphState.selectedTypes[checked[i].value] = true;
  }

  // Filter state (per-node _visible/_matched) is recomputed only when a
  // filter input changes; painting reads it. Hover previously re-derived
  // this on every mouseout — at thousands of nodes that made each hover
  // event a full state pass plus 4–6 selection walks. The query is read
  // live from the input (not from a debounce-committed copy) so no
  // recompute caller can ever see a stale query.
  function recomputeGraphFilter() {
    graphState.query = $graphSearch.value.trim().toLowerCase();
    var query = graphState.query;
    graphState.nodes.forEach(function (n) {
      var typeOk = !!(graphState.selectedTypes[n.type] || (n.derived_kind && graphState.selectedTypes[n.derived_kind]));
      var orphanOk = true;
      if (graphState.orphanMode === "connected") {
        orphanOk = n._neighborCount > 0;
      } else if (graphState.orphanMode === "orphans") {
        orphanOk = n._neighborCount === 0;
      }
      n._matched = !query || n._lc.indexOf(query) !== -1;
      n._visible = typeOk && orphanOk;
    });
  }

  // Single pass over nodes and one over links, setting every class at once
  // (the old code walked each selection once per class). Contract: hover
  // fading wins over filter fading while active; search-match highlights
  // persist through hover; filter changes cancel hover (see the filter
  // wiring in initGraph). Link endpoints are node objects (resolved by
  // forceLink in the simulation branch, by radialLayout otherwise), so
  // visibility and identity read straight off the nodes — no parallel id
  // maps to keep in sync.
  function paintGraph() {
    if (!graphState.nodeSel) return;
    var hoverId = graphState.hoverId;
    var neighbors = hoverId ? (graphState.neighborMap[hoverId] || Object.create(null)) : null;
    var query = graphState.query;

    graphState.nodeSel.each(function (d) {
      var hover = false;
      var faded;
      var highlighted = !!(query && d._matched && d._visible);
      if (hoverId) {
        hover = d.id === hoverId;
        faded = !hover && !neighbors[d.id];
      } else {
        faded = !d._visible || !!(query && !d._matched);
      }
      var cl = this.classList;
      cl.toggle("is-hover", hover);
      cl.toggle("is-faded", faded);
      cl.toggle("is-highlighted", highlighted);
    });

    graphState.linkSel.each(function (d) {
      var faded;
      var highlighted = false;
      if (hoverId) {
        highlighted = d.source.id === hoverId || d.target.id === hoverId;
        faded = !highlighted;
      } else {
        faded = !(d.source._visible && d.target._visible);
      }
      var cl = this.classList;
      cl.toggle("is-faded", faded);
      cl.toggle("is-highlighted", highlighted);
    });
  }

  // Coalesce paints to one per frame. Sweeping the pointer across a dense
  // graph fires many mouseover/mouseout pairs per frame; painting each one
  // synchronously janked at ~3.6ms/event on 5k nodes.
  var graphPaintQueued = false;
  function scheduleGraphPaint() {
    if (graphPaintQueued) return;
    graphPaintQueued = true;
    requestAnimationFrame(function () {
      graphPaintQueued = false;
      paintGraph();
    });
  }

  /* ===========================================================
   * Changes view (comparative report, payload.changes)
   * =========================================================== */

  function formatChangeValue(value) {
    if (value === null || value === undefined || value === "") return "—";
    return String(value);
  }

  function changeFieldHtml(f) {
    var label = '<span class="change-field-name mono">' + escapeHtml(f.field) + "</span> ";
    if (f.added !== undefined || f.removed !== undefined) {
      var parts = [];
      (f.added || []).forEach(function (v) {
        parts.push('<span class="change-list-added">+ ' + escapeHtml(v) + "</span>");
      });
      (f.removed || []).forEach(function (v) {
        parts.push('<span class="change-list-removed">− ' + escapeHtml(v) + "</span>");
      });
      return '<li class="change-field">' + label + parts.join(" ") + "</li>";
    }
    return (
      '<li class="change-field">' + label +
      '<span class="change-old">' + escapeHtml(formatChangeValue(f.old)) + "</span>" +
      '<span class="change-arrow"> → </span>' +
      '<span class="change-new">' + escapeHtml(formatChangeValue(f.new)) + "</span></li>"
    );
  }

  function changeEntryLabel(entry, linkable) {
    var label =
      '<span class="dot dot-' + escapeHtml(entry.type) + '"></span>' +
      '<span class="change-name">' + escapeHtml(entry.name) + "</span> " +
      '<span class="row-id mono">' + escapeHtml(entry.id) + "</span>";
    if (linkable && byId[entry.id]) {
      return (
        '<button type="button" class="ref-link change-link" data-id="' +
        escapeHtml(entry.id) + '">' + label + "</button>"
      );
    }
    return '<span class="change-static">' + label + "</span>";
  }

  function changeRowSearchAttr(entry) {
    return ' data-search="' + escapeHtml((entry.name + " " + entry.id).toLowerCase()) + '"';
  }

  // Per-type breakdown for a summary count, e.g. "(3 metrics, 9 dimensions)".
  // Counts entry.type occurrences preserving first-seen order; empty lists
  // get no parenthetical. Types are a fixed vocabulary, but the assembled
  // text is still routed through escapeHtml for consistency with the rest
  // of this view.
  function changeTypeBreakdown(entries) {
    if (!entries.length) return "";
    var order = [];
    var counts = {};
    entries.forEach(function (entry) {
      if (!Object.prototype.hasOwnProperty.call(counts, entry.type)) {
        counts[entry.type] = 0;
        order.push(entry.type);
      }
      counts[entry.type]++;
    });
    var parts = order.map(function (type) {
      var count = counts[type];
      return count + " " + formatTypeLabel(type).toLowerCase() + (count > 1 ? "s" : "");
    });
    return " (" + escapeHtml(parts.join(", ")) + ")";
  }

  function renderChanges() {
    if (!$changesView || !payload.changes) return;
    var ch = payload.changes;
    var baselineLabel = ch.baseline
      ? ch.baseline.taken_at || ch.baseline.source || "baseline"
      : "baseline";
    document.getElementById("changes-summary").innerHTML =
      '<span class="change-count change-count-added">+' + ch.added.length + " added" +
        changeTypeBreakdown(ch.added) + "</span>" +
      '<span class="separator">·</span>' +
      '<span class="change-count change-count-removed">−' + ch.removed.length + " removed" +
        changeTypeBreakdown(ch.removed) + "</span>" +
      '<span class="separator">·</span>' +
      '<span class="change-count change-count-modified">~' + ch.modified.length + " modified" +
        changeTypeBreakdown(ch.modified) + "</span>" +
      '<span class="changes-baseline">against ' + escapeHtml(baselineLabel) + "</span>";

    var parts = [];
    if (!ch.added.length && !ch.removed.length && !ch.modified.length) {
      parts.push('<p class="changes-empty">No changes between these snapshots.</p>');
    }
    if (ch.added.length) {
      parts.push('<h2 class="change-group-title ui">Added (' + ch.added.length + ")</h2>");
      ch.added.forEach(function (entry) {
        var catalogEntry = byId[entry.id];
        var noDesc = catalogEntry && !catalogEntry.description
          ? '<span class="change-no-desc ui">no description</span>'
          : "";
        parts.push(
          '<div class="change-row change-added"' + changeRowSearchAttr(entry) + ">" +
            changeEntryLabel(entry, true) + noDesc + "</div>"
        );
      });
    }
    if (ch.removed.length) {
      parts.push('<h2 class="change-group-title ui">Removed (' + ch.removed.length + ")</h2>");
      ch.removed.forEach(function (entry) {
        // Removed components no longer exist in the primary snapshot: no link.
        parts.push(
          '<div class="change-row change-removed"' + changeRowSearchAttr(entry) + ">" +
            changeEntryLabel(entry, false) + "</div>"
        );
      });
    }
    if (ch.modified.length) {
      parts.push('<h2 class="change-group-title ui">Modified (' + ch.modified.length + ")</h2>");
      ch.modified.forEach(function (entry) {
        var count = entry.fields.length;
        parts.push(
          '<details class="change-row change-modified"' + changeRowSearchAttr(entry) + "><summary>" +
            changeEntryLabel(entry, true) +
            '<span class="change-field-count ui">' + count + " field" + (count === 1 ? "" : "s") + "</span>" +
          "</summary>" +
          '<ul class="change-fields">' + entry.fields.map(changeFieldHtml).join("") + "</ul>" +
          "</details>"
        );
      });
    }
    document.getElementById("changes-body").innerHTML = parts.join("");

    $changesView.addEventListener("click", function (event) {
      var btn = event.target.closest("button.ref-link");
      if (!btn) return;
      // A link inside <summary> must open the detail panel, not toggle the
      // <details> element — preventDefault cancels the toggle.
      event.preventDefault();
      openDetail(btn.getAttribute("data-id"));
    });

    var changesSearchDebounceTimer = null;
    document.getElementById("changes-search").addEventListener("input", function (event) {
      clearTimeout(changesSearchDebounceTimer);
      changesSearchDebounceTimer = setTimeout(function () {
        var query = event.target.value.trim().toLowerCase();
        $changesView.querySelectorAll("#changes-body .change-row").forEach(function (row) {
          row.hidden = !!query && (row.getAttribute("data-search") || "").indexOf(query) === -1;
        });
      }, SEARCH_DEBOUNCE_MS);
    });
  }
  renderChanges();

  /* ===========================================================
   * Trend view (interval log; charts are server-rendered SVG)
   * =========================================================== */

  function trendIdList(label, ids, cls) {
    if (!ids.length) return "";
    return (
      '<div class="trend-ids"><span class="trend-ids-label ' + cls + '">' +
        label + " (" + ids.length + ")</span> " +
      ids.map(function (id) {
        return '<span class="mono trend-id">' + escapeHtml(id) + "</span>";
      }).join(" ") +
      "</div>"
    );
  }

  function renderTrendLog() {
    if (!$trendView || !payload.trend) return;
    var parts = [];
    payload.trend.intervals.forEach(function (iv) {
      var fromLabel = formatDate(iv.from);
      var toLabel = formatDate(iv.to);
      if (fromLabel === toLabel) {
        fromLabel = iv.from_source || fromLabel;
        toLabel = iv.to_source || toLabel;
      }
      parts.push(
        '<details class="trend-interval"><summary>' +
          '<span class="trend-range">' +
            escapeHtml(fromLabel) + " → " + escapeHtml(toLabel) +
          "</span>" +
          '<span class="change-count change-count-added">+' + iv.added.length + "</span>" +
          '<span class="change-count change-count-removed">−' + iv.removed.length + "</span>" +
          '<span class="change-count change-count-modified">~' + iv.modified.length + "</span>" +
        "</summary>" +
        trendIdList("Added", iv.added, "change-count-added") +
        trendIdList("Removed", iv.removed, "change-count-removed") +
        trendIdList("Modified", iv.modified, "change-count-modified") +
        "</details>"
      );
    });
    if (payload.trend.capped) {
      parts.push(
        '<p class="trend-capped ui">Window capped at the most recent snapshots; ' +
        "older history not shown.</p>"
      );
    }
    document.getElementById("trend-log").innerHTML = parts.join("");
  }
  renderTrendLog();

  // Deferred URL-state restore: showView/openDetail need the graph section's
  // definitions, so view/detail restore runs after everything is wired. The
  // params were captured at load, before the first updateHash() rewrote
  // location.hash.
  function restoreViewAndDetail(params) {
    if (!params) return;
    var viewParam = params.get("view");
    if (viewParam === "graph") showView("graph");
    if (viewParam === "changes" && $changesView) showView("changes");
    if (viewParam === "trend" && $trendView) showView("trend");
    var detailId = params.get("detail");
    if (detailId && byId[detailId]) openDetail(detailId);
  }
  restoreViewAndDetail(initialHashParams);
})();
