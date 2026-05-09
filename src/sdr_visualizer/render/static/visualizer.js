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
      pieces.push('<div class="detail-section"><h3>Anatomy</h3>' + segMeta + "</div>");
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
})();
