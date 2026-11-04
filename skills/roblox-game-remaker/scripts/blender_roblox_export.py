"""Check meshes and rigs against Roblox import limits, then export FBX or glTF from Blender.

Run inside Blender (needs bpy):
  blender -b scene.blend --python scripts/blender_roblox_export.py -- --out exports/crate.fbx
  blender -b hero.blend --python scripts/blender_roblox_export.py -- --out exports/run.fbx --animation --r15
  blender -b prop.blend --python scripts/blender_roblox_export.py -- --out exports/prop.glb --format glb

Options (after the "--"):
  --out PATH         output file (.fbx, .glb or .gltf)
  --format fbx|glb|gltf   default from the extension
  --selected         only check and export the selected objects (default: all mesh and armature objects)
  --animation        bake animation (one clip per FBX; Roblox imports a single animation track)
  --r15              require the standard R15 bone hierarchy
  --report PATH      write a JSON report
  --force            export even when errors were found

Limits from the Roblox creator docs (modeling specifications, export settings, character body
specifications): at most 20,000 triangles per mesh; at most 4 bone influences per vertex; no
influences on the Root bone; bones with zero rotation and unit scale in rest pose; watertight
geometry without n-gons where possible; cage meshes named <mesh>_InnerCage / <mesh>_OuterCage.
FBX export: Path Mode Copy + Embed Textures, Apply Scalings = FBX Unit Scale, Add Leaf Bones off,
Bake Animation only when exporting animation, Forward Z / Up Y per the Roblox Blender guide.

The pure-Python checks below (no bpy) are unit tested outside Blender.
"""

from __future__ import annotations

import argparse
import json
import sys

MAX_TRIANGLES = 20000
MAX_INFLUENCES = 4
R15_PARENTS = {
    "HumanoidRootNode": "Root",
    "LowerTorso": "HumanoidRootNode",
    "UpperTorso": "LowerTorso",
    "Head": "UpperTorso",
    "LeftUpperArm": "UpperTorso",
    "LeftLowerArm": "LeftUpperArm",
    "LeftHand": "LeftLowerArm",
    "RightUpperArm": "UpperTorso",
    "RightLowerArm": "RightUpperArm",
    "RightHand": "RightLowerArm",
    "LeftUpperLeg": "LowerTorso",
    "LeftLowerLeg": "LeftUpperLeg",
    "LeftFoot": "LeftLowerLeg",
    "RightUpperLeg": "LowerTorso",
    "RightLowerLeg": "RightUpperLeg",
    "RightFoot": "RightLowerLeg",
}


# ----------------------------------------------------------------- pure checks

def check_triangles(name: str, triangles: int) -> list[str]:
    if triangles > MAX_TRIANGLES:
        return [f"{name}: {triangles} triangles exceeds the {MAX_TRIANGLES} per-mesh limit; decimate or split the mesh"]
    return []


def check_influences(name: str, vertex_weights: list[list[float]], eps: float = 1e-6) -> list[str]:
    """vertex_weights: per vertex, the weights of every deforming group."""
    over = sum(1 for ws in vertex_weights if sum(1 for w in ws if w > eps) > MAX_INFLUENCES)
    if over:
        return [f"{name}: {over} vertices have more than {MAX_INFLUENCES} bone influences; use Weights > Limit Total (4)"]
    return []


def check_root_influence(name: str, group_names: list[str], used_groups: set[str]) -> list[str]:
    bad = [g for g in group_names if g in ("Root", "HumanoidRootNode") and g in used_groups]
    return [f"{name}: vertices are weighted to {', '.join(bad)}; remove influences from the root bone"] if bad else []


def check_r15(parents: dict[str, str | None]) -> list[str]:
    """parents: bone name -> parent bone name (None for the top bone)."""
    errors = []
    if "Root" not in parents:
        errors.append("R15: missing bone 'Root'")
    for bone, parent in R15_PARENTS.items():
        if bone not in parents:
            errors.append(f"R15: missing bone '{bone}'")
        elif parents[bone] != parent:
            errors.append(f"R15: '{bone}' must be a child of '{parent}' (found '{parents[bone]}')")
    return errors


def check_cage_names(mesh_names: list[str]) -> list[str]:
    errors = []
    names = set(mesh_names)
    for n in mesh_names:
        lower = n.lower()
        for suffix in ("_innercage", "_outercage"):
            if lower.endswith(suffix):
                if not n.endswith(("_InnerCage", "_OuterCage")):
                    errors.append(f"{n}: cage suffix must be exactly _InnerCage or _OuterCage")
                elif n[: -len(suffix)] not in names:
                    errors.append(f"{n}: no primary mesh named '{n[: -len(suffix)]}'")
        if "cage" in lower and not lower.endswith(("_innercage", "_outercage")):
            errors.append(f"{n}: looks like a cage; name it <mesh>_InnerCage or <mesh>_OuterCage")
    return errors


def check_transform(name: str, rotation_euler, scale, is_bone: bool = False, tol: float = 1e-4) -> list[str]:
    errs = []
    if any(abs(v) > tol for v in rotation_euler):
        errs.append(f"{name}: unapplied rotation {tuple(round(v, 4) for v in rotation_euler)}; apply transforms (Ctrl+A)")
    if any(abs(v - 1.0) > tol for v in scale):
        errs.append(f"{name}: unapplied scale {tuple(round(v, 4) for v in scale)}; apply transforms (Ctrl+A)")
    if is_bone and errs:
        errs = [e.replace("apply transforms (Ctrl+A)", "bones need rotation 0 and scale 1 in rest pose") for e in errs]
    return errs


def parse_args(argv: list[str]):
    ap = argparse.ArgumentParser(prog="blender_roblox_export.py", description="Roblox-checked export from Blender")
    ap.add_argument("--out", required=True)
    ap.add_argument("--format", choices=["fbx", "glb", "gltf"])
    ap.add_argument("--selected", action="store_true")
    ap.add_argument("--animation", action="store_true")
    ap.add_argument("--r15", action="store_true")
    ap.add_argument("--report")
    ap.add_argument("--force", action="store_true")
    return ap.parse_args(argv)


# ----------------------------------------------------------------- Blender side

def _blender_main(argv: list[str]) -> int:
    import bmesh  # Blender only
    import bpy

    args = parse_args(argv)
    fmt = args.format or args.out.rsplit(".", 1)[-1].lower()
    if fmt not in ("fbx", "glb", "gltf"):
        print("error: --out must end in .fbx, .glb or .gltf (or pass --format)")
        return 2
    objs = list(bpy.context.selected_objects) if args.selected else list(bpy.context.scene.objects)
    meshes = [o for o in objs if o.type == "MESH"]
    arms = [o for o in objs if o.type == "ARMATURE"]
    errors: list[str] = []
    warnings: list[str] = []
    stats = {"meshes": {}, "armatures": {}}
    depsgraph = bpy.context.evaluated_depsgraph_get()

    for ob in meshes:
        ev = ob.evaluated_get(depsgraph)
        me = ev.to_mesh()
        bm = bmesh.new()
        bm.from_mesh(me)
        tris = sum(len(f.verts) - 2 for f in bm.faces)
        ngons = sum(1 for f in bm.faces if len(f.verts) > 4)
        nonmanifold = sum(1 for e in bm.edges if not e.is_manifold)
        zero = sum(1 for f in bm.faces if f.calc_area() < 1e-10)
        bm.free()
        ev.to_mesh_clear()
        stats["meshes"][ob.name] = {"triangles": tris, "ngons": ngons, "non_manifold_edges": nonmanifold, "zero_area_faces": zero}
        errors += check_triangles(ob.name, tris)
        if ngons:
            warnings.append(f"{ob.name}: {ngons} n-gons; Roblox asks for quads where possible")
        if nonmanifold and not ob.name.endswith(("_InnerCage", "_OuterCage")):
            warnings.append(f"{ob.name}: {nonmanifold} non-manifold edges; meshes should be watertight")
        if zero:
            warnings.append(f"{ob.name}: {zero} zero-area faces")
        errors += check_transform(ob.name, ob.rotation_euler, ob.scale)
        groups = [g.name for g in ob.vertex_groups]
        if groups and any(m.type == "ARMATURE" for m in ob.modifiers):
            weights = [[g.weight for g in v.groups] for v in ob.data.vertices]
            errors += check_influences(ob.name, weights)
            used = {groups[g.group] for v in ob.data.vertices for g in v.groups if g.weight > 1e-6 and g.group < len(groups)}
            errors += check_root_influence(ob.name, groups, used)
    errors += check_cage_names([o.name for o in meshes])

    for arm in arms:
        parents = {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones}
        stats["armatures"][arm.name] = {"bones": len(parents)}
        errors += check_transform(arm.name, arm.rotation_euler, arm.scale)
        for pb in arm.pose.bones:
            if args.animation:
                continue  # posed frames are expected when exporting animation
            errors += check_transform(f"{arm.name}:{pb.name}", pb.rotation_euler if pb.rotation_mode != "QUATERNION"
                                      else (pb.rotation_quaternion[1], pb.rotation_quaternion[2], pb.rotation_quaternion[3]),
                                      pb.scale, is_bone=True)
        if args.r15:
            errors += check_r15(parents)
    if args.r15 and not arms:
        errors.append("--r15 given but no armature found")

    report = {"out": args.out, "format": fmt, "errors": errors, "warnings": warnings, "stats": stats, "exported": False}
    for w in warnings:
        print(f"WARNING {w}")
    for e in errors:
        print(f"ERROR {e}")
    if errors and not args.force:
        print(f"{len(errors)} errors: not exporting (fix them or pass --force)")
    else:
        if args.selected is False:
            bpy.ops.object.select_all(action="DESELECT")
            for o in meshes + arms:
                o.select_set(True)
        if fmt == "fbx":
            bpy.ops.export_scene.fbx(
                filepath=args.out, use_selection=True, path_mode="COPY", embed_textures=True,
                apply_scale_options="FBX_SCALE_UNITS", axis_forward="Z", axis_up="Y",
                add_leaf_bones=False, bake_anim=args.animation, object_types={"MESH", "ARMATURE"},
            )
        else:
            bpy.ops.export_scene.gltf(filepath=args.out, use_selection=True,
                                      export_format="GLB" if fmt == "glb" else "GLTF_SEPARATE",
                                      export_animations=args.animation)
        report["exported"] = True
        print(f"exported {args.out}")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    return 1 if errors and not args.force else 0


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    try:
        import bpy  # noqa: F401
    except ImportError:
        print("error: run this inside Blender: blender -b file.blend --python blender_roblox_export.py -- --out out.fbx", file=sys.stderr)
        sys.exit(2)
    sys.exit(_blender_main(argv))
