from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field

FLOWCHART_HEADER_RE = re.compile(r"^\s*(?:flowchart|graph)\s+([A-Za-z]{2})\b", re.IGNORECASE)
NODE_ID_RE = re.compile(r"^\s*([A-Za-z_][\w.-]*)")
ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
NODE_GAP_X = 42
NODE_GAP_Y = 34
LAYER_GAP_X = 82
LAYER_GAP_Y = 72
PADDING = 28
MIN_NODE_W = 112
MAX_NODE_W = 198
TEXT_LINE_H = 15
TEXT_PAD_X = 18
TEXT_PAD_Y = 13


@dataclass(slots=True)
class MermaidNode:
    node_id: str
    label: str
    shape: str = "rect"
    order: int = 0
    x: float = 0
    y: float = 0
    width: float = MIN_NODE_W
    height: float = 46
    lines: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MermaidEdge:
    source: str
    target: str
    label: str = ""
    kind: str = "arrow"


@dataclass(slots=True)
class MermaidDiagram:
    direction: str
    nodes: dict[str, MermaidNode] = field(default_factory=dict)
    edges: list[MermaidEdge] = field(default_factory=list)


@dataclass(slots=True)
class ParsedEdge:
    left: str
    right: str
    label: str = ""
    kind: str = "arrow"


def render_mermaid_to_svg(source: str) -> str | None:
    """Render a practical, offline subset of Mermaid flowcharts to SVG.

    The project intentionally avoids online Mermaid/CDN dependencies during PDF
    generation. This renderer covers the common flowchart syntax used in project
    reports and guides: ``flowchart``/``graph`` declarations, TD/TB/LR/RL/BT
    directions, rectangle/rounded/circle/diamond/parallelogram nodes, and the
    usual solid, dotted, thick, and labelled edges.
    """
    diagram = parse_mermaid_flowchart(source)
    if not diagram or not diagram.nodes:
        return None
    # SHA-1 is used only for a deterministic SVG marker ID, not security.
    marker_id = "md2pdf-mermaid-arrow-" + hashlib.sha1(
        source.encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:10]
    return _diagram_to_svg(diagram, marker_id=marker_id)


def parse_mermaid_flowchart(source: str) -> MermaidDiagram | None:
    statements = _logical_statements(source)
    direction = "TD"
    body_start = 0
    for index, statement in enumerate(statements):
        match = FLOWCHART_HEADER_RE.match(statement)
        if match:
            direction = _normalize_direction(match.group(1))
            body_start = index + 1
            break
    else:
        return None

    diagram = MermaidDiagram(direction=direction)
    for statement in statements[body_start:]:
        stripped = statement.strip()
        if not stripped or _is_unsupported_control_line(stripped):
            continue
        for segment in _split_chained_edges(stripped):
            parsed = _parse_edge(segment)
            if parsed:
                left = _parse_node_expr(parsed.left)
                right = _parse_node_expr(parsed.right)
                if left and right:
                    _upsert_node(diagram, left)
                    _upsert_node(diagram, right)
                    diagram.edges.append(
                        MermaidEdge(left.node_id, right.node_id, parsed.label, parsed.kind)
                    )
                continue
            node = _parse_node_expr(segment)
            if node:
                _upsert_node(diagram, node)
    return diagram


def _logical_statements(source: str) -> list[str]:
    statements: list[str] = []
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if "%%" in line:
            line = line.split("%%", 1)[0].strip()
        for part in line.split(";"):
            part = part.strip()
            if part:
                statements.append(part)
    return statements


def _normalize_direction(value: str) -> str:
    direction = value.strip().upper()
    if direction == "TB":
        return "TD"
    return direction if direction in {"TD", "BT", "LR", "RL"} else "TD"


def _is_unsupported_control_line(line: str) -> bool:
    lowered = line.lower()
    prefixes = (
        "subgraph ",
        "end",
        "classdef ",
        "class ",
        "style ",
        "click ",
        "linkstyle ",
        "accdescr",
        "acctitle",
    )
    return lowered.startswith(prefixes)


def _split_chained_edges(statement: str) -> list[str]:
    # Keep the implementation conservative: most project documentation uses one
    # edge per line. A small helper still expands A --> B --> C into two edges.
    parts = re.split(r"\s+(-->|---|-.->|==>)\s+", statement)
    if len(parts) < 5:
        return [statement]
    result: list[str] = []
    current = parts[0]
    index = 1
    while index + 1 < len(parts):
        op = parts[index]
        right = parts[index + 1]
        result.append(f"{current} {op} {right}")
        current = right
        index += 2
    return result


def _parse_edge(line: str) -> ParsedEdge | None:
    patterns = [
        (re.compile(r"^(?P<left>.*?)\s*-->\|(?P<label>[^|]+)\|\s*(?P<right>.+)$"), "arrow"),
        (re.compile(r"^(?P<left>.*?)\s*==>\|(?P<label>[^|]+)\|\s*(?P<right>.+)$"), "thick"),
        (re.compile(r"^(?P<left>.*?)\s*-\.->\|(?P<label>[^|]+)\|\s*(?P<right>.+)$"), "dotted"),
        (re.compile(r"^(?P<left>.*?)\s*--\s*(?P<label>[^-]+?)\s*-->\s*(?P<right>.+)$"), "arrow"),
        (re.compile(r"^(?P<left>.*?)\s*-\.\s*(?P<label>[^.]+?)\s*\.->\s*(?P<right>.+)$"), "dotted"),
        (re.compile(r"^(?P<left>.*?)\s*-\.->\s*(?P<right>.+)$"), "dotted"),
        (re.compile(r"^(?P<left>.*?)\s*==>\s*(?P<right>.+)$"), "thick"),
        (re.compile(r"^(?P<left>.*?)\s*-->\s*(?P<right>.+)$"), "arrow"),
        (re.compile(r"^(?P<left>.*?)\s*---\s*(?P<right>.+)$"), "line"),
    ]
    for pattern, kind in patterns:
        match = pattern.match(line)
        if not match:
            continue
        left = match.group("left").strip()
        right = match.group("right").strip()
        if not left or not right:
            return None
        label = (match.groupdict().get("label") or "").strip()
        return ParsedEdge(left=left, right=right, label=label, kind=kind)
    return None


def _parse_node_expr(expr: str) -> MermaidNode | None:
    match = NODE_ID_RE.match(expr.strip())
    if not match:
        return None
    node_id = match.group(1)
    rest = expr[match.end() :].strip()
    label = node_id
    shape = "rect"

    patterns: list[tuple[str, str, str, str]] = [
        ("[[", "]]", "subroutine", "subroutine"),
        ("{{", "}}", "hexagon", "hexagon"),
        ("((", "))", "circle", "circle"),
        ("[(", ")]", "database", "database"),
        ("([", "])", "stadium", "stadium"),
        ("[/", "/]", "parallelogram", "parallelogram"),
        ("[\\", "\\]", "parallelogram", "parallelogram"),
        ("[", "]", "rect", "rect"),
        ("(", ")", "round", "round"),
        ("{", "}", "diamond", "diamond"),
    ]
    for opener, closer, _name, candidate_shape in patterns:
        if rest.startswith(opener):
            end = rest.find(closer, len(opener))
            if end != -1:
                label = rest[len(opener) : end]
                shape = candidate_shape
            break

    return MermaidNode(node_id=node_id, label=_clean_label(label), shape=shape)


def _clean_label(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1]
    return re.sub(r"\s+", " ", text).strip() or "node"


def _upsert_node(diagram: MermaidDiagram, node: MermaidNode) -> None:
    existing = diagram.nodes.get(node.node_id)
    if existing:
        if node.label != node.node_id:
            existing.label = node.label
        if node.shape != "rect":
            existing.shape = node.shape
        return
    node.order = len(diagram.nodes)
    diagram.nodes[node.node_id] = node


def _diagram_to_svg(diagram: MermaidDiagram, *, marker_id: str) -> str:
    ranks = _assign_ranks(diagram)
    layers: dict[int, list[MermaidNode]] = {}
    for node in sorted(diagram.nodes.values(), key=lambda item: item.order):
        _measure_node(node)
        layers.setdefault(ranks.get(node.node_id, 0), []).append(node)

    direction = diagram.direction
    horizontal = direction in {"LR", "RL"}
    reverse = direction in {"BT", "RL"}
    ordered_ranks = sorted(layers)
    if reverse:
        ordered_ranks = list(reversed(ordered_ranks))

    width, height = _place_nodes(layers, ordered_ranks, horizontal=horizontal)
    node_svg = "\n".join(_node_svg(node) for node in sorted(diagram.nodes.values(), key=lambda item: item.order))
    edge_svg = "\n".join(_edge_svg(edge, diagram.nodes, horizontal=horizontal, marker_id=marker_id) for edge in diagram.edges)
    safe_title = html.escape("Mermaid flowchart")
    return f'''<svg class="md2pdf-mermaid-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="{safe_title}">
  <defs>
    <marker id="{html.escape(marker_id)}" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L9,4.5 L0,9 z" class="md2pdf-mermaid-arrow-head" />
    </marker>
  </defs>
  <rect class="md2pdf-mermaid-bg" x="1" y="1" width="{width - 2:.0f}" height="{height - 2:.0f}" rx="14" />
  <g class="md2pdf-mermaid-edges">{edge_svg}</g>
  <g class="md2pdf-mermaid-nodes">{node_svg}</g>
</svg>'''


def _assign_ranks(diagram: MermaidDiagram) -> dict[str, int]:
    ranks = {node_id: 0 for node_id in diagram.nodes}
    incoming = {node_id: 0 for node_id in diagram.nodes}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in diagram.nodes}
    for edge in diagram.edges:
        if edge.source not in diagram.nodes or edge.target not in diagram.nodes:
            continue
        incoming[edge.target] += 1
        outgoing[edge.source].append(edge.target)

    queue = [node_id for node_id, node in sorted(diagram.nodes.items(), key=lambda item: item[1].order) if incoming[node_id] == 0]
    if not queue:
        queue = [node_id for node_id, _node in sorted(diagram.nodes.items(), key=lambda item: item[1].order)]

    processed: set[str] = set()
    all_nodes = [node_id for node_id, _node in sorted(diagram.nodes.items(), key=lambda item: item[1].order)]
    while len(processed) < len(diagram.nodes):
        if not queue:
            remaining = [node_id for node_id in all_nodes if node_id not in processed]
            if not remaining:
                break
            # Break cycles deterministically. The selected node keeps the best
            # rank discovered so far; its outgoing edges can still push later
            # nodes into deeper layers.
            remaining.sort(key=lambda node_id: (incoming.get(node_id, 0), ranks.get(node_id, 0), diagram.nodes[node_id].order))
            queue.append(remaining[0])

        source = queue.pop(0)
        if source in processed:
            continue
        processed.add(source)
        for target in outgoing.get(source, []):
            if target in processed:
                continue
            ranks[target] = max(ranks[target], ranks[source] + 1)
            incoming[target] -= 1
            if incoming[target] <= 0:
                queue.append(target)
    return ranks


def _measure_node(node: MermaidNode) -> None:
    node.lines = _wrap_label(node.label)
    max_chars = max((len(line) for line in node.lines), default=4)
    node.width = min(MAX_NODE_W, max(MIN_NODE_W, max_chars * 7.2 + TEXT_PAD_X * 2))
    node.height = max(44, len(node.lines) * TEXT_LINE_H + TEXT_PAD_Y * 2)
    if node.shape == "circle":
        diameter = max(node.width, node.height, 66)
        node.width = node.height = min(max(diameter, 66), 128)
    if node.shape == "diamond":
        node.width = max(node.width + 18, 120)
        node.height = max(node.height + 16, 72)
    if node.shape in {"database", "hexagon", "subroutine", "stadium"}:
        node.width = max(node.width + 14, 124)
        node.height = max(node.height + 8, 58)


def _wrap_label(label: str, max_chars: int = 22) -> list[str]:
    words = label.split()
    if not words:
        return [label]
    lines: list[str] = []
    current = ""
    for word in words:
        if len(word) > max_chars:
            if current:
                lines.append(current)
                current = ""
            chunks = [word[i : i + max_chars] for i in range(0, len(word), max_chars)]
            lines.extend(chunks[:-1])
            current = chunks[-1]
            continue
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:4]


def _place_nodes(
    layers: dict[int, list[MermaidNode]], ordered_ranks: list[int], *, horizontal: bool
) -> tuple[float, float]:
    cursor = PADDING
    max_cross = 0.0
    layer_sizes: dict[int, float] = {}
    for rank in ordered_ranks:
        nodes = layers[rank]
        if horizontal:
            layer_sizes[rank] = max((node.width for node in nodes), default=MIN_NODE_W)
            cross = sum(node.height for node in nodes) + NODE_GAP_Y * max(0, len(nodes) - 1)
        else:
            layer_sizes[rank] = max((node.height for node in nodes), default=44)
            cross = sum(node.width for node in nodes) + NODE_GAP_X * max(0, len(nodes) - 1)
        max_cross = max(max_cross, cross)

    for rank in ordered_ranks:
        nodes = layers[rank]
        if horizontal:
            layer_w = layer_sizes[rank]
            total_h = sum(node.height for node in nodes) + NODE_GAP_Y * max(0, len(nodes) - 1)
            y = PADDING + (max_cross - total_h) / 2
            for node in nodes:
                node.x = cursor + (layer_w - node.width) / 2
                node.y = y
                y += node.height + NODE_GAP_Y
            cursor += layer_w + LAYER_GAP_X
        else:
            layer_h = layer_sizes[rank]
            total_w = sum(node.width for node in nodes) + NODE_GAP_X * max(0, len(nodes) - 1)
            x = PADDING + (max_cross - total_w) / 2
            for node in nodes:
                node.x = x
                node.y = cursor + (layer_h - node.height) / 2
                x += node.width + NODE_GAP_X
            cursor += layer_h + LAYER_GAP_Y

    main = max(cursor - (LAYER_GAP_X if horizontal else LAYER_GAP_Y) + PADDING, 160)
    cross = max_cross + PADDING * 2
    return (main, cross) if horizontal else (cross, main)


def _node_svg(node: MermaidNode) -> str:
    x, y, w, h = node.x, node.y, node.width, node.height
    safe_id = html.escape(node.node_id)
    text = _node_text_svg(node, x + w / 2, y + h / 2)
    if node.shape == "circle":
        shape = f'<ellipse class="md2pdf-mermaid-node-shape" cx="{x + w / 2:.1f}" cy="{y + h / 2:.1f}" rx="{w / 2:.1f}" ry="{h / 2:.1f}" />'
    elif node.shape == "diamond":
        points = f"{x + w / 2:.1f},{y:.1f} {x + w:.1f},{y + h / 2:.1f} {x + w / 2:.1f},{y + h:.1f} {x:.1f},{y + h / 2:.1f}"
        shape = f'<polygon class="md2pdf-mermaid-node-shape" points="{points}" />'
    elif node.shape == "hexagon":
        inset = min(26, w * 0.18)
        points = f"{x + inset:.1f},{y:.1f} {x + w - inset:.1f},{y:.1f} {x + w:.1f},{y + h / 2:.1f} {x + w - inset:.1f},{y + h:.1f} {x + inset:.1f},{y + h:.1f} {x:.1f},{y + h / 2:.1f}"
        shape = f'<polygon class="md2pdf-mermaid-node-shape" points="{points}" />'
    elif node.shape == "parallelogram":
        skew = min(22, w * 0.16)
        points = f"{x + skew:.1f},{y:.1f} {x + w:.1f},{y:.1f} {x + w - skew:.1f},{y + h:.1f} {x:.1f},{y + h:.1f}"
        shape = f'<polygon class="md2pdf-mermaid-node-shape" points="{points}" />'
    elif node.shape == "database":
        curve = min(16, h * 0.28)
        body = f"M{x:.1f},{y + curve:.1f} C{x:.1f},{y:.1f} {x + w:.1f},{y:.1f} {x + w:.1f},{y + curve:.1f} L{x + w:.1f},{y + h - curve:.1f} C{x + w:.1f},{y + h:.1f} {x:.1f},{y + h:.1f} {x:.1f},{y + h - curve:.1f} Z"
        top = f"M{x:.1f},{y + curve:.1f} C{x:.1f},{y + curve * 2:.1f} {x + w:.1f},{y + curve * 2:.1f} {x + w:.1f},{y + curve:.1f}"
        shape = f'<path class="md2pdf-mermaid-node-shape" d="{body}" /><path class="md2pdf-mermaid-node-shape md2pdf-mermaid-node-detail" d="{top}" />'
    else:
        rx = h / 2 if node.shape == "stadium" else (16 if node.shape in {"round", "subroutine"} else 9)
        shape = f'<rect class="md2pdf-mermaid-node-shape" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx:.1f}" />'
        if node.shape == "subroutine":
            pad = min(14, w * 0.12)
            shape += f'<path class="md2pdf-mermaid-node-shape md2pdf-mermaid-node-detail" d="M{x + pad:.1f},{y:.1f} V{y + h:.1f} M{x + w - pad:.1f},{y:.1f} V{y + h:.1f}" />'
    return f'<g class="md2pdf-mermaid-node md2pdf-mermaid-node-{html.escape(node.shape)}" data-node-id="{safe_id}">{shape}{text}</g>'


def _node_text_svg(node: MermaidNode, center_x: float, center_y: float) -> str:
    count = len(node.lines)
    start_y = center_y - ((count - 1) * TEXT_LINE_H) / 2 + 4
    direction = _text_direction(node.label)
    tspans = []
    for index, line in enumerate(node.lines):
        dy = 0 if index == 0 else TEXT_LINE_H
        tspans.append(
            f'<tspan x="{center_x:.1f}" dy="{dy:.1f}">{html.escape(line)}</tspan>'
        )
    return (
        f'<text class="md2pdf-mermaid-node-label" x="{center_x:.1f}" y="{start_y:.1f}" '
        f'text-anchor="middle" direction="{direction}" unicode-bidi="plaintext">{"".join(tspans)}</text>'
    )


def _text_direction(text: str) -> str:
    return "rtl" if ARABIC_RE.search(text or "") else "ltr"


def _edge_svg(edge: MermaidEdge, nodes: dict[str, MermaidNode], *, horizontal: bool, marker_id: str) -> str:
    source = nodes.get(edge.source)
    target = nodes.get(edge.target)
    if not source or not target:
        return ""
    if horizontal:
        forward = target.x >= source.x
        x1 = source.x + source.width if forward else source.x
        y1 = source.y + source.height / 2
        x2 = target.x if forward else target.x + target.width
        y2 = target.y + target.height / 2
        delta = abs(x2 - x1)
        mid = x1 + (1 if forward else -1) * max(28, delta / 2)
        path = f"M {x1:.1f} {y1:.1f} C {mid:.1f} {y1:.1f}, {mid:.1f} {y2:.1f}, {x2:.1f} {y2:.1f}"
        label_x, label_y = (x1 + x2) / 2, (y1 + y2) / 2 - 7
    else:
        forward = target.y >= source.y
        x1 = source.x + source.width / 2
        y1 = source.y + source.height if forward else source.y
        x2 = target.x + target.width / 2
        y2 = target.y if forward else target.y + target.height
        delta = abs(y2 - y1)
        mid = y1 + (1 if forward else -1) * max(26, delta / 2)
        path = f"M {x1:.1f} {y1:.1f} C {x1:.1f} {mid:.1f}, {x2:.1f} {mid:.1f}, {x2:.1f} {y2:.1f}"
        label_x, label_y = (x1 + x2) / 2, (y1 + y2) / 2 - 7

    classes = ["md2pdf-mermaid-edge", f"md2pdf-mermaid-edge-{edge.kind}"]
    marker = f' marker-end="url(#{html.escape(marker_id)})"' if edge.kind != "line" else ""
    label = ""
    if edge.label:
        safe_label = html.escape(edge.label)
        direction = _text_direction(edge.label)
        label_w = _estimate_text_width(edge.label, font_size=11, padding=14)
        label_h = 18
        label_x0 = label_x - label_w / 2
        label_y0 = label_y - 13
        label_center_y = label_y0 + label_h / 2
        label = (
            f'<g class="md2pdf-mermaid-edge-label-group">'
            f'<rect class="md2pdf-mermaid-edge-label-bg" x="{label_x0:.1f}" y="{label_y0:.1f}" '
            f'width="{label_w:.1f}" height="{label_h:.1f}" rx="9" />'
            f'<text class="md2pdf-mermaid-edge-label" x="{label_x:.1f}" y="{label_center_y:.1f}" '
            f'text-anchor="middle" direction="{direction}" unicode-bidi="plaintext">'
            f'<tspan x="{label_x:.1f}" dy="0.35em">{safe_label}</tspan></text>'
            f'</g>'
        )
    return f'<g class="{" ".join(classes)}"><path d="{path}"{marker} />{label}</g>'


def _estimate_text_width(value: str, *, font_size: float, padding: float) -> float:
    """Estimate an SVG text label background width without a browser.

    The offline Mermaid renderer cannot ask Chromium for text metrics while it is
    building SVG. A deterministic estimate is sufficient for compact edge-label
    chips and avoids the older stroked-text halo, which looked good visually but
    produced duplicated glyph extraction in some PDF viewers.
    """
    width = 0.0
    for char in value:
        if char.isspace():
            width += font_size * 0.34
        elif ord(char) > 0x2FF:
            width += font_size * 0.72
        elif char in "ilI.,'`|!":
            width += font_size * 0.32
        elif char in "mwMW@#%&":
            width += font_size * 0.82
        else:
            width += font_size * 0.58
    return max(28.0, width + padding)
