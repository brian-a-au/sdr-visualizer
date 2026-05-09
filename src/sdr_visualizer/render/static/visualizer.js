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
  var byId = {};
  catalog.forEach(function (entry) { byId[entry.id] = entry; });

  var indexById = (payload.catalog_index && payload.catalog_index.by_id) || {};

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

  function formatTypeLabel(type) {
    switch (type) {
      case "metric": return "Metric";
      case "dimension": return "Dimension";
      case "derived_field": return "Derived field";
      case "segment": return "Segment";
      case "calculated_metric": return "Calc metric";
      default: return type;
    }
  }

  function formatDate(value) {
    if (!value) return "—";
    // Tolerate both ISO 8601 and the cja_auto_sdr "YYYY-MM-DD HH:MM:SS" shape.
    var date = new Date(value);
    if (isNaN(date.getTime())) return value;
    var y = date.getUTCFullYear();
    var m = String(date.getUTCMonth() + 1).padStart(2, "0");
    var d = String(date.getUTCDate()).padStart(2, "0");
    return y + "-" + m + "-" + d;
  }

  function daysSince(value) {
    if (!value) return Infinity;
    var date = new Date(value);
    if (isNaN(date.getTime())) return Infinity;
    var diff = Date.now() - date.getTime();
    return diff / 86400000;
  }

  function tagsOf(entry) {
    return entry.tags || [];
  }

  function descriptionOf(entry) {
    return entry.description || (entry.formula_text ? entry.formula_text : "");
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

    var filtered = catalog.filter(function (entry) {
      if (!typeSet[entry.type]) return false;

      if (query) {
        var idx = indexById[entry.id];
        var hay = idx ? idx.search : ((entry.name || "") + " " + (entry.id || "")).toLowerCase();
        if (hay.indexOf(query) === -1) return false;
      }

      if (descriptionMode === "has" && !entry.description) return false;
      if (descriptionMode === "missing" && entry.description) return false;

      if (referencesMode === "referenced" && !((entry.in_degree || 0) > 0)) return false;
      if (referencesMode === "orphaned" && (entry.in_degree || 0) > 0) return false;

      if (modifiedDays !== Infinity) {
        if (daysSince(entry.modified_at) > modifiedDays) return false;
      }

      return true;
    });

    filtered.sort(compareEntries);
    renderRows(filtered);
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
      var ad = av ? new Date(av).getTime() : 0;
      var bd = bv ? new Date(bv).getTime() : 0;
      return ad - bd;
    }
    av = (av || "").toString().toLowerCase();
    bv = (bv || "").toString().toLowerCase();
    if (av < bv) return -1;
    if (av > bv) return 1;
    return 0;
  }

  /* ----- Rendering ----- */

  function renderRows(entries) {
    var html = entries.map(rowHtml).join("");
    $body.innerHTML = html;
    $empty.hidden = entries.length > 0;
    $resultCount.textContent = entries.length === catalog.length
      ? entries.length + " components"
      : entries.length + " of " + catalog.length;
    updateHeaderSortIndicators();
  }

  function rowHtml(entry) {
    var tags = tagsOf(entry).slice(0, 4).map(function (t) {
      return '<span class="tag">' + escapeHtml(t) + "</span>";
    }).join("");
    if (tagsOf(entry).length > 4) {
      tags += '<span class="tag">+' + (tagsOf(entry).length - 4) + "</span>";
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
        '<td class="col-type"><span class="dot dot-' + escapeHtml(entry.type) + '"></span>' + escapeHtml(formatTypeLabel(entry.type)) + "</td>" +
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
    $detailBody.innerHTML = detailHtml(entry);
    $detailPanel.classList.add("is-open");
    $detailPanel.setAttribute("aria-hidden", "false");
    $detailOverlay.classList.add("is-open");
    $detailOverlay.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function closeDetail() {
    $detailPanel.classList.remove("is-open");
    $detailPanel.setAttribute("aria-hidden", "true");
    $detailOverlay.classList.remove("is-open");
    $detailOverlay.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  function detailHtml(entry) {
    var typeColor = '<span class="dot dot-' + escapeHtml(entry.type) + '"></span>';
    var pieces = [
      '<div class="detail-eyebrow">' + typeColor + escapeHtml(formatTypeLabel(entry.type)) + "</div>",
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
      compMeta += "<dt>Type</dt><dd>" + escapeHtml(formatTypeLabel(entry.type)) + "</dd>";
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

  $search.addEventListener("input", applyFilters);
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
      applyFilters();
    });
  });

  $body.addEventListener("click", function (event) {
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

  applyFilters();

  /* ===========================================================
   * Graph view (D3 force-directed)
   * =========================================================== */

  var GRAPH_NODE_THRESHOLD = 1000;

  var $viewButtons = document.querySelectorAll(".view-button[data-view]");
  var $catalogView = document.getElementById("catalog-view");
  var $graphView = document.getElementById("graph-view");
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
    orphanMode: "all",
    query: "",
  };

  function showView(name) {
    $catalogView.hidden = name !== "catalog";
    $graphView.hidden = name !== "graph";
    $viewButtons.forEach(function (b) {
      b.classList.toggle("is-active", b.getAttribute("data-view") === name);
    });
    if (name === "graph" && !graphState.initialized) {
      maybeInitGraph();
    }
  }

  $viewButtons.forEach(function (b) {
    b.addEventListener("click", function () { showView(b.getAttribute("data-view")); });
  });

  function maybeInitGraph() {
    var totalNodes = (payload.graph && payload.graph.nodes) ? payload.graph.nodes.length : 0;
    if (totalNodes > GRAPH_NODE_THRESHOLD) {
      $graphDegraded.hidden = false;
      $graphRenderAnyway.addEventListener("click", function () {
        $graphDegraded.hidden = true;
        initGraph();
      }, { once: true });
      return;
    }
    initGraph();
  }

  function initGraph() {
    if (graphState.initialized) return;
    graphState.initialized = true;
    if (!window.d3) {
      console.error("sdr-visualizer: D3 not loaded; graph view unavailable");
      return;
    }
    var d3 = window.d3;

    // Node + link copies — D3 mutates them, so don't share with the catalog.
    var srcNodes = (payload.graph && payload.graph.nodes) || [];
    var srcEdges = (payload.graph && payload.graph.edges) || [];

    var inDeg = (payload.graph && payload.graph.in_degree) || {};
    graphState.nodes = srcNodes.map(function (n) {
      return {
        id: n.id,
        type: n.type,
        label: n.label,
        in_degree: inDeg[n.id] || 0,
      };
    });
    graphState.links = srcEdges.map(function (e) { return { source: e.source, target: e.target }; });

    // Adjacency for hover-highlight.
    graphState.neighborMap = {};
    srcEdges.forEach(function (e) {
      (graphState.neighborMap[e.source] = graphState.neighborMap[e.source] || {})[e.target] = true;
      (graphState.neighborMap[e.target] = graphState.neighborMap[e.target] || {})[e.source] = true;
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
      .on("zoom", function (event) { g.attr("transform", event.transform); });
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

    nodeSel.on("mouseover", function (event, d) { highlightNeighbors(d.id); })
      .on("mouseout", function () { applyGraphFilters(); })
      .on("click", function (event, d) { openDetail(d.id); });

    nodeSel.call(d3.drag()
      .on("start", function (event, d) {
        if (!event.active) graphState.simulation.alphaTarget(0.3).restart();
        d.fx = d.x; d.fy = d.y;
      })
      .on("drag", function (event, d) { d.fx = event.x; d.fy = event.y; })
      .on("end", function (event, d) {
        if (!event.active) graphState.simulation.alphaTarget(0);
        d.fx = null; d.fy = null;
      }));

    graphState.simulation = d3.forceSimulation(graphState.nodes)
      .force("link", d3.forceLink(graphState.links).id(function (d) { return d.id; }).distance(60).strength(0.5))
      .force("charge", d3.forceManyBody().strength(-90))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide().radius(function (d) {
        return Math.max(6, 5 + Math.sqrt(d.in_degree)) + 2;
      }))
      .alphaDecay(0.05)
      .on("tick", tick);

    function tick() {
      linkSel
        .attr("x1", function (d) { return d.source.x; })
        .attr("y1", function (d) { return d.source.y; })
        .attr("x2", function (d) { return d.target.x; })
        .attr("y2", function (d) { return d.target.y; });
      nodeSel.attr("transform", function (d) { return "translate(" + d.x + "," + d.y + ")"; });
    }

    // Wire filter UI.
    selectedTypesFromUI();
    applyGraphFilters();
    $graphTypeFilter.addEventListener("change", function () { selectedTypesFromUI(); applyGraphFilters(); });
    $graphOrphanFilter.addEventListener("change", function () { graphState.orphanMode = $graphOrphanFilter.value; applyGraphFilters(); });
    $graphSearch.addEventListener("input", function () { graphState.query = $graphSearch.value.trim().toLowerCase(); applyGraphFilters(); });
    $graphReset.addEventListener("click", function () {
      svg.transition().duration(150).call(graphState.zoom.transform, d3.zoomIdentity);
      graphState.simulation.alpha(0.6).restart();
    });

    $graphStats.textContent = graphState.nodes.length + " nodes · " + graphState.links.length + " edges";
  }

  function selectedTypesFromUI() {
    graphState.selectedTypes = {};
    var checked = $graphTypeFilter.querySelectorAll("input:checked");
    for (var i = 0; i < checked.length; i++) graphState.selectedTypes[checked[i].value] = true;
  }

  function applyGraphFilters() {
    if (!graphState.nodeSel) return;

    var visibleIds = {};
    graphState.nodes.forEach(function (n) {
      var typeOk = !!graphState.selectedTypes[n.type];
      var orphanOk = true;
      if (graphState.orphanMode === "connected") {
        orphanOk = (graphState.neighborMap[n.id] && Object.keys(graphState.neighborMap[n.id]).length > 0);
      } else if (graphState.orphanMode === "orphans") {
        orphanOk = !graphState.neighborMap[n.id];
      }
      var queryOk = true;
      if (graphState.query) {
        queryOk = (n.label || "").toLowerCase().indexOf(graphState.query) !== -1
          || (n.id || "").toLowerCase().indexOf(graphState.query) !== -1;
      }
      var visible = typeOk && orphanOk;
      n._matched = queryOk;
      n._visible = visible;
      if (visible) visibleIds[n.id] = true;
    });

    graphState.nodeSel.classed("is-faded", function (d) {
      if (!d._visible) return true;
      if (graphState.query) return !d._matched;
      return false;
    });
    graphState.nodeSel.classed("is-highlighted", function (d) {
      return graphState.query && d._matched && d._visible;
    });
    graphState.linkSel.classed("is-faded", function (d) {
      var src = typeof d.source === "object" ? d.source.id : d.source;
      var tgt = typeof d.target === "object" ? d.target.id : d.target;
      return !visibleIds[src] || !visibleIds[tgt];
    });
  }

  function highlightNeighbors(id) {
    if (!graphState.nodeSel) return;
    var neighbors = graphState.neighborMap[id] || {};
    graphState.nodeSel.classed("is-hover", function (d) { return d.id === id; });
    graphState.nodeSel.classed("is-faded", function (d) {
      if (d.id === id) return false;
      if (neighbors[d.id]) return false;
      return true;
    });
    graphState.linkSel.classed("is-faded", function (d) {
      var src = typeof d.source === "object" ? d.source.id : d.source;
      var tgt = typeof d.target === "object" ? d.target.id : d.target;
      return src !== id && tgt !== id;
    });
    graphState.linkSel.classed("is-highlighted", function (d) {
      var src = typeof d.source === "object" ? d.source.id : d.source;
      var tgt = typeof d.target === "object" ? d.target.id : d.target;
      return src === id || tgt === id;
    });
  }
})();
