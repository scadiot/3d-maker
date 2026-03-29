"""Save / load scene to/from JSON."""

import json

from editor.utils.texture_atlas import TextureAtlas
from editor.utils import math3d
from editor.core.group import Group


def save_json(scene, path: str) -> None:
    """Exports the scene to a hierarchical JSON file."""
    def serialize_group(g):
        return {
            "name":     g.name,
            "hidden":   g.hidden,
            "locked":   g.locked,
            "groups":   [serialize_group(c) for c in g.children],
            "polygons": [
                {
                    "vertices":         [[round(v, 6) for v in vert] for vert in p.vertices],
                    "uvs":              [[round(u, 6), round(v, 6)] for u, v in p.uvs],
                    "texture_atlas_id": p.texture_atlas_id,
                }
                for p in g.polygons
            ],
        }

    state = scene._state
    project_name = state.project_name if state is not None else ""
    atlases = []
    if state is not None:
        atlases = [
            {"id": ta.id, "image_path": ta.image_path, "atlas_data": ta.atlas_data}
            for ta in state.textures_atlases
        ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"name": project_name, "textures_atlases": atlases, "root": serialize_group(scene.root)},
            f, indent=2, ensure_ascii=False,
        )


def import_json(scene, path: str) -> None:
    """Merges polygons from a JSON file into the current scene.

    Texture atlases are deduplicated by image_path: atlases already present
    in the project are reused, new ones are appended with fresh IDs.
    The old texture_atlas_id values in the file are remapped to the IDs
    of the current project before the polygons are added.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    state = scene._state
    id_map: dict[int, int] = {}

    if state is not None:
        existing_paths = {ta.image_path: ta.id for ta in state.textures_atlases}
        next_id = max((ta.id for ta in state.textures_atlases), default=0) + 1
        new_atlases = []

        for ta_data in data.get("textures_atlases", []):
            old_id = ta_data.get("id", 0)
            img_path = ta_data.get("image_path", "")
            if img_path in existing_paths:
                id_map[old_id] = existing_paths[img_path]
            else:
                atlas = TextureAtlas(img_path, ta_data.get("atlas_data"))
                atlas.id = next_id
                id_map[old_id] = next_id
                existing_paths[img_path] = next_id
                new_atlases.append(atlas)
                next_id += 1

        if new_atlases:
            for atlas in new_atlases:
                scene.load_atlas(atlas)
            state.change_textures(state.textures_atlases + new_atlases)

    def load_group(node_data, parent):
        for p_data in node_data.get("polygons", []):
            poly = parent.add_polygon(
                [tuple(v) for v in p_data["vertices"]],
                [tuple(uv) for uv in p_data["uvs"]],
            )
            old_id = p_data.get("texture_atlas_id", 0)
            poly.texture_atlas_id = id_map.get(old_id, old_id) if state is not None else old_id
        for g_data in node_data.get("groups", []):
            child = parent.add_group(g_data.get("name", "Group"))
            child.hidden = g_data.get("hidden", False)
            child.locked = g_data.get("locked", False)
            load_group(g_data, child)

    import_name = data.get("name") or "Import"
    import_group = scene.root.add_group(import_name)
    import_group.locked = True
    load_group(data["root"], import_group)
    scene._emit_scene_changed("polygons_added")


def load_json(scene, path: str) -> None:
    """Imports a scene from a JSON file (appends to existing polygons)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    def load_group(node_data, parent):
        for p_data in node_data.get("polygons", []):
            poly = parent.add_polygon(
                [tuple(v) for v in p_data["vertices"]],
                [tuple(uv) for uv in p_data["uvs"]],
            )
            poly.texture_atlas_id = p_data.get("texture_atlas_id", 0)
        for g_data in node_data.get("groups", []):
            child = parent.add_group(g_data.get("name", "Group"))
            child.hidden = g_data.get("hidden", False)
            child.locked = g_data.get("locked", False)
            load_group(g_data, child)
        # Backward compatibility: old format with mixed "children"
        for child_data in node_data.get("children", []):
            if "vertices" in child_data:
                parent.add_polygon(
                    [tuple(v) for v in child_data["vertices"]],
                    [tuple(uv) for uv in child_data["uvs"]],
                )
            else:
                child = parent.add_group(child_data.get("name", "Group"))
                load_group(child_data, child)
    load_group(data["root"], scene.root)

    state = scene._state
    if state is not None:
        state.clear_selection()
        state.project_name = data.get("name", "Unnamed Project")
        state.project_path = path
        atlases = []
        for ta in data.get("textures_atlases", []):
            atlas = TextureAtlas(ta["image_path"], ta.get("atlas_data"))
            atlas.id = ta.get("id", 0)
            atlases.append(atlas)
        state.textures_atlases = atlases
        for atlas in state.textures_atlases:
            scene.load_atlas(atlas)
    scene._emit_scene_changed("polygons_added")
