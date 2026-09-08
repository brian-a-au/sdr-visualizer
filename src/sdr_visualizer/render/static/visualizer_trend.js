(function () {
  "use strict";

  // The parent owns view activation and URL state. This factory owns only
  // one-time Trend initialization and the lazily materialized interval log.
  function create(context) {
    var payload = context.payload;
    var $trendView = context.view;
    var $trendLog = context.log;
    var escapeHtml = context.escapeHtml;
    var formatDate = context.formatDate;

    var TREND_ID_BATCH_SIZE = 100;
    var TREND_INTERVAL_CAP = 59;
    var trendState = {
      initialized: false,
      intervals: [],
      revealed: [],
    };

    function trendIdList(label, ids, cls, intervalIndex, kind) {
      if (!ids.length) return "";
      var shown = Math.min(trendState.revealed[intervalIndex][kind], ids.length);
      var button = "";
      if (shown < ids.length) {
        button =
          '<button type="button" class="trend-show-next progressive-button" data-interval="' +
          intervalIndex + '" data-kind="' + kind + '">Show next ' +
          Math.min(TREND_ID_BATCH_SIZE, ids.length - shown) + "</button>";
      }
      return (
        '<div class="trend-ids"><span class="trend-ids-label ' + cls + '">' +
          label + " (" + ids.length + ")</span> " +
        ids.slice(0, shown).map(function (id) {
          return '<span class="mono trend-id">' + escapeHtml(id) + "</span>";
        }).join(" ") + button +
        "</div>"
      );
    }

    function renderTrendInterval(intervalIndex) {
      var iv = trendState.intervals[intervalIndex];
      var $body = $trendView.querySelector(
        '.trend-interval-body[data-interval="' + intervalIndex + '"]'
      );
      if (!$body) return;
      $body.innerHTML =
        trendIdList("Added", iv.added, "change-count-added", intervalIndex, "added") +
        trendIdList("Removed", iv.removed, "change-count-removed", intervalIndex, "removed") +
        trendIdList("Modified", iv.modified, "change-count-modified", intervalIndex, "modified");
      $body.setAttribute("data-rendered", "true");
    }

    function renderTrendLog() {
      var parts = [];
      trendState.intervals.forEach(function (iv, intervalIndex) {
        var fromLabel = formatDate(iv.from);
        var toLabel = formatDate(iv.to);
        if (fromLabel === toLabel) {
          fromLabel = iv.from_source || fromLabel;
          toLabel = iv.to_source || toLabel;
        }
        parts.push(
          '<details class="trend-interval" data-interval="' + intervalIndex + '"><summary>' +
            '<span class="trend-range">' +
              escapeHtml(fromLabel) + " → " + escapeHtml(toLabel) +
            "</span>" +
            '<span class="change-count change-count-added">+' + iv.added.length + "</span>" +
            '<span class="change-count change-count-removed">−' + iv.removed.length + "</span>" +
            '<span class="change-count change-count-modified">~' + iv.modified.length + "</span>" +
          "</summary>" +
          '<div class="trend-interval-body" data-interval="' + intervalIndex + '"></div>' +
          "</details>"
        );
      });
      if (payload.trend.capped) {
        parts.push(
          '<p class="trend-capped ui">Window capped at the most recent snapshots; ' +
          "older history not shown.</p>"
        );
      }
      $trendLog.innerHTML = parts.join("");
    }

    function initTrend() {
      if (trendState.initialized || !$trendView || !payload.trend) return;
      trendState.initialized = true;
      trendState.intervals = payload.trend.intervals.slice(0, TREND_INTERVAL_CAP);
      trendState.revealed = trendState.intervals.map(function () {
        return {added: TREND_ID_BATCH_SIZE, removed: TREND_ID_BATCH_SIZE, modified: TREND_ID_BATCH_SIZE};
      });
      renderTrendLog();

      // toggle does not bubble, so listen during capture. One delegated
      // listener covers every lazily created interval.
      $trendView.addEventListener("toggle", function (event) {
        var details = event.target.closest("details.trend-interval");
        if (!details || !details.open) return;
        if (details.querySelector(".trend-interval-body").getAttribute("data-rendered")) return;
        renderTrendInterval(Number(details.getAttribute("data-interval")));
      }, true);
      $trendView.addEventListener("click", function (event) {
        var summary = event.target.closest("summary");
        if (summary) {
          var interval = summary.closest("details.trend-interval");
          if (interval && !interval.open) {
            renderTrendInterval(Number(interval.getAttribute("data-interval")));
          }
        }
        var button = event.target.closest("button.trend-show-next");
        if (!button) return;
        var intervalIndex = Number(button.getAttribute("data-interval"));
        var kind = button.getAttribute("data-kind");
        trendState.revealed[intervalIndex][kind] += TREND_ID_BATCH_SIZE;
        renderTrendInterval(intervalIndex);
      });
    }

    return Object.freeze({ init: initTrend });
  }

  window.SdrVisualizerTrend = Object.freeze({ create: create });
})();
