"""Combine saved queue results with Forge's native gallery and image metadata."""
import copy
import os


PER_IMAGE_FIELDS = {
    "all_prompts": ("prompt", ""),
    "all_negative_prompts": ("negative_prompt", ""),
    "all_seeds": ("seed", -1),
    "all_subseeds": ("subseed", -1),
}


def image_metadata(info, count):
    """Align sample metadata with gallery positions, including grid images."""
    first = info.get("index_of_first_image", 0)
    result = {"infotexts": list(info.get("infotexts", []))[:count]}
    result["infotexts"].extend([""] * (count - len(result["infotexts"])))
    for field, (fallback, default) in PER_IMAGE_FIELDS.items():
        values = info.get(field) or []
        result[field] = [
            values[min(max(i - first, 0), len(values) - 1)]
            if values else info.get(fallback, default)
            for i in range(count)
        ]
    return result


def merge_gallery_results(gallery, info, completed):
    """Append unseen task versions; return None if no displayable images changed.

    completed contains (version, decoded task result) pairs. Versions live in the
    gallery's own generation info, so browser sessions and tabs stay independent.
    """
    gallery = list(gallery or [])
    info = copy.deepcopy(info or {})
    metadata = image_metadata(info, len(gallery))
    versions = list(info.get("agent_scheduler_gallery_versions", []))
    selected = len(gallery)
    changed = False

    for version, result in completed:
        if version in versions:
            continue
        paths = result.get("images") or []
        task_info = result.get("geninfo") or {}
        task_metadata = image_metadata(task_info, len(paths))
        existing = [i for i, path in enumerate(paths) if os.path.isfile(path)]
        if not existing:
            continue
        gallery.extend(paths[i] for i in existing)
        for field in metadata:
            metadata[field].extend(task_metadata[field][i] for i in existing)
        versions.append(version)
        # Retain full generation settings as well as per-image prompt/seed data.
        info.update(task_info)
        changed = True

    if not changed:
        return None
    info.update(metadata)
    info["index_of_first_image"] = 0
    info["agent_scheduler_gallery_versions"] = versions
    return gallery, info, selected
