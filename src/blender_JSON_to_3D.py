import sys
import json
import math
from pathlib import Path

import bpy

# ── Config
# Output files live at the project root, one level up from this script
# (which sits in src/), so they land next to README.md etc. rather than
# inside src/.
_PROJECT_ROOT = Path(__file__).parent.parent
FILE_PATH     = _PROJECT_ROOT / "park_output.json"
OUTPUT_BLEND  = _PROJECT_ROOT / "park_scene.blend"
OUTPUT_IMAGE  = _PROJECT_ROOT / "model_preview.png"
SCALE         = 0.05        # PDF units → Blender metres
SURFACE_DEPTH = 0.15        # Solidify thickness (metres)
LINE_BEVEL    = 0.025       # Curve bevel radius
MIN_LINE_LEN  = 5 * SCALE   # skip micro-lines

# Parse custom flags (everything after "--" in argv)
_custom_args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
RENDER_PREVIEW = "--render-preview" in _custom_args


# ══════════════════════════════════════════════════════════════════════════
# Material library
# ══════════════════════════════════════════════════════════════════════════

# (material_type → (roughness, metallic, bump_strength, noise_scale))
MATERIAL_PARAMS = {
    "grass_lush":         (1.0,  0.0, 0.80, 50.0),
    "safety_rubber_red":  (0.9,  0.0, 0.35, 120.0),
    "safety_rubber_blue": (0.9,  0.0, 0.35, 120.0),
    "safety_rubber_green":(0.9,  0.0, 0.35, 120.0),
    "fine_sand":          (0.85, 0.0, 0.20, 800.0),
    "wood_chips":         (0.95, 0.0, 0.60, 60.0),
    "asphalt_dark":       (0.85, 0.0, 0.15, 200.0),
    "concrete_light":     (0.75, 0.0, 0.10, 300.0),
    "gravel_gray":        (0.90, 0.0, 0.55, 150.0),
    "water_feature":      (0.05, 0.05, 0.0,  20.0),
}


def _get_or_create_pbr_material(mat_type: str, base_color: list) -> bpy.types.Material:
    name = f"Mat_{mat_type}"
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes  = mat.node_tree.nodes
    links  = mat.node_tree.links

    bsdf   = nodes["Principled BSDF"]
    rough, metal, bump_str, noise_sc = MATERIAL_PARAMS.get(
        mat_type, (0.8, 0.0, 0.3, 100.0)
    )

    r, g, b = (base_color + [0.5, 0.5, 0.5])[:3]
    bsdf.inputs["Base Color"].default_value  = (r, g, b, 1.0)
    bsdf.inputs["Roughness"].default_value   = rough
    bsdf.inputs["Metallic"].default_value    = metal

    # Procedural bump
    if bump_str > 0:
        noise = nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = noise_sc
        bump  = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = bump_str
        links.new(noise.outputs["Fac"],    bump.inputs["Height"])
        links.new(bump.outputs["Normal"],  bsdf.inputs["Normal"])

    # Special: water gets a Glossy + Mix overlay
    if mat_type == "water_feature":
        glossy = nodes.new("ShaderNodeBsdfGlossy")
        glossy.inputs["Color"].default_value = (0.6, 0.8, 1.0, 1.0)
        glossy.inputs["Roughness"].default_value = 0.05
        mix = nodes.new("ShaderNodeMixShader")
        mix.inputs["Fac"].default_value = 0.4
        out = nodes["Material Output"]
        links.new(bsdf.outputs["BSDF"],    mix.inputs[1])
        links.new(glossy.outputs["BSDF"],  mix.inputs[2])
        links.new(mix.outputs["Shader"],   out.inputs["Surface"])

    return mat


def _get_or_create_line_material(stroke_color: list) -> bpy.types.Material:
    r, g, b = (stroke_color + [0.2, 0.2, 0.2])[:3]
    name = f"LineMat_{r:.2f}_{g:.2f}_{b:.2f}"
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out      = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value    = (r, g, b, 1.0)
    emission.inputs["Strength"].default_value = 1.5
    links.new(emission.outputs["Emission"], out.inputs["Surface"])
    mat.diffuse_color = (r, g, b, 1.0)
    return mat


# ══════════════════════════════════════════════════════════════════════════
# Geometry helpers
# ══════════════════════════════════════════════════════════════════════════

def _create_collection(name: str) -> bpy.types.Collection:
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def _compute_center(data: dict) -> tuple[float, float]:
    xs, ys = [], []
    for s in data.get("surfaces", []):
        for p in s["points"]:
            xs.append(p[0]); ys.append(p[1])
    for eq in data.get("equipment", []):
        xs.append(eq["position"][0]); ys.append(eq["position"][1])
    if not xs:
        return (0.0, 0.0)
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


def _cvt(p: list, center: tuple) -> tuple[float, float, float]:
    return (
        round((p[0] - center[0]) * SCALE, 5),
        round((p[1] - center[1]) * SCALE, 5),
        0.0,
    )


def _create_surface(surface: dict, center: tuple,
                    collection: bpy.types.Collection, idx: int) -> None:
    points = surface.get("points", [])
    if len(points) < 3:
        return

    mesh = bpy.data.meshes.new(f"surf_mesh_{idx}")
    obj  = bpy.data.objects.new(f"Surface_{idx}", mesh)

    verts = [_cvt(p, center) for p in points]
    mesh.from_pydata(verts, [], [tuple(range(len(verts)))])
    mesh.update()
    collection.objects.link(obj)

    # Solidify → real 3-D volume
    bpy.context.view_layer.objects.active = obj
    sol = obj.modifiers.new("Solidify", "SOLIDIFY")
    sol.thickness = SURFACE_DEPTH
    sol.offset    = 1.0

    # UV unwrap
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")

    mat_type = surface.get("material_type", "concrete_light")
    color    = surface.get("color", [0.5, 0.5, 0.5])
    obj.data.materials.append(_get_or_create_pbr_material(mat_type, color))


def _create_vector_line(p1: tuple, p2: tuple,
                        collection: bpy.types.Collection,
                        name: str, stroke=None) -> None:
    curve_data              = bpy.data.curves.new(name, type="CURVE")
    curve_data.dimensions   = "3D"
    curve_data.bevel_depth  = LINE_BEVEL
    curve_data.bevel_resolution = 1

    spline = curve_data.splines.new("POLY")
    spline.points.add(1)
    spline.points[0].co = (*p1, 1.0)
    spline.points[1].co = (*p2, 1.0)

    obj = bpy.data.objects.new(name, curve_data)
    collection.objects.link(obj)

    if stroke:
        obj.data.materials.append(_get_or_create_line_material(stroke))


def _process_vectors(vectors: list, center: tuple,
                     collection: bpy.types.Collection) -> None:
    for i, vec in enumerate(vectors):
        stroke = vec.get("stroke")
        if vec["type"] == "lines":
            for j, seg in enumerate(vec["segments"]):
                p1 = _cvt(seg[0], center)
                p2 = _cvt(seg[1], center)
                if math.dist(p1, p2) > MIN_LINE_LEN:
                    _create_vector_line(p1, p2, collection,
                                        f"Line_{i}_{j}", stroke)
        elif "points" in vec:
            pts = [_cvt(p, center) for p in vec["points"]]
            for j in range(len(pts) - 1):
                _create_vector_line(pts[j], pts[j + 1], collection,
                                    f"Path_{i}_{j}", stroke)


# ══════════════════════════════════════════════════════════════════════════
# Camera & render
# ══════════════════════════════════════════════════════════════════════════

def _setup_render(scene_objects: list) -> None:
    """Auto-frame all geometry, add HDRI-style lighting, render PNG."""

    # ── Sun light 
    bpy.ops.object.light_add(type="SUN", location=(10, 10, 20))
    sun = bpy.context.active_object
    sun.data.energy = 5.0
    sun.rotation_euler = (math.radians(45), 0, math.radians(30))

    # ── Fill light (soft, opposite side) 
    bpy.ops.object.light_add(type="AREA", location=(-8, -8, 8))
    fill = bpy.context.active_object
    fill.data.energy  = 200.0
    fill.data.size    = 10.0

    # ── Camera 
    bpy.ops.object.camera_add(location=(20, -20, 20))
    cam = bpy.context.active_object
    bpy.context.scene.camera = cam

    # Point at world origin via constraint
    ct = cam.constraints.new("TRACK_TO")
    empty = bpy.data.objects.new("CameraTarget", None)
    bpy.context.scene.collection.objects.link(empty)
    empty.location = (0, 0, 0)
    ct.target      = empty
    ct.track_axis  = "TRACK_NEGATIVE_Z"
    ct.up_axis     = "UP_Y"

    # Auto-fit: select all geometry, frame in camera view
    bpy.ops.object.select_all(action="SELECT")
    # Use scene override to avoid context errors
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            with bpy.context.temp_override(area=area):
                bpy.ops.view3d.camera_to_view_selected()
            break

    # ── Render settings 
    scene = bpy.context.scene
    scene.render.engine               = "CYCLES"
    scene.cycles.samples              = 64        # fast but decent quality
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath             = str(OUTPUT_IMAGE.resolve())
    scene.render.resolution_x        = 800
    scene.render.resolution_y        = 600
    scene.render.film_transparent     = True
    scene.cycles.use_denoising       = True

    print(f"[Blender] Rendering preview → {OUTPUT_IMAGE} …")
    bpy.ops.render.render(write_still=True)
    print("[Blender] Render complete.")


# ══════════════════════════════════════════════════════════════════════════
# Main entry point
# ══════════════════════════════════════════════════════════════════════════

def create_park() -> None:
    # Clear default scene
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    if not FILE_PATH.exists():
        print(f"[Blender] ERROR: JSON not found at {FILE_PATH}")
        return

    with open(FILE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    surfaces = data.get("surfaces", [])
    vectors  = data.get("vectors", [])
    print(f"[Blender] Loaded {len(surfaces)} surfaces, {len(vectors)} vectors.")

    collection = _create_collection("Park_Model")
    center     = _compute_center(data)

    for i, surf in enumerate(surfaces):
        _create_surface(surf, center, collection, i)

    if vectors:
        _process_vectors(vectors, center, collection)

    if RENDER_PREVIEW:
        _setup_render([])

    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT_BLEND.resolve()))
    print(f"[Blender] Scene saved → {OUTPUT_BLEND}")


create_park()