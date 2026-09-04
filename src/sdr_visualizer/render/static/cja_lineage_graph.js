(() => {
  "use strict";

  const SVG_NS = "http:" + "//www.w3.org/2000/svg";
  const CAMERA_MIN_WIDTH = 240;
  const READABLE_CAMERA_WIDTH = 360;
  const JOURNEY_LIMIT = 3;

  function create(context) {
    const {
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
    } = context;

    function truncateLabel(value, limit = 24) {
      const points = Array.from(value);
      return points.length > limit ? `${points.slice(0, limit - 3).join("")}…` : value;
    }

    function roundedPathData(points, radius = 18) {
      const distinct = points.filter(
        (point, index) =>
          index === 0 ||
          point[0] !== points[index - 1][0] ||
          point[1] !== points[index - 1][1]
      );
      if (distinct.length < 3) {
        return distinct
          .map((point, index) => `${index === 0 ? "M" : "L"}${point[0]} ${point[1]}`)
          .join(" ");
      }
      const commands = [`M${distinct[0][0]} ${distinct[0][1]}`];
      for (let index = 1; index < distinct.length - 1; index += 1) {
        const previous = distinct[index - 1];
        const current = distinct[index];
        const next = distinct[index + 1];
        const incoming = Math.hypot(current[0] - previous[0], current[1] - previous[1]);
        const outgoing = Math.hypot(next[0] - current[0], next[1] - current[1]);
        const bend = Math.min(radius, incoming / 2, outgoing / 2);
        const before = [
          current[0] + ((previous[0] - current[0]) * bend) / incoming,
          current[1] + ((previous[1] - current[1]) * bend) / incoming,
        ];
        const after = [
          current[0] + ((next[0] - current[0]) * bend) / outgoing,
          current[1] + ((next[1] - current[1]) * bend) / outgoing,
        ];
        commands.push(
          `L${before[0]} ${before[1]}`,
          `Q${current[0]} ${current[1]} ${after[0]} ${after[1]}`
        );
      }
      const last = distinct[distinct.length - 1];
      commands.push(`L${last[0]} ${last[1]}`);
      return commands.join(" ");
    }

    function combinedPathData(first, second) {
      return roundedPathData([...first.points, ...second.points]);
    }

    function svgDefinitions() {
      const defs = document.createElementNS(SVG_NS, "defs");
      for (const [id, deviation] of [
        ["lineage-comet-glow", "6"],
        ["lineage-node-glow", "3"],
      ]) {
        const filter = document.createElementNS(SVG_NS, "filter");
        filter.id = id;
        for (const [name, value] of [
          ["x", "-40%"], ["y", "-40%"], ["width", "180%"], ["height", "180%"],
        ]) filter.setAttribute(name, value);
        const blur = document.createElementNS(SVG_NS, "feGaussianBlur");
        blur.setAttribute("stdDeviation", deviation);
        blur.setAttribute("result", "blur");
        const merge = document.createElementNS(SVG_NS, "feMerge");
        for (const input of ["blur", "SourceGraphic"]) {
          const node = document.createElementNS(SVG_NS, "feMergeNode");
          node.setAttribute("in", input);
          merge.appendChild(node);
        }
        filter.append(blur, merge);
        defs.appendChild(filter);
      }
      for (const [id, className] of [
        ["lineage-arrow-dataset", "lineage-arrow--dataset"],
        ["lineage-arrow-data-view", "lineage-arrow--data-view"],
      ]) {
        const marker = document.createElementNS(SVG_NS, "marker");
        marker.id = id;
        for (const [name, value] of [
          ["viewBox", "0 0 7 6"], ["refX", "6"], ["refY", "3"],
          ["markerWidth", "7"], ["markerHeight", "6"], ["orient", "auto"],
        ]) marker.setAttribute(name, value);
        const arrow = document.createElementNS(SVG_NS, "path");
        arrow.setAttribute("d", "M0 0 L7 3 L0 6 Z");
        arrow.classList.add("lineage-arrow", className);
        marker.appendChild(arrow);
        defs.appendChild(marker);
      }
      return defs;
    }

    function buildColumnLayer(canvas) {
      const bands = document.createElementNS(SVG_NS, "g");
      bands.classList.add("lineage-columns");
      for (const column of canvas.columns) {
        const group = document.createElementNS(SVG_NS, "g");
        group.classList.add("lineage-column", `lineage-column--${column.kind}`);
        const band = document.createElementNS(SVG_NS, "rect");
        band.classList.add("lineage-column-band");
        for (const [name, value] of [
          ["x", column.x - 22], ["y", 18], ["width", column.width + 44],
          ["height", Math.max(164, canvas.height - 36)], ["rx", 28],
        ]) band.setAttribute(name, String(value));
        group.appendChild(band);
        bands.appendChild(group);
      }
      return bands;
    }

    function centerY(node) {
      return node.y + node.height / 2;
    }

    function closestJourneyForConnection(connectionId, nodes, edgeByPair) {
      const connectionRef = `connection:${connectionId}`;
      const connectionNode = nodes.get(connectionRef);
      if (!connectionNode) return null;
      const datasets = (payload.adjacency.dataset_ids_by_connection[connectionId] || [])
        .map((id) => ({ id, node: nodes.get(`dataset:${id}`) }))
        .filter((item) => item.node)
        .sort((left, right) => centerY(left.node) - centerY(right.node));
      const views = (payload.adjacency.data_view_ids_by_connection[connectionId] || [])
        .map((id) => ({ id, node: nodes.get(`data-view:${id}`) }))
        .filter((item) => item.node)
        .sort((left, right) => centerY(left.node) - centerY(right.node));
      let datasetIndex = 0;
      let viewIndex = 0;
      let best = null;
      while (datasetIndex < datasets.length && viewIndex < views.length) {
        state.ambientJourneyComparisons += 1;
        const dataset = datasets[datasetIndex];
        const view = views[viewIndex];
        const datasetRef = `dataset:${dataset.id}`;
        const viewRef = `data-view:${view.id}`;
        const first = edgeByPair.get(`${datasetRef}\n${connectionRef}`);
        const second = edgeByPair.get(`${connectionRef}\n${viewRef}`);
        const centers = [centerY(dataset.node), centerY(connectionNode), centerY(view.node)];
        const score = Math.max(...centers) - Math.min(...centers);
        const label = `${entityLabel("dataset", dataset.id)} to ${entityLabel("connection", connectionId)} to ${entityLabel("data-view", view.id)}`;
        if (first && second && (!best || score < best.score || (score === best.score && label.localeCompare(best.label) < 0))) {
          best = {
            score,
            connectionId,
            refs: [datasetRef, connectionRef, viewRef],
            edges: [first, second],
            label,
          };
        }
        if (centerY(dataset.node) <= centerY(view.node)) datasetIndex += 1;
        else viewIndex += 1;
      }
      return best;
    }

    function ambientJourneys(canvas, edges) {
      state.ambientJourneyComparisons = 0;
      const nodes = new Map(canvas.nodes.map((node) => [node.ref, node]));
      const edgeByPair = new Map(
        edges.map((edge) => [`${edge.source_ref}\n${edge.target_ref}`, edge])
      );
      const candidates = payload.entities.connections
        .map((connection) => closestJourneyForConnection(connection.id, nodes, edgeByPair))
        .filter(Boolean)
        .sort((left, right) => left.score - right.score || left.label.localeCompare(right.label));
      return candidates.slice(0, JOURNEY_LIMIT);
    }

    function buildSvgNode(node, view, index, defs, journeyRefs) {
      const group = document.createElementNS(SVG_NS, "g");
      group.classList.add("lineage-node", `lineage-node--${node.kind}`);
      group.dataset.ref = node.ref;
      if (node.entity_id === view.id || node.entity_id === state.activeDatasetId) {
        group.classList.add("is-selected");
      }
      if (journeyRefs.has(node.ref)) group.classList.add("is-journey-node");
      group.setAttribute("transform", `translate(${node.x} ${node.y})`);
      const label = entityLabel(node.kind, node.entity_id);
      const kindLabel = node.kind === "data-view"
        ? "Data view"
        : node.kind[0].toUpperCase() + node.kind.slice(1);
      group.setAttribute("role", "img");
      group.setAttribute("aria-label", `${kindLabel}: ${label}. Stable identifier: ${node.entity_id}.`);
      const shape = document.createElementNS(SVG_NS, "rect");
      shape.setAttribute("width", String(node.width));
      shape.setAttribute("height", String(node.height));
      shape.setAttribute("rx", node.kind === "dataset" ? "18" : "12");
      shape.classList.add("lineage-node-shape");
      const accent = document.createElementNS(SVG_NS, "rect");
      accent.classList.add("lineage-node-accent");
      for (const [name, value] of [
        ["x", 0], ["y", 10], ["width", 6], ["height", node.height - 20], ["rx", 3],
      ]) accent.setAttribute(name, String(value));
      const icon = document.createElementNS(SVG_NS, "circle");
      icon.classList.add("lineage-node-icon");
      icon.setAttribute("cx", "25");
      icon.setAttribute("cy", String(node.height / 2));
      icon.setAttribute("r", "12");
      const glyph = document.createElementNS(SVG_NS, "text");
      glyph.classList.add("lineage-node-glyph");
      glyph.setAttribute("x", "25");
      glyph.setAttribute("y", String(node.height / 2 + 4));
      glyph.setAttribute("text-anchor", "middle");
      glyph.textContent = node.kind === "dataset" ? "D" : node.kind === "connection" ? "C" : "V";
      const clip = document.createElementNS(SVG_NS, "clipPath");
      clip.id = `lineage-label-clip-${index}`;
      const clipRect = document.createElementNS(SVG_NS, "rect");
      for (const [name, value] of [
        ["x", 44], ["y", 6], ["width", node.width - 54], ["height", node.height - 12],
      ]) clipRect.setAttribute(name, String(value));
      clip.appendChild(clipRect);
      defs.appendChild(clip);
      const text = document.createElementNS(SVG_NS, "text");
      text.classList.add("lineage-node-label");
      text.setAttribute("x", "45");
      text.setAttribute("y", "28");
      text.setAttribute("clip-path", `url(#${clip.id})`);
      text.textContent = truncateLabel(label);
      const kind = document.createElementNS(SVG_NS, "text");
      kind.classList.add("lineage-node-kind");
      kind.setAttribute("x", "45");
      kind.setAttribute("y", "47");
      kind.textContent = node.kind === "dataset" ? "AEP DATASET" : node.kind === "connection" ? "CJA CONNECTION" : "CJA DATA VIEW";
      const title = document.createElementNS(SVG_NS, "title");
      title.textContent = `${kindLabel}: ${label}; ${node.entity_id}`;
      group.append(title, shape, accent, icon, glyph, text, kind);
      return group;
    }

    function buildSvg(canvas, nodes, edges, view, withAmbientFlow = false) {
      const svg = document.createElementNS(SVG_NS, "svg");
      svg.classList.add("lineage-svg");
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-labelledby", "lineage-svg-title lineage-svg-description");
      const defs = svgDefinitions();
      const title = document.createElementNS(SVG_NS, "title");
      title.id = "lineage-svg-title";
      title.textContent = state.fullGraph ? "Full CJA lineage topology" : `Selected lineage for ${view.name}`;
      const description = document.createElementNS(SVG_NS, "desc");
      description.id = "lineage-svg-description";
      description.textContent = state.fullGraph
        ? `${nodes.length} entities and ${edges.length} relationships.`
        : `Bounded parent, dataset, and sibling neighborhood for ${view.name}. Text details follow the diagram.`;
      if (state.globalRoleFilter !== "all") {
        svg.classList.add("has-global-role-filter");
        description.textContent += " Non-matching entities and relationships are visually muted by the active Connection role highlight.";
      }
      const journeys = withAmbientFlow && state.globalRoleFilter === "all"
        ? ambientJourneys(canvas, edges)
        : [];
      const journeyRefs = new Set(journeys.flatMap((journey) => journey.refs));
      if (state.activeDatasetId && view.connection_id) {
        journeyRefs.add(`dataset:${state.activeDatasetId}`);
        journeyRefs.add(`connection:${view.connection_id}`);
        journeyRefs.add(`data-view:${view.id}`);
      }
      if (journeys.length) {
        description.textContent += ` ${journeys.length} representative dataset-to-data-view journeys are highlighted; their motion is illustrative and does not measure traffic volume.`;
      }
      svg.append(title, description, defs, buildColumnLayer(canvas));
      for (const edge of edges) {
        const path = document.createElementNS(SVG_NS, "path");
        path.setAttribute("d", roundedPathData(edge.points));
        path.setAttribute("fill", "none");
        path.classList.add("lineage-edge", `lineage-edge--${edge.kind}`);
        let globalRoleMatch = true;
        if (edge.kind === "dataset-connection") {
          const datasetId = edge.source_ref.slice("dataset:".length);
          const connectionId = edge.target_ref.slice("connection:".length);
          const role = relationshipRole(datasetId, connectionId);
          globalRoleMatch = role.filterKey === state.globalRoleFilter;
          if (role.label) {
            path.classList.add(`lineage-edge-role--${role.styleKey}`);
            path.dataset.connectionRole = role.label;
            const edgeTitle = document.createElementNS(SVG_NS, "title");
            edgeTitle.textContent = `${entityLabel("dataset", datasetId)} to ${entityLabel("connection", connectionId)}. Connection role: ${role.label}.`;
            path.appendChild(edgeTitle);
          }
        } else if (state.globalRoleFilter !== "all") {
          const connectionId = edge.source_ref.slice("connection:".length);
          globalRoleMatch = entityMatchesGlobalRole("connection", connectionId);
        }
        if (state.globalRoleFilter !== "all") {
          path.classList.add(
            globalRoleMatch ? "is-global-role-match" : "is-global-role-muted"
          );
        }
        path.setAttribute("marker-end", edge.kind === "dataset-connection" ? "url(#lineage-arrow-dataset)" : "url(#lineage-arrow-data-view)");
        if (isRouteEdge(edge, view)) path.classList.add("is-route");
        svg.appendChild(path);
      }
      for (const [index, journey] of journeys.entries()) {
        const routePath = combinedPathData(journey.edges[0], journey.edges[1]);
        const guide = document.createElementNS(SVG_NS, "path");
        guide.setAttribute("d", routePath);
        guide.classList.add("journey-guide", `journey-guide--${index}`);
        guide.setAttribute("filter", "url(#lineage-comet-glow)");
        guide.setAttribute("aria-hidden", "true");
        svg.appendChild(guide);
        if (!reducedMotion.matches) {
          for (let tail = 3; tail >= 0; tail -= 1) {
            const marker = document.createElementNS(SVG_NS, "circle");
            marker.classList.add("journey-comet", `journey-comet--${index}`);
            marker.setAttribute("r", String(3.5 + (3 - tail) * 1.5));
            marker.setAttribute("opacity", String(0.22 + (3 - tail) * 0.2));
            marker.setAttribute("filter", "url(#lineage-comet-glow)");
            marker.setAttribute("aria-hidden", "true");
            const motion = document.createElementNS(SVG_NS, "animateMotion");
            motion.setAttribute("path", routePath);
            motion.setAttribute("dur", `${4.6 + index * 0.7}s`);
            motion.setAttribute("begin", `-${index * 0.8 + tail * 0.09}s`);
            motion.setAttribute("repeatCount", "indefinite");
            marker.appendChild(motion);
            svg.appendChild(marker);
          }
        }
      }
      for (const [index, node] of nodes.entries()) {
        const group = buildSvgNode(node, view, index, defs, journeyRefs);
        if (state.globalRoleFilter !== "all") {
          group.classList.add(
            entityMatchesGlobalRole(node.kind, node.entity_id)
              ? "is-global-role-match"
              : "is-global-role-muted"
          );
        }
        svg.appendChild(group);
      }
      if (state.activeDatasetId && !reducedMotion.matches && !state.fullGraph) {
        const routeEdges = edges.filter((edge) => isRouteEdge(edge, view));
        if (routeEdges.length === 2) {
          const marker = document.createElementNS(SVG_NS, "circle");
          marker.classList.add("route-marker");
          marker.setAttribute("r", "8");
          marker.setAttribute("aria-hidden", "true");
          const motion = document.createElementNS(SVG_NS, "animateMotion");
          motion.setAttribute("path", combinedPathData(routeEdges[0], routeEdges[1]));
          motion.setAttribute("dur", "4s");
          motion.setAttribute("repeatCount", "indefinite");
          marker.appendChild(motion);
          svg.appendChild(marker);
          if (state.paused) svg.pauseAnimations();
        }
      }
      return { svg, journeys };
    }

    function stageDimensions() {
      const style = getComputedStyle(stage);
      return {
        width: Math.max(1, stage.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)),
        height: Math.max(1, stage.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)),
      };
    }

    function clampCamera(camera) {
      const canvas = state.activeCanvas;
      if (!canvas) return camera;
      const width = Math.min(canvas.width, Math.max(CAMERA_MIN_WIDTH, camera.width));
      const dimensions = stageDimensions();
      const height = Math.min(canvas.height, (width * dimensions.height) / dimensions.width);
      return {
        x: Math.min(Math.max(0, camera.x), Math.max(0, canvas.width - width)),
        y: Math.min(Math.max(0, camera.y), Math.max(0, canvas.height - height)),
        width,
        height,
      };
    }

    function applyCamera() {
      const svg = stage.querySelector("svg");
      if (!svg || !state.camera) return;
      state.camera = clampCamera(state.camera);
      const { x, y, width, height } = state.camera;
      svg.setAttribute("viewBox", `${x} ${y} ${width} ${height}`);
    }

    function initialCamera(canvas, focusRefs) {
      const dimensions = stageDimensions();
      const width = Math.min(
        canvas.width,
        Math.max(READABLE_CAMERA_WIDTH, (dimensions.width * 15.5) / 12.5)
      );
      const height = Math.min(canvas.height, (width * dimensions.height) / dimensions.width);
      const focusNodes = focusRefs
        .map((ref) => canvas.nodes.find((node) => node.ref === ref))
        .filter(Boolean);
      const anchor = focusNodes[0] || canvas.nodes[0];
      const centerX = anchor ? anchor.x + anchor.width / 2 : canvas.width / 2;
      const centerYValue = anchor ? anchor.y + anchor.height / 2 : height / 2;
      return clampCamera({ x: centerX - width / 2, y: centerYValue - height / 2, width, height });
    }

    function configureDiagramControls(journeys) {
      el.cameraControls.hidden = false;
      el.stageToolbar.hidden = false;
      el.stageKey.hidden = false;
      el.keyDatasets.textContent = String(stage.querySelectorAll(".lineage-node--dataset").length);
      el.keyConnections.textContent = String(stage.querySelectorAll(".lineage-node--connection").length);
      el.keyDataViews.textContent = String(stage.querySelectorAll(".lineage-node--data-view").length);
      const hasJourneys = journeys.length > 0;
      const hasMotion = state.fullGraph ? hasJourneys : Boolean(state.activeDatasetId);
      const paused = state.fullGraph ? state.flowPaused : state.paused;
      el.flowPause.hidden = reducedMotion.matches || !hasMotion;
      el.flowPause.setAttribute("aria-pressed", String(paused));
      el.flowPause.textContent = paused ? "Resume flow" : "Pause flow";
      el.themeToggle.setAttribute("aria-pressed", String(state.theme === "dark"));
      el.themeToggle.textContent = state.theme === "dark" ? "Light mode" : "Dark mode";
      stage.classList.toggle("is-flow-paused", paused);
      el.motionCopy.hidden = !state.fullGraph || !hasJourneys;
      if (state.fullGraph && hasJourneys) {
        el.motionCopy.textContent = reducedMotion.matches
          ? `${journeys.length} representative journeys remain statically highlighted; animation is omitted by reduced-motion preference.`
          : `${journeys.length} representative journeys glow across the topology. Motion shows lineage direction only; it does not encode volume, latency, or health.`;
      }
    }

    function mountSvg(canvas, built, focusRefs) {
      stage.appendChild(built.svg);
      stage.classList.add("has-camera");
      state.activeCanvas = canvas;
      state.initialCamera = initialCamera(canvas, focusRefs);
      state.camera = { ...state.initialCamera };
      applyCamera();
      configureDiagramControls(built.journeys);
    }

    function clearPan() {
      if (state.pointer && stage.hasPointerCapture(state.pointer.id)) {
        stage.releasePointerCapture(state.pointer.id);
      }
      state.pointer = null;
      stage.classList.remove("is-panning");
    }

    function clearDiagramControls() {
      clearPan();
      stage.classList.remove("has-camera", "is-flow-paused");
      state.activeCanvas = null;
      state.initialCamera = null;
      state.camera = null;
      el.cameraControls.hidden = true;
      el.motionCopy.hidden = true;
      el.flowPause.hidden = true;
      el.stageToolbar.hidden = true;
      el.stageKey.hidden = true;
    }

    function zoomCamera(factor) {
      if (!state.camera || !state.activeCanvas) return;
      const centerX = state.camera.x + state.camera.width / 2;
      const centerYValue = state.camera.y + state.camera.height / 2;
      const width = Math.min(state.activeCanvas.width, Math.max(CAMERA_MIN_WIDTH, state.camera.width * factor));
      const dimensions = stageDimensions();
      const height = Math.min(state.activeCanvas.height, (width * dimensions.height) / dimensions.width);
      state.camera = clampCamera({ x: centerX - width / 2, y: centerYValue - height / 2, width, height });
      applyCamera();
    }

    function panCamera(horizontal, vertical) {
      if (!state.camera) return;
      state.camera.x += state.camera.width * horizontal;
      state.camera.y += state.camera.height * vertical;
      applyCamera();
    }

    function edgePriority(edge, view) {
      if (isRouteEdge(edge, view)) return 2;
      return edge.source_ref === `connection:${view.connection_id}` && edge.target_ref === `data-view:${view.id}` ? 1 : 0;
    }

    function compactCanvas(canvas, retainedNodes, retainedEdges) {
      const byRef = new Map();
      const nodes = [];
      for (const kind of ["dataset", "connection", "data-view"]) {
        const preparedSlots = canvas.nodes.filter((node) => node.kind === kind).sort((a, b) => a.y - b.y);
        const retained = retainedNodes.filter((node) => node.kind === kind).sort((a, b) => a.y - b.y);
        for (const [index, node] of retained.entries()) {
          const compacted = { ...node, y: preparedSlots[index].y };
          nodes.push(compacted);
          byRef.set(compacted.ref, compacted);
        }
      }
      const edges = retainedEdges.map((edge) => {
        const source = byRef.get(edge.source_ref);
        const target = byRef.get(edge.target_ref);
        const start = [source.x + source.width, source.y + source.height / 2];
        const end = [target.x, target.y + target.height / 2];
        const laneX = edge.points[1][0];
        return { ...edge, points: [start, [laneX, start[1]], [laneX, end[1]], end] };
      });
      const bottomMargin = Math.max(0, ...canvas.columns.map((column) => canvas.height - column.bottom));
      const height = Math.max(200, Math.max(0, ...nodes.map((node) => node.y + node.height)) + bottomMargin);
      return {
        ...canvas,
        height,
        columns: canvas.columns.map((column) => ({ ...column, bottom: height - bottomMargin })),
        nodes,
        edges,
      };
    }

    function renderLocalGraph() {
      const view = selectedView();
      const canvas = view && view.connection_id ? maps.local.get(view.connection_id) : null;
      setFullGraph(false);
      empty(stage);
      stage.dataset.state = "data-view";
      if (!canvas || !view.connection_id) {
        clearDiagramControls();
        addText(stage, "p", "A local diagram is unavailable because this data view has no resolved parent connection.", "availability availability--missing");
        return;
      }
      const required = new Set([`data-view:${view.id}`, `connection:${view.connection_id}`]);
      if (state.activeDatasetId) required.add(`dataset:${state.activeDatasetId}`);
      const allowed = new Set(required);
      for (const node of canvas.nodes) {
        if (allowed.size >= 100) break;
        allowed.add(node.ref);
      }
      const edges = canvas.edges
        .filter((edge) => allowed.has(edge.source_ref) && allowed.has(edge.target_ref))
        .sort((left, right) => edgePriority(right, view) - edgePriority(left, view))
        .slice(0, 100);
      const bounded = compactCanvas(canvas, canvas.nodes.filter((node) => allowed.has(node.ref)), edges);
      const built = buildSvg(bounded, bounded.nodes, bounded.edges, view);
      const focusRefs = [`connection:${view.connection_id}`, `data-view:${view.id}`];
      if (state.activeDatasetId) focusRefs.unshift(`dataset:${state.activeDatasetId}`);
      mountSvg(bounded, built, focusRefs);
      if (canvas.nodes.length > allowed.size) {
        addText(stage, "p", `${canvas.nodes.length - allowed.size} additional local nodes are omitted from this bounded diagram; complete datasets and siblings remain listed below.`, "diagram-note");
      }
    }

    function drawFullGraph() {
      setFullGraph(true);
      el.showOverview.setAttribute("aria-pressed", "false");
      state.paused = false;
      state.flowPaused = false;
      empty(stage);
      stage.dataset.state = "full-graph";
      const view = selectedView() || { id: "", name: "full topology", connection_id: null };
      const canvas = payload.geometry.global;
      const built = buildSvg(canvas, canvas.nodes, canvas.edges, view, true);
      const focusRefs = state.activeDatasetId && view.connection_id
        ? [`dataset:${state.activeDatasetId}`, `connection:${view.connection_id}`, `data-view:${view.id}`]
        : built.journeys.length ? built.journeys[0].refs : [];
      mountSvg(canvas, built, focusRefs);
      if (selectedView()) renderRouteControls(selectedView());
      setStatus(`Full topology drawn: ${canvas.nodes.length} nodes and ${canvas.edges.length} relationships. The camera opens at readable scale; pan or use the navigation controls to inspect the complete graph.`);
    }

    return Object.freeze({
      applyCamera,
      clearDiagramControls,
      clearPan,
      drawFullGraph,
      panCamera,
      renderLocalGraph,
      stageDimensions,
      zoomCamera,
    });
  }

  window.SdrCjaLineageGraph = Object.freeze({ create });
})();
