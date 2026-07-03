import fitz  # PyMuPDF
import re
import json
import time
from pathlib import Path

# ── Spatial filters (tune to your PDF layout) 
AREA_THRESHOLD = 5_000   # px² — ignore tiny fill slivers
Y_LIMIT = 1_100           # crop bottom legend / title block
X_LIMIT = 700             # crop right-side legend


def extract_pdf(pdf_path: str, output_path: str) -> dict:
    """
    Parse *pdf_path* and write enriched JSON to *output_path*.

    Returns the parsed data dict so callers can display analytics
    without re-reading the file.
    """
    t0 = time.perf_counter()
    doc = fitz.open(pdf_path)
    page = doc[0]
    page_height = page.rect.height

    print(f"[PDF] Opened '{Path(pdf_path).name}'  —  {len(doc)} page(s)")

    # ── Coordinate helper 
    def to_3d(x: float, y: float):
        """Flip Y so origin is bottom-left (3-D friendly)."""
        return round(x, 2), round(page_height - y, 2)

    # ── 1. Text: equipment markers & legend map 
    equipment_markers: list[dict] = []
    equipment_map: dict[int, str] = {}
    text_dict = page.get_text("dict")

    for block in text_dict["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            line_text = " ".join(s["text"] for s in line["spans"]).strip()

            # Legend mapping  →  "3. Swing set"
            m = re.match(r"^(\d+)\.\s+(.*)", line_text)
            if m:
                equipment_map[int(m.group(1))] = m.group(2)

            # Marker labels on the plan  →  "3."
            for span in line["spans"]:
                text = span["text"].strip()
                if text.endswith(".") and text[:-1].isdigit():
                    bbox = span["bbox"]
                    xm = (bbox[0] + bbox[2]) / 2
                    ym = (bbox[1] + bbox[3]) / 2
                    if ym < Y_LIMIT and xm < X_LIMIT:
                        cx, cy = to_3d(xm, ym)
                        equipment_markers.append(
                            {"id": int(text[:-1]), "position": [cx, cy]}
                        )

    # Attach names from legend
    for marker in equipment_markers:
        marker["name"] = equipment_map.get(marker["id"], "unknown")

    # ── 2. Drawings: surfaces & vector shapes 
    drawings = page.get_drawings()
    major_surfaces: list[dict] = []
    vector_shapes: list[dict] = []

    color_freq: dict[tuple, int] = {}   # for analytics

    for d in drawings:
        rect = fitz.Rect(d["rect"])

        # Spatial filter
        if rect.x0 > X_LIMIT or rect.y0 > Y_LIMIT:
            continue

        area = rect.width * rect.height

        # ── Filled surfaces 
        if d["fill"] is not None and area > AREA_THRESHOLD:
            path_points: list[list[float]] = []
            for item in d["items"]:
                for p in item[1:]:
                    if isinstance(p, fitz.Point):
                        path_points.append(list(to_3d(p.x, p.y)))
                    elif isinstance(p, fitz.Rect):
                        x0, y0 = to_3d(p.x0, p.y1)
                        x1, y1 = to_3d(p.x1, p.y0)
                        path_points.extend([[x0, y0], [x1, y0],
                                            [x1, y1], [x0, y1]])

            if path_points:
                fill_rgb = tuple(round(c, 3) for c in d["fill"])
                color_freq[fill_rgb] = color_freq.get(fill_rgb, 0) + 1
                major_surfaces.append({
                    "type": "polygon",
                    "points": path_points,
                    "color": list(fill_rgb),
                    "area": round(area, 1),
                })
            continue  # don't also process as vector

        # ── Vector strokes 
        segments: list = []
        for item in d["items"]:
            cmd = item[0]
            if cmd == "l":
                segments.append([
                    list(to_3d(item[1].x, item[1].y)),
                    list(to_3d(item[2].x, item[2].y)),
                ])
            elif cmd == "re":
                r = item[1]
                vector_shapes.append({
                    "type": "rectangle",
                    "bbox": [list(to_3d(r.x0, r.y1)),
                             list(to_3d(r.x1, r.y0))],
                    "stroke": d.get("color"),
                    "fill": d.get("fill"),
                })
            elif cmd in ("c", "m", "v", "y"):
                pts = [list(to_3d(p.x, p.y))
                       for p in item[1:] if isinstance(p, fitz.Point)]
                if pts:
                    vector_shapes.append({
                        "type": "path",
                        "points": pts,
                        "command": cmd,
                        "stroke": d.get("color"),
                    })

        if segments:
            vector_shapes.append({
                "type": "lines",
                "segments": segments,
                "stroke": d.get("color"),
            })

    # ── Analytics block 
    dominant_colors = sorted(
        [{"rgb": list(k), "count": v} for k, v in color_freq.items()],
        key=lambda x: x["count"], reverse=True
    )[:5]

    analytics = {
        "surface_count": len(major_surfaces),
        "vector_count": len(vector_shapes),
        "equipment_count": len(equipment_markers),
        "dominant_colors": dominant_colors,
        "extraction_time_s": round(time.perf_counter() - t0, 3),
    }

    print(f"[PDF] Surfaces: {analytics['surface_count']}  "
          f"Vectors: {analytics['vector_count']}  "
          f"Equipment: {analytics['equipment_count']}  "
          f"({analytics['extraction_time_s']} s)")

    # ── Assemble & write output 
    output = {
        "metadata": {
            "source_file": str(Path(pdf_path).resolve()),
            "x_filter": X_LIMIT,
            "y_filter": Y_LIMIT,
            "page_height": round(page_height, 2),
        },
        "analytics": analytics,
        "equipment": equipment_markers,
        "surfaces": major_surfaces,
        "vectors": vector_shapes,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4, ensure_ascii=False)

    print(f"[PDF] JSON written → {output_path}")
    return output


if __name__ == "__main__":
    extract_pdf("sample_park.pdf", "park_output.json")