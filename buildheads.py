import json
import os
import re
import uuid
import zipfile
import io
import argparse

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# =============================================================================
# createHead.py  –  BPH (Custom Player Heads) addon file generator
# Target: Minecraft Bedrock Edition 1.26.30 (stable)
# References:
#   https://wiki.bedrock.dev/
#   https://learn.microsoft.com/en-us/minecraft/creator/
# =============================================================================

# ---------------------------------------------------------------------------
# ADDON CONFIGURATION
# These values drive manifest generation and .mcaddon packaging.
# UUIDs are generated fresh on each run — do NOT hardcode them here so that
# every build produces unique identifiers as required by Minecraft.
# ---------------------------------------------------------------------------
ADDON_NAME      = "StreamerHeads"
ENGINE_VERSION  = [1, 26, 30]
SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
DEFAULT_HEADS_FILE = os.path.join(SCRIPT_DIR, "heads.json")

# ---------------------------------------------------------------------------
# VERSION – persisted in version.json next to this script.
# The patch number (index 2) auto-increments on each run where any
# gamertag in HEADS already exists in the addon output.
# ---------------------------------------------------------------------------
_VERSION_FILE = os.path.join(SCRIPT_DIR, "version.json")
_BASE_VERSION = [2, 0, 0]


def _load_version() -> list:
    if os.path.isfile(_VERSION_FILE):
        try:
            with open(_VERSION_FILE, "r") as _vf:
                _v = json.load(_vf)
            if isinstance(_v, list) and len(_v) == 3:
                return [int(x) for x in _v]
        except Exception:
            pass
    return list(_BASE_VERSION)


def _save_version(v: list):
    with open(_VERSION_FILE, "w") as _vf:
        json.dump(v, _vf)


def _bump_version(v: list) -> list:
    # Increment patch (index 2); roll over to minor at 100
    v = list(v)
    v[2] += 1
    if v[2] >= 100:
        v[2] = 0
        v[1] += 1
    return v


VERSION = _load_version()
ver_str = ".".join(str(v) for v in VERSION)   # e.g. "2.0.7" — used in manifest descriptions

# ---------------------------------------------------------------------------
# HEADS  –  the single source of truth for every head to generate.
#
# Each entry is:
#   "PlayerName": {
#       "model": "modelname"   or  None  (uses "head" if None)
#   }
#
# "PlayerName" must match the Java Edition username exactly (case-sensitive)
# so the mcprofile.io API can resolve the skin texture.
# ---------------------------------------------------------------------------
HEADS = {
    "BdoubleO100": {"model": None},
    "cubfan135": {"model": None},
    "Docm77": {"model": None},
    "Etho": {"model": None},
    "falsesymmetry": {"model": None},
    "GeminiTay": {"model": None},
    "Grian": {"model": None},
    "hypnotizd": {"model": None},
    "impulseSV": {"model": None},
    "Jevin": {"model": None},
    "JoeHills": {"model": None},
    "Keralis": {"model": None},
    "MumboJumbo": {"model": None},
    "PearlescentMoon": {"model": None},
    "Rendog": {"model": None},
    "GoodTimeWithScar": {"model": None},
    "Skizzleman": {"model": None},
    "Smallishbeans": {"model": None},
    "Tango": {"model": None},
    "VintageBeef": {"model": None},
    "Welsknight": {"model": None},
    "xBCrafted": {"model": None},
    "Xisuma": {"model": None},
    "ZombieCleo": {"model": None},
    # Add more players here:
    # "Steve": {"model": None},
}

# Convenience list derived from HEADS — used for skin fetching and pack icons.
GAMERTAGS = list(HEADS.keys())


def _head_entry(name: str, model=None) -> tuple[str, dict]:
    name = str(name).strip()
    if not name:
        raise ValueError("Head entries must include a non-empty player name.")
    return name, {"model": model}


def heads_from_names(names: str) -> dict:
    """Build a HEADS dict from comma/newline separated player names."""
    if not names:
        return {}
    parts = re.split(r"[,\n]+", names)
    return dict(_head_entry(part) for part in parts if part.strip())


def _normalize_heads_data(data) -> dict:
    if isinstance(data, dict) and "heads" in data:
        data = data["heads"]

    if isinstance(data, dict):
        heads = {}
        for name, value in data.items():
            if isinstance(value, dict):
                model = value.get("model")
            else:
                model = value
            key, entry = _head_entry(name, model)
            heads[key] = entry
        return heads

    if isinstance(data, list):
        heads = {}
        for entry in data:
            if isinstance(entry, str):
                key, value = _head_entry(entry)
            elif isinstance(entry, dict):
                key, value = _head_entry(entry.get("name", ""), entry.get("model"))
            else:
                raise ValueError(f"Unsupported head entry: {entry!r}")
            heads[key] = value
        return heads

    raise ValueError("Heads file must contain a list, object, or object with a 'heads' list.")


def load_heads_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return _normalize_heads_data(json.load(f))


def parse_version(value: str) -> list:
    parts = str(value).strip().replace(",", ".").split(".")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("Version must have three parts, for example 2.1.3")
    try:
        return [int(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Version parts must be integers.") from exc


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build the StreamerHeads Bedrock .mcaddon.")
    parser.add_argument(
        "--heads",
        help="Comma-separated Minecraft Java player names. Overrides --heads-file.",
    )
    parser.add_argument(
        "--heads-file",
        help="JSON file containing player names. Defaults to heads.json when present.",
    )
    parser.add_argument(
        "--version",
        type=parse_version,
        help="Version to stamp into manifests, for example 2.1.3.",
    )
    parser.add_argument(
        "--no-version-bump",
        action="store_true",
        help="Do not auto-increment patch version when existing output is detected.",
    )
    parser.add_argument(
        "--output",
        help="Destination .mcaddon path. Defaults to StreamerHeads_v<version>.mcaddon.",
    )
    parser.add_argument(
        "--require-textures",
        action="store_true",
        help="Fail the build if any selected head texture could not be generated.",
    )
    return parser.parse_args(argv)


def apply_head_selection(args):
    global HEADS, GAMERTAGS
    if args.heads:
        HEADS = heads_from_names(args.heads)
    else:
        heads_file = args.heads_file
        if not heads_file and os.path.isfile(DEFAULT_HEADS_FILE):
            heads_file = DEFAULT_HEADS_FILE
        if heads_file:
            HEADS = load_heads_file(heads_file)

    if not HEADS:
        raise ValueError("No heads selected. Provide --heads, --heads-file, or a non-empty heads.json.")
    GAMERTAGS = list(HEADS.keys())

RP_NAME = "StreamerheadsResources"
BP_NAME = "StreamerHeads_BP"

# Root directories used throughout this script
RP_DIR = "BPH_RP"
BP_DIR = "BPH_BP"

# ---------------------------------------------------------------------------
# UUID STORE
# UUIDs are generated ONCE and saved to bph_ids.json next to this script.
# Every subsequent run loads and reuses the same UUIDs so that Minecraft
# treats each rebuilt pack as an upgrade of the same addon rather than a
# brand-new one.  Only the VERSION number changes between runs.
#
#   rp_header  - RP header (also listed as BP dependency)
#   rp_module  - RP module
#   bp_header  - BP header
#   bp_module  - BP module (data)
#   bp_script  - BP script module
# ---------------------------------------------------------------------------
_UUID_FILE = os.path.join(SCRIPT_DIR, "bph_ids.json")
_UUID_KEYS = ("rp_header", "rp_module", "bp_header", "bp_module", "bp_script")


def _load_uuids() -> dict:
    """Load UUIDs from bph_ids.json, creating the file on the first run."""
    if os.path.isfile(_UUID_FILE):
        try:
            with open(_UUID_FILE, "r") as _f:
                _data = json.load(_f)
            if all(k in _data for k in _UUID_KEYS):
                return _data
        except Exception:
            pass
    # First run -- generate and persist
    _data = {k: str(uuid.uuid4()) for k in _UUID_KEYS}
    with open(_UUID_FILE, "w") as _f:
        json.dump(_data, _f, indent=4)
    print(f"  Generated new UUIDs -> {_UUID_FILE}")
    return _data


_UUIDS = _load_uuids()

_rp_header_uuid = _UUIDS["rp_header"]
_rp_module_uuid = _UUIDS["rp_module"]
_bp_header_uuid = _UUIDS["bp_header"]
_bp_module_uuid = _UUIDS["bp_module"]
_bp_script_uuid = _UUIDS["bp_script"]


# ===========================================================================
# MANIFEST GENERATION
# Produces manifest.json for both the RP and BP following format_version 2.
# Spec: https://learn.microsoft.com/en-us/minecraft/creator/reference/content
#         /addonsreference/packmanifest?view=minecraft-bedrock-stable
# ===========================================================================

def build_rp_manifest() -> dict:
    """
    Returns the RP manifest dict.
    type = "resources" marks this as a Resource Pack.
    The RP depends on the BP too, so activating either pack for a world pulls
    in the other half of the add-on.
    """
    return {
        "format_version": 2,
        "header": {
            "name":               RP_NAME,
            "description":        f"{ADDON_NAME} v{'.'.join(str(v) for v in VERSION)} – Resource Pack",
            "uuid":               _rp_header_uuid,
            "version":            VERSION,
            "min_engine_version": ENGINE_VERSION
        },
        "modules": [
            {
                "type":    "resources",
                "uuid":    _rp_module_uuid,
                "version": VERSION
            }
        ],
        "dependencies": [
            {
                # Link BP so either pack activation brings in the full add-on
                "uuid":    _bp_header_uuid,
                "version": VERSION
            }
        ],
        "capabilities": ["pbr"],
        "metadata": {
            "authors": ["PPTribalize"],
            "license": "CC BY-NC-SA 4.0",
            "url": "https://www.youtube.com/@Tribalize",
            "product_type": "addon"
        }
    }


def build_bp_manifest() -> dict:
    """
    Returns the BP manifest dict.
    type = "data"     ←  behaviour pack data module
    type = "script"   ←  Script API module (requires @minecraft/server)
    dependencies lists both the RP header UUID (auto-links RP when BP is
    applied) and the @minecraft/server module needed by custom components.
    The RP also depends on this BP so either pack activation brings in both.
    """
    return {
        "format_version": 2,
        "header": {
            "name":               BP_NAME,
            "description":        f"{ADDON_NAME} v{'.'.join(str(v) for v in VERSION)} – Behaviour Pack",
            "uuid":               _bp_header_uuid,
            "version":            VERSION,
            "min_engine_version": ENGINE_VERSION
        },
        "modules": [
            {
                "type":    "data",
                "uuid":    _bp_module_uuid,
                "version": VERSION
            },
            {
                # Script module – required for minecraft:custom_components in blocks
                "type":     "script",
                "uuid":     _bp_script_uuid,
                "version":  VERSION,
                "language": "javascript",
                "entry":    "scripts/index.js"
            }
        ],
        "dependencies": [
            {
                # Link RP so it is applied automatically with the BP
                "uuid":    _rp_header_uuid,
                "version": VERSION
            },
            {
                # Script API – needed for custom block components
                "module_name": "@minecraft/server",
                "version":     "2.8.0"
            }
        ],
        "capabilities": ["script_eval"],
        "metadata": {
            "authors": ["PPTribalize"],
            "license": "CC BY-NC-SA 4.0",
            "url": "https://www.youtube.com/@Tribalize",
            "product_type": "addon"
        }
    }


def write_manifests():
    """Writes manifest.json into both BPH_RP and BPH_BP directories."""
    for directory, manifest_fn in (
        (RP_DIR, build_rp_manifest),
        (BP_DIR, build_bp_manifest),
    ):
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "manifest.json")
        with open(path, "w") as f:
            json.dump(manifest_fn(), f, indent=4)
        print(f"Wrote manifest: {path}")


# ===========================================================================
# PACK STRUCTURE INITIALISER
# Creates all boilerplate files that update_* functions expect to exist.
# Safe to call on every run -- existing files are left untouched.
# ===========================================================================

def _write_if_missing(path: str, text: str):
    """Writes a UTF-8 text file only when it does not already exist."""
    if os.path.isfile(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  Initialised: {path}")


def _write_json_if_missing(path: str, data):
    """Writes a JSON file only when it does not already exist."""
    if os.path.isfile(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    print(f"  Initialised: {path}")


# Script API entry point written to BP/scripts/index.js on first run.
# Uses \\n joins to avoid any quoting issues in the source file.
_INDEX_JS_LINES = [
    'import { world } from "@minecraft/server";',
    '',
    '// Each entry: [itemId, blockId]',
    'const headArray = [',
    '];',
    '',
    '// ---------------------------------------------------------------------------',
    '// Head rotation on placement via playerPlaceBlock event',
    '// ---------------------------------------------------------------------------',
    'world.afterEvents.playerPlaceBlock.subscribe((event) => {',
    '    const { player, block } = event;',
    '',
    '    if (!block.typeId.startsWith("bph:") || !block.typeId.endsWith("_head_block")) return;',
    '',
    '    const yaw = ((player.getRotation().y % 360) + 360) % 360;',
    '    const rot = Math.round(yaw / 22.5) % 16;',
    '',
    '    block.setPermutation(',
    '        block.permutation.withState("bph:head_rotation", rot)',
    '    );',
    '});',
    '',
]


def initialize_pack_structure():
    """
    Scaffolds every file that the update_* functions require.
    Existing files are NEVER overwritten so repeated runs are safe.
    """
    print("--- Initialising pack structure ---")

    # RP boilerplate
    _write_json_if_missing(
        f"{RP_DIR}/blocks.json",
        {"format_version": [1, 1, 0]}
    )
    _write_json_if_missing(
        f"{RP_DIR}/textures/terrain_texture.json",
        {
            "resource_pack_name": ADDON_NAME,
            "texture_name": "atlas.terrain",
            "padding": 8,
            "num_mip_levels": 4,
            "texture_data": {}
        }
    )
    _write_json_if_missing(
        f"{RP_DIR}/textures/item_texture.json",
        {
            "resource_pack_name": ADDON_NAME,
            "texture_name": "atlas.items",
            "texture_data": {}
        }
    )
    _write_if_missing(
        f"{RP_DIR}/texts/en_US.lang",
        "## Custom Player Heads - language file\n"
    )
    _write_json_if_missing(
        f"{RP_DIR}/texts/languages.json",
        ["en_US"]
    )

    # BP boilerplate
    _write_if_missing(
        f"{BP_DIR}/scripts/index.js",
        "\n".join(_INDEX_JS_LINES) + "\n"
    )

    # Ensure all required subdirectories exist
    for sub in ("items", "blocks", "recipes", "scripts", "trading/economy_trades", "loot_tables"):
        os.makedirs(f"{BP_DIR}/{sub}", exist_ok=True)
    for sub in ("attachables", "items", "textures/blocks/skulls",
                "textures/items/skulls", "texts",
                "models/blocks", "models/entity"):
        os.makedirs(f"{RP_DIR}/{sub}", exist_ok=True)

    print("  Pack structure ready.")


# ===========================================================================
# SKIN / TEXTURE AUTO-FETCH
# Downloads each player's skin from Crafatar using their Java UUID,
# crops the 8×8 face region from the 64×64 skin sheet, scales it to 64×64,
# and saves it as the head texture the addon expects.
#
# Skin source pipeline:
#   1. https://mcprofile.io/api/v1/java/username/{username}
#      → returns bedrockSkinValue (base64 skin property with texture URL)
#   2. https://textures.minecraft.net/texture/{texture_id}
#      → raw 64x64 PNG skin sheet; face region cropped and saved
#
# If requests or Pillow are missing, or if the API call fails, this step is
# skipped gracefully – the creator can place textures manually.
# ===========================================================================

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
MCPROFILE_URL        = "https://mcprofile.io/api/v1/java/username/{username}"
TEXTURE_DOWNLOAD_URL = "https://textures.minecraft.net/texture/{texture_id}"

# ---------------------------------------------------------------------------
# Minecraft skin sheet UV layout (all values in pixels on a 64x64 sheet)
# ---------------------------------------------------------------------------
#
#  The BPH head geometry model references UV regions on the full skin sheet.
#  We must save the COMPLETE 64x64 skin PNG as the block/attachable texture
#  so the geometry samples the correct faces.
#
#  Additionally we produce a separate ITEM ICON which is just the front-face
#  of the head, composited with the hat overlay, and upscaled to 64x64.
#
#  Standard Minecraft skin UV map (head region only):
#
#   Base layer head cube  (on skin sheet):
#     Top    : x=8,  y=0,  w=8,  h=8    (0,0  → 8,8  after origin shift)
#     Bottom : x=16, y=0,  w=8,  h=8
#     Right  : x=0,  y=8,  w=8,  h=8
#     Front  : x=8,  y=8,  w=8,  h=8   ← the face we show in item icon
#     Left   : x=16, y=8,  w=8,  h=8
#     Back   : x=24, y=8,  w=8,  h=8
#
#   Hat/overlay layer  (32px offset):
#     Top    : x=40, y=0,  w=8,  h=8
#     Bottom : x=48, y=0,  w=8,  h=8
#     Right  : x=32, y=8,  w=8,  h=8
#     Front  : x=40, y=8,  w=8,  h=8   ← overlay for item icon
#     Left   : x=48, y=8,  w=8,  h=8
#     Back   : x=56, y=8,  w=8,  h=8
#
# Skin UV regions for the item icon:
SKIN_FACE_BASE    = (8,  8, 16, 16)   # base-layer front face
SKIN_FACE_HAT     = (40, 8, 48, 16)   # hat-overlay front face
OUTPUT_ICON_SIZE  = (64, 64)          # upscale for crisp inventory icon


def _get_texture_id_from_mcprofile(gamertag: str) -> str | None:
    """
    Calls mcprofile.io/api/v1/java/username/{gamertag} and extracts the
    texture hash from the Java player profile response.

    The Java endpoint returns a standard Mojang session-server profile:
        {
          "id": "<uuid>",
          "name": "<username>",
          "properties": [
            { "name": "textures", "value": "<base64>" }
          ]
        }

    The base64 'value' decodes to JSON containing the skin URL:
        {
          "textures": {
            "SKIN": { "url": "http://textures.minecraft.net/texture/<hash>" }
          }
        }

    Returns the texture hash string on success, or None on failure.
    """
    import base64

    if not HAS_REQUESTS:
        return None
    try:
        url  = MCPROFILE_URL.format(username=gamertag)
        resp = requests.get(url, timeout=15)

        print(f"  mcprofile.io status: {resp.status_code} for '{gamertag}'")

        if resp.status_code != 200:
            print(f"  Response body: {resp.text[:300]}")
            return None

        data = resp.json()

        # -- Primary: decode base64 'value' from the properties array --
        # This is the standard Mojang Java profile format used by mcprofile.io.
        for prop in data.get("properties", []):
            if prop.get("name") == "textures":
                try:
                    decoded = json.loads(
                        base64.b64decode(prop["value"]).decode("utf-8")
                    )
                    skin_url = decoded.get("textures", {}).get("SKIN", {}).get("url", "")
                    if skin_url:
                        texture_id = skin_url.rstrip("/").split("/")[-1]
                        print(f"  Found texture ID from properties: {texture_id[:16]}...")
                        return texture_id
                except Exception as decode_err:
                    print(f"  Failed to decode properties value: {decode_err}")

        # -- Fallback: scan raw response text for a textures.minecraft.net URL --
        # Handles any non-standard response shape.
        match = re.search(
            r'textures\.minecraft\.net/texture/([A-Fa-f0-9]+)',
            resp.text
        )
        if match:
            texture_id = match.group(1)
            print(f"  Found texture ID via URL regex: {texture_id[:16]}...")
            return texture_id

        # -- Nothing worked — print full response to help the user debug --
        print(f"  No texture ID found in mcprofile.io response.")
        print(f"  Response keys: {list(data.keys())}")
        print(f"  Full response: {resp.text[:500]}")
        return None

    except Exception as e:
        print(f"  mcprofile.io request failed for '{gamertag}': {e}")
        return None


def fetch_player_skin_texture(gamertag: str,
                               block_tex_path: str,
                               item_icon_path: str) -> bool:
    """
    Downloads the player skin and produces two PNG files:

    block_tex_path  – The FULL 64x64 skin sheet saved verbatim.
                      This is referenced by the block geometry (terrain_texture)
                      and the attachable.  The geometry model UVs map directly
                      onto this sheet, so every face of the head renders correctly.

    item_icon_path  – A 64x64 icon made by compositing the 8x8 base-layer face
                      with the 8x8 hat-overlay face and upscaling with NEAREST
                      filter.  Used in the inventory/hotbar via item_texture.json.

    Returns True only if both files were written successfully.
    """
    if not HAS_REQUESTS or not HAS_PIL:
        missing = "requests" if not HAS_REQUESTS else "Pillow"
        print(f"  Skipping skin fetch (missing library: {missing}).")
        print(f"  Place textures manually:")
        print(f"    Block texture : {block_tex_path}")
        print(f"    Item icon     : {item_icon_path}")
        return False

    texture_id = _get_texture_id_from_mcprofile(gamertag)
    if not texture_id:
        print(f"  Skin not resolved. Place textures manually:")
        print(f"    Block texture : {block_tex_path}")
        print(f"    Item icon     : {item_icon_path}")
        return False

    try:
        skin_url  = TEXTURE_DOWNLOAD_URL.format(texture_id=texture_id)
        print(f"  Downloading skin: {skin_url}")
        resp = requests.get(skin_url, timeout=15)

        if resp.status_code != 200:
            print(f"  textures.minecraft.net returned HTTP {resp.status_code}.")
            return False

        skin_img = Image.open(io.BytesIO(resp.content)).convert("RGBA")

        # Validate – Minecraft skins must be 64x64 (or 64x32 for legacy)
        if skin_img.width != 64 or skin_img.height not in (32, 64):
            print(f"  Unexpected skin size {skin_img.size} for '{gamertag}'. "
                  f"Expected 64x64 or 64x32.")
            return False

        # If this is a legacy 64x32 skin, pad it to 64x64 so hat-layer UVs
        # don't read outside bounds.
        if skin_img.height == 32:
            padded = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            padded.paste(skin_img, (0, 0))
            skin_img = padded
            print(f"  Legacy 64x32 skin padded to 64x64.")

        # ------------------------------------------------------------------
        # TWO separate texture files are needed:
        #
        # 1. BLOCK TEXTURE  (block_tex_path → terrain_texture.json)
        #    The BPH head geometry model's UV coordinates map onto the full
        #    64x64 Minecraft skin sheet. Each face of the head cube samples
        #    a different region of this sheet (front face at 8,8; top at 8,0;
        #    sides at 0,8 / 16,8; back at 24,8 etc.).
        #    Save the complete skin sheet so the geometry renders correctly
        #    on all faces when the block is placed in the world.
        #
        # 2. ITEM ICON  (item_icon_path → item_texture.json)
        #    The inventory/hotbar icon should show just the player face.
        #    Crop the 8x8 front-face region, composite the hat overlay on top,
        #    then upscale to 64x64 with nearest-neighbour for a crisp result.
        #
        # Skin UV regions (pixels on the 64x64 sheet):
        #   Base layer front face : (8, 8) → (16, 16)
        #   Hat overlay front face : (40,8) → (48, 16)
        # ------------------------------------------------------------------

        # -- Block texture: full skin sheet saved as-is --
        os.makedirs(os.path.dirname(block_tex_path), exist_ok=True)
        skin_img.save(block_tex_path, "PNG")
        print(f"  Saved block texture (full skin sheet): {block_tex_path}")

        # -- Item icon: front face + hat overlay, upscaled to 64x64 --
        base_face = skin_img.crop(SKIN_FACE_BASE)    # (8,8,16,16)
        hat_face  = skin_img.crop(SKIN_FACE_HAT)     # (40,8,48,16)
        face_icon = Image.alpha_composite(base_face.copy(), hat_face)
        face_icon = face_icon.resize(OUTPUT_ICON_SIZE, Image.NEAREST)

        os.makedirs(os.path.dirname(item_icon_path), exist_ok=True)
        face_icon.save(item_icon_path, "PNG")
        print(f"  Saved item icon (face crop 64x64): {item_icon_path}")

        return True

    except Exception as e:
        print(f"  Skin fetch/crop failed for '{gamertag}': {e}")
        return False


def fetch_all_skins(gamertags: list[str]):
    """
    Downloads skin textures for every gamertag in the list.
    Produces both the full-skin block texture and the face item icon.
    """
    print("\n--- Fetching player skin textures ---")
    for tag in gamertags:
        # Slug: lowercase + spaces→underscores to match terrain_texture.json paths
        slug = tag.lower().replace(" ", "_")
        block_tex  = os.path.join(RP_DIR, "textures", "blocks", "skulls", f"{slug}.png")
        item_icon  = os.path.join(RP_DIR, "textures", "items",  "skulls", f"{slug}.png")
        fetch_player_skin_texture(tag, block_tex, item_icon)


def missing_texture_paths(gamertags: list[str]) -> list[str]:
    missing = []
    for tag in gamertags:
        slug = tag.lower().replace(" ", "_")
        for folder in (
            os.path.join(RP_DIR, "textures", "blocks", "skulls"),
            os.path.join(RP_DIR, "textures", "items", "skulls"),
        ):
            path = os.path.join(folder, f"{slug}.png")
            if not os.path.isfile(path):
                missing.append(path)
    return missing



def write_vibrant_visuals_texture_sets():
    """
    Writes Texture Set JSON files for Vibrant Visuals/PBR.
    The existing PNG remains the color layer; MER [0, 0, 255] means
    non-metal, non-emissive, fully rough.
    """
    for texture_dir in (
        os.path.join(RP_DIR, "textures", "blocks", "skulls"),
        os.path.join(RP_DIR, "textures", "items", "skulls"),
    ):
        if not os.path.isdir(texture_dir):
            continue
        for filename in sorted(os.listdir(texture_dir)):
            if not filename.lower().endswith(".png"):
                continue
            stem = os.path.splitext(filename)[0]
            path = os.path.join(texture_dir, f"{stem}.texture_set.json")
            data = {
                "format_version": "1.21.30",
                "minecraft:texture_set": {
                    "color": stem,
                    "metalness_emissive_roughness": [0, 0, 255],
                },
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=4)
                f.write("\n")
    print("  Written Vibrant Visuals texture sets for skull textures.")



# ===========================================================================
# PACK ICON GENERATION
# Both the RP and BP need a pack_icon.png (512×512 recommended).
# We reuse the first gamertag's face texture if available; otherwise we
# create a simple placeholder coloured square so the pack always imports.
# ===========================================================================

ICON_SIZE = (512, 512)

def _make_placeholder_icon(colour: tuple) -> "Image.Image":
    img = Image.new("RGBA", ICON_SIZE, colour)
    return img


def write_empty_loot_table():
    """
    Writes BP/loot_tables/empty.json — referenced by minecraft:loot in every
    block definition. Prevents the block from dropping itself when broken;
    the head item is dropped by the Script API on player death instead.
    """
    path = f"{BP_DIR}/loot_tables/empty.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"pools": []}, f, indent=4)
    print(f"  Written empty loot table: {path}")


def generate_pack_icons():
    """Writes pack_icon.png to RP and BP directories."""
    if not HAS_PIL:
        print("Skipping pack_icon generation (Pillow not available).")
        return

    # Use the face-crop item icon (textures/items/skulls/) for the pack icon —
    # this is already the 64x64 face-only image, not the full skin sheet.
    source_path = None
    if GAMERTAGS:
        slug0 = GAMERTAGS[0].lower().replace(" ", "_")
        candidate = os.path.join(RP_DIR, "textures", "items", "skulls",
                                 f"{slug0}.png")
        if os.path.isfile(candidate):
            source_path = candidate

    for directory, colour in ((RP_DIR, (30, 160, 100, 255)),
                               (BP_DIR, (60,  80, 180, 255))):
        icon_path = os.path.join(directory, "pack_icon.png")
        os.makedirs(directory, exist_ok=True)

        if source_path:
            img = Image.open(source_path).convert("RGBA").resize(ICON_SIZE, Image.NEAREST)
        else:
            img = _make_placeholder_icon(colour)

        img.save(icon_path, "PNG")
        print(f"Wrote pack icon: {icon_path}")


# ===========================================================================
# .MCADDON BUILDER
# An .mcaddon file is a ZIP archive containing:
#   behavior_packs/<BP_NAME>/   ← everything in BPH_BP/
#   resource_packs/StreamerheadsResources/  <- everything in BPH_RP/
#
# Reference:
#   https://wiki.bedrock.dev/guide/project-setup-android
#   (An .mcaddon is both packs selected → compressed → renamed to .mcaddon)
# ===========================================================================

def build_mcaddon(output_path: str | None = None):
    """
    Zips BPH_RP and BPH_BP into a valid .mcaddon file.

    :param output_path: Destination file path.  Defaults to
                        '<ADDON_NAME>_v<VERSION>.mcaddon' in the CWD.
    """
    if output_path is None:
        ver_str  = "_".join(str(v) for v in VERSION)
        output_path = f"{ADDON_NAME}_v{ver_str}.mcaddon"
    output_parent = os.path.dirname(os.path.abspath(output_path))
    if output_parent:
        os.makedirs(output_parent, exist_ok=True)

    pack_map = {
        BP_DIR: f"{BP_NAME}",
        RP_DIR: f"{RP_NAME}",
    }

    missing = [d for d in pack_map if not os.path.isdir(d)]
    if missing:
        print(f"Error: Cannot build .mcaddon - directories not found: {missing}")
        return

    print(f"\n--- Building {output_path} ---")
    file_count = 0

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for local_dir, zip_prefix in pack_map.items():
            for root, _, files in os.walk(local_dir):
                for file in files:
                    local_path = os.path.join(root, file)
                    # Compute path inside the ZIP
                    rel_path   = os.path.relpath(local_path, local_dir)
                    arc_path   = f"{zip_prefix}/{rel_path}".replace("\\", "/")
                    zf.write(local_path, arc_path)
                    file_count += 1

    print(f"  Packed {file_count} files -> {output_path}")
    print(f"  Double-click or share the file to import into Minecraft Bedrock.")

# ---------------------------------------------------------------------------
# TEMPLATE REGISTRY
# Maps template type → JSON template + output path
# ---------------------------------------------------------------------------
TEMPLATE_REGISTRY = {

    # ------------------------------------------------------------------
    # ATTACHABLE  (RP)
    # Renders the head geometry when the item is worn or held.
    # format_version "1.10.0" is the correct, stable version for
    # attachables per wiki.bedrock.dev/items/attachables and remains
    # the de-facto standard even in 1.26.30.
    # ------------------------------------------------------------------
    "attachable": {
        # Per the working amegapint_head.json reference and original session state:
        #   - format_version 1.10.0
        #   - "item" query restricts attachable to player entity
        #   - materials: "armor"/"armor_enchanted" for head-slot worn items
        #   - geometry: "geometry.head_attachable" — per-head file in models/entity/
        #     with bone "head", pivot [0,24,0], cube origin [-4,24,-4], NO binding key
        #   - scripts.parent_setup hides vanilla helmet layer
        #   - render_controllers: controller.render.armor — correct for armor-slot items
        #     using a "head" bone at pivot [0,24,0] matching the player skeleton
        "template": {
            "format_version": "1.10.0",
            "minecraft:attachable": {
                "description": {
                    "identifier": "bph:[lower custom name]_head",
                    "item": {
                        "bph:[lower custom name]_head": "query.is_owner_identifier_any('minecraft:player')"
                    },
                    "materials": {
                        "default": "armor",
                        "enchanted": "armor_enchanted"
                    },
                    "textures": {
                        "default": "textures/blocks/skulls/[lower custom name]",
                        "enchanted": "textures/misc/enchanted_item_glint"
                    },
                    "geometry": {
                        "default": "geometry.head_attachable"
                    },
                    "scripts": {
                        "parent_setup": "variable.helmet_layer_visible = 0.0;"
                    },
                    "render_controllers": [
                        "controller.render.armor"
                    ]
                }
            }
        },
        "file_path": "BPH_RP/attachables/[lower custom name]_head.json"
    },

    # ------------------------------------------------------------------
    # ITEM  –  Resource Pack side  (RP)
    # In 1.26.30 the RP item file is ONLY needed if you want to override
    # the inventory icon texture shortname via minecraft:icon.
    # The old "category: null" trick is gone; use menu_category properly.
    # format_version bumped to 1.26.30 to match BP item.
    # ------------------------------------------------------------------
    "items_rp": {
        "template": {
            "format_version": "1.26.30",
            "minecraft:item": {
                "description": {
                    "identifier": "bph:[lower custom name]_head",
                    # RP items that are purely icon overrides need no menu_category
                },
                "components": {
                    # Shortname key must match an entry in RP/textures/item_texture.json
                    "minecraft:icon": {
                        "textures": {
                            "default": "[lower custom name]_head"
                        }
                    }
                }
            }
        },
        "file_path": "BPH_RP/items/[lower custom name]_head.json"
    },

    # ------------------------------------------------------------------
    # ITEM  –  Behaviour Pack side  (BP)
    # format_version 1.26.30 targets the latest stable release.
    # minecraft:max_stack_size now uses an integer directly (not {"value":1}).
    # minecraft:block_placer uses the correct 1.20.10+ syntax.
    # "itemGroup.name.skull" group key is correct for the skull group.
    # ------------------------------------------------------------------
    "items_bp": {
        "template": {
            "format_version": "1.26.30",
            "minecraft:item": {
                "description": {
                    "identifier": "bph:[lower custom name]_head",
                    "menu_category": {
                        "category": "items"
                    }
                },
                "components": {
                    "minecraft:display_name": {
                        "value": "item.bph:[lower custom name]_head"   # resolves via lang file
                    },
                    "minecraft:block_placer": {
                        "block": "bph:[lower custom name]_head_block"
                    },
                    "minecraft:max_stack_size": 1,        # integer, not {"value":1}
                    "minecraft:wearable": {
                        "slot": "slot.armor.head"
                    },
                    "minecraft:rarity": "uncommon"
                }
            }
        },
        "file_path": "BPH_BP/items/[lower custom name]_head.json"
    },

    # ------------------------------------------------------------------
    # BLOCK  (BP)
    # format_version 1.26.30 – targets latest stable release.
    # Changes vs old file:
    #   • "states" → "states" (renamed from "properties" in older format)
    #     but also removed "traits" from "description" – traits belong at
    #     the root "description" level, which is already the case here,
    #     but "states" must NOT live inside "description"; it was moved
    #     to the root "description" in 1.20.20+.  The original code had
    #     it inside description which is correct for 1.20.20+.
    #   • Permutation rotation logic reviewed – fixed logical OR (||)
    #     that caused overlap when head_rotation >= 4 AND face is east.
    #     Wall-face permutations should use ONLY the face query; floor
    #     rotation permutations should be face == 'up'.  Separated them.
    #   • minecraft:display_name added so the block shows the right name
    #     in the "can place on" tooltip (requires 1.19.60+).
    #   • ambient_occlusion fix landed in 1.26.30 – field now works
    #     correctly in minecraft:material_instances.
    # ------------------------------------------------------------------
    "block": {
        "template": {
            "format_version": "1.26.30",
            "minecraft:block": {
                "description": {
                    "identifier": "bph:[lower custom name]_head_block",
                    "menu_category": {
                        "category": "none",
                        "is_hidden_in_commands": True
                    },
                    "traits": {
                        "minecraft:placement_position": {
                            "enabled_states": [
                                "minecraft:block_face"
                            ]
                        }
                    },
                    "states": {
                        "bph:head_rotation": {
                            "values": {
                                "min": 0,
                                "max": 15
                            }
                        }
                    }
                },
                "components": {
                    "minecraft:display_name": "tile.bph:[lower custom name]_head_block.name",
                    "minecraft:liquid_detection": {
                        "detection_rules": [
                            {
                                "can_contain_liquid": True
                            }
                        ]
                    },
                    "minecraft:destructible_by_mining": {
                        "seconds_to_destroy": 1.5
                    },
                    # Floor placement collision / selection box (8×8×8, sitting on ground)
                    "minecraft:collision_box": {
                        "origin": [-4, 0, -4],
                        "size":   [8,  8,  8]
                    },
                    "minecraft:selection_box": {
                        "origin": [-4, 0, -4],
                        "size":   [8,  8,  8]
                    },
                    "minecraft:geometry": {
                        "identifier": "geometry.[lower custom name]_[custom model name]",
                        "bone_visibility": {
                            # Floor variants – four 22.5° increments per quadrant
                            "up_0":    "q.block_state('minecraft:block_face') == 'up' && math.mod(q.block_state('bph:head_rotation'), 4) == 0",
                            "up_22_5": "q.block_state('minecraft:block_face') == 'up' && math.mod(q.block_state('bph:head_rotation'), 4) == 1",
                            "up_45":   "q.block_state('minecraft:block_face') == 'up' && math.mod(q.block_state('bph:head_rotation'), 4) == 2",
                            "up_67_5": "q.block_state('minecraft:block_face') == 'up' && math.mod(q.block_state('bph:head_rotation'), 4) == 3",
                            # Wall variant (any side face)
                            "side":    "q.block_state('minecraft:block_face') != 'up'"
                        }
                    },
                    "minecraft:item_visual": {
                        "geometry": {
                            "identifier": "geometry.[lower custom name]_[custom model name]_display"
                        },
                        "material_instances": {
                            "*": {
                                "texture":      "[lower custom name]_head",
                                "face_dimming": False
                            }
                        }
                    },
                    "minecraft:material_instances": {
                        "*": {
                            "texture":            "[lower custom name]_head",
                            "ambient_occlusion":  False,
                            "render_method":      "alpha_test"
                        },
                        "down": {
                            "texture":       "soul_sand",
                            "render_method": "alpha_test"
                        }
                    },
                    "minecraft:loot": "loot_tables/empty.json",
                    "minecraft:light_dampening": 0,
                    "minecraft:placement_filter": {
                        "conditions": [
                            {
                                "allowed_faces": ["up", "side"]
                            }
                        ]
                    }
                },
                "permutations": [
                    # ---- Wall-face rotations (block_face != 'up') ----
                    # North  → no extra Y rotation needed (default facing)
                    {
                        "condition": "q.block_state('minecraft:block_face') == 'east'",
                        "components": {
                            "minecraft:transformation": {"rotation": [0, -90, 0]},
                            "minecraft:collision_box":  {"origin": [-5, 3, 0], "size": [10, 10, 10]},
                            "minecraft:selection_box":  {"origin": [-5, 3, 0], "size": [10, 10, 10]}
                        }
                    },
                    {
                        "condition": "q.block_state('minecraft:block_face') == 'south'",
                        "components": {
                            "minecraft:transformation": {"rotation": [0, 180, 0]},
                            "minecraft:collision_box":  {"origin": [-5, 3, 0], "size": [10, 10, 10]},
                            "minecraft:selection_box":  {"origin": [-5, 3, 0], "size": [10, 10, 10]}
                        }
                    },
                    {
                        "condition": "q.block_state('minecraft:block_face') == 'west'",
                        "components": {
                            "minecraft:transformation": {"rotation": [0, 90, 0]},
                            "minecraft:collision_box":  {"origin": [-5, 3, 0], "size": [10, 10, 10]},
                            "minecraft:selection_box":  {"origin": [-5, 3, 0], "size": [10, 10, 10]}
                        }
                    },
                    {
                        "condition": "q.block_state('minecraft:block_face') == 'north'",
                        "components": {
                            "minecraft:collision_box": {"origin": [-5, 3, 0], "size": [10, 10, 10]},
                            "minecraft:selection_box": {"origin": [-5, 3, 0], "size": [10, 10, 10]}
                        }
                    },
                    # ---- Floor rotation quadrants (block_face == 'up') ----
                    # head_rotation 0-3   → 0°    (south-facing, default)
                    # head_rotation 4-7   → -90°  (west-facing)
                    # head_rotation 8-11  → 180°  (north-facing)
                    # head_rotation 12-15 → 90°   (east-facing)
                    {
                        "condition": "q.block_state('minecraft:block_face') == 'up' && q.block_state('bph:head_rotation') >= 4 && q.block_state('bph:head_rotation') < 8",
                        "components": {
                            "minecraft:transformation": {"rotation": [0, -90, 0]}
                        }
                    },
                    {
                        "condition": "q.block_state('minecraft:block_face') == 'up' && q.block_state('bph:head_rotation') >= 8 && q.block_state('bph:head_rotation') < 12",
                        "components": {
                            "minecraft:transformation": {"rotation": [0, 180, 0]}
                        }
                    },
                    {
                        "condition": "q.block_state('minecraft:block_face') == 'up' && q.block_state('bph:head_rotation') >= 12",
                        "components": {
                            "minecraft:transformation": {"rotation": [0, 90, 0]}
                        }
                    }
                ]
            }
        },
        "file_path": "BPH_BP/blocks/[lower custom name]_head.json"
    }
}


# ---------------------------------------------------------------------------
# update_index_js
# ---------------------------------------------------------------------------
def update_index_js(custom_name):
    """Appends a new head entry to the headArray in BPH_BP/scripts/index.js."""
    file_name = "BPH_BP/scripts/index.js"
    formatted_custom_name = custom_name.lower().replace(" ", "_")

    new_element = (
        f'["bph:{formatted_custom_name}_head", '
        f'"bph:{formatted_custom_name}_head_block"]'
    )

    try:
        with open(file_name, "r") as f:
            content = f.read()

        match = re.search(r"const headArray\s*=\s*\[.*?\];", content, re.DOTALL)
        if not match:
            print(f"Error: {file_name} does not contain the expected headArray definition.")
            return

        array_body = match.group(0)
        # Strip outer brackets and trim whitespace
        inner = array_body[array_body.index('[') + 1: array_body.rindex(']')].strip()
        # Guard against duplicate entries
        if f'"bph:{formatted_custom_name}_head"' in inner:
            print(f"Warning: {formatted_custom_name} already exists in headArray - skipping.")
            return

        separator = ",\n    " if inner else ""
        updated_array = f"const headArray = [\n    {inner}{separator}{new_element}\n];"
        before = content[:match.start()]
        after  = content[match.end():]

        with open(file_name, "w") as f:
            f.write(before + updated_array + after)

        print(f"Added '{formatted_custom_name}' to {file_name}")

    except FileNotFoundError:
        print(f"Error: {file_name} not found.")
    except Exception as e:
        print(f"An error occurred updating index.js: {e}")


# ---------------------------------------------------------------------------
# create_json_from_template
# ---------------------------------------------------------------------------
def _build_head_cube(pivot_y: float = 4.0, rotation_y: float = 0.0) -> dict:
    """
    Returns a single Bedrock geometry bone dict containing one 8x8x8 head cube.

    The cube sits centred at x=0, z=0, bottom at y=0 (origin [-4,0,-4]).
    UV mapping targets the standard Minecraft skin-sheet head region on a
    64x64 skin texture:
        North (front face) : u=8,  v=8  – the player face
        South (back)       : u=24, v=8
        East  (right)      : u=16, v=8
        West  (left)       : u=0,  v=8
        Up    (top)        : u=8,  v=0
        Down  (bottom)     : u=16, v=0

    pivot_y   – Y position of the rotation pivot (8 = centre of cube at origin [-4,4,-4]).
    rotation_y – Pre-baked Y rotation in degrees for the 22.5° sub-bones.
    """
    return {
        "origin":   [-5, 0, -5],
        "size":     [10, 10, 10],
        "pivot":    [0, pivot_y, 0],
        "rotation": [0, rotation_y, 0],
        "uv": {
            "north": {"uv": [8,  8],  "uv_size": [8, 8]},
            "south": {"uv": [24, 8],  "uv_size": [8, 8]},
            "east":  {"uv": [16, 8],  "uv_size": [8, 8]},
            "west":  {"uv": [0,  8],  "uv_size": [8, 8]},
            "up":    {"uv": [8,  0],  "uv_size": [8, 8]},
            "down":  {"uv": [16, 0],  "uv_size": [8, 8]}
        }
    }


def _build_wall_cube(rotation_y: float = 0.0) -> dict:
    """
    Cube for wall-mounted placement.
    Centred vertically (Y=3 to Y=13) and flush against the wall back face (Z=0 to Z=10).
    The bone pivot sits at the cube centre: [0, 8, 5].
    """
    return {
        "origin":   [-5, 3, 0],
        "size":     [10, 10, 10],
        "pivot":    [0, 8, 5],
        "rotation": [0, rotation_y, 0],
        "uv": {
            "north": {"uv": [8,  8],  "uv_size": [8, 8]},
            "south": {"uv": [24, 8],  "uv_size": [8, 8]},
            "east":  {"uv": [16, 8],  "uv_size": [8, 8]},
            "west":  {"uv": [0,  8],  "uv_size": [8, 8]},
            "up":    {"uv": [8,  0],  "uv_size": [8, 8]},
            "down":  {"uv": [16, 0],  "uv_size": [8, 8]}
        }
    }


def create_geometry_files(head_name: str, model_name: str = "head"):
    """
    Generates two geometry files required for the head to render correctly:

    1. geometry.<model_name>  (block geo)
       Used by the placed block.  Contains 5 bones:
         up_0    – floor placement, 0° rotation
         up_22_5 – floor placement, 22.5° rotation
         up_45   – floor placement, 45° rotation
         up_67_5 – floor placement, 67.5° rotation
         side    – wall-mounted placement (no Y rotation; the block permutation
                   handles rotation via minecraft:transformation)

    2. geometry.<model_name>_attachable  (attachable/worn geo)
       Used when the item is held in hand or worn on the head.
       Single bone containing the same 8x8x8 cube, no pre-baked rotation.

    Both use texture_width=64, texture_height=64 to match the full skin sheet.
    Files are written to BPH_RP/models/blocks/ and will NOT overwrite existing
    custom geometry files (e.g. if the creator supplies their own model).
    """
    lower = head_name.lower().replace(" ", "_")

    # ----------------------------------------------------------------
    # 1. Block geometry
    # ----------------------------------------------------------------
    block_geo_path = f"BPH_RP/models/blocks/{lower}_{model_name}.geo.json"

    block_geo = {
        "format_version": "1.21.0",
        "minecraft:geometry": [
            {
                "description": {
                    "identifier":      f"geometry.{lower}_{model_name}",
                    "texture_width":   64,
                    "texture_height":  64,
                    "visible_bounds_width":  2,
                    "visible_bounds_height": 2.5,
                    "visible_bounds_offset": [0, 0.75, 0]
                },
                "bones": [
                    {
                        "name":   "up_0",
                        "pivot":  [0, 0, 0],
                        "cubes":  [_build_head_cube(pivot_y=5.0, rotation_y=0)]
                    },
                    {
                        "name":   "up_22_5",
                        "pivot":  [0, 0, 0],
                        "cubes":  [_build_head_cube(pivot_y=5.0, rotation_y=22.5)]
                    },
                    {
                        "name":   "up_45",
                        "pivot":  [0, 0, 0],
                        "cubes":  [_build_head_cube(pivot_y=5.0, rotation_y=45)]
                    },
                    {
                        "name":   "up_67_5",
                        "pivot":  [0, 0, 0],
                        "cubes":  [_build_head_cube(pivot_y=5.0, rotation_y=67.5)]
                    },
                    {
                        "name":   "side",
                        "pivot":  [0, 0, 0],
                        "cubes":  [_build_wall_cube(rotation_y=0)]
                    }
                ]
            }
        ]
    }

    os.makedirs(os.path.dirname(block_geo_path), exist_ok=True)
    with open(block_geo_path, "w") as f:
        json.dump(block_geo, f, indent=4)
    print(f"  Created block geometry: {block_geo_path}")

    # ----------------------------------------------------------------
    # 2. Display geometry (minecraft:item_visual)
    # A single-bone 8x8x8 cube used to render the head as a 3D item
    # in the inventory and when dropped on the ground.
    # ----------------------------------------------------------------
    display_geo_path = f"BPH_RP/models/blocks/{lower}_{model_name}_display.geo.json"

    display_geo = {
        "format_version": "1.21.0",
        "minecraft:geometry": [
            {
                "description": {
                    "identifier":     f"geometry.{lower}_{model_name}_display",
                    "texture_width":  64,
                    "texture_height": 64
                },
                "bones": [
                    {
                        "name":  "head",
                        "pivot": [0, 0, 0],
                        "cubes": [
                            {
                                "origin": [-4, -4, -4],
                                "size":   [8, 8, 8],
                                "uv": {
                                    # minecraft:item_visual renders with the camera
                                    # looking north→south, so the SOUTH face is what
                                    # faces the player in the inventory slot.
                                    # Swap north/south so the player face (UV 8,8)
                                    # lands on south (visible) and the back (UV 24,8)
                                    # lands on north (away from camera).
                                    "north": {"uv": [24, 8], "uv_size": [8, 8]},
                                    "south": {"uv": [8,  8], "uv_size": [8, 8]},
                                    "east":  {"uv": [16, 8], "uv_size": [8, 8]},
                                    "west":  {"uv": [0,  8], "uv_size": [8, 8]},
                                    "up":    {"uv": [8,  0], "uv_size": [8, 8]},
                                    "down":  {"uv": [16, 0], "uv_size": [8, 8]}
                                }
                            }
                        ]
                    }
                ]
            }
        ]
    }

    os.makedirs(os.path.dirname(display_geo_path), exist_ok=True)
    with open(display_geo_path, "w") as f:
        json.dump(display_geo, f, indent=4)
    print(f"  Created display geometry: {display_geo_path}")

    # ----------------------------------------------------------------
    # 3. Attachable geometry (worn on head slot)
    #    No binding — controller.render.armor handles correct head-slot placement.
    #    pivot [0,24,0] and origin [-4,24,-4] match the player head bone in world space.
    #    inflate 0.5 pushes the cube just outside the player's own head skin layer
    #    to prevent skin bleed-through.
    # ----------------------------------------------------------------
    attach_geo_path = f"BPH_RP/models/entity/{lower}_{model_name}_attachable.geo.json"

    attach_geo = {
        "format_version": "1.16.0",
        "minecraft:geometry": [
            {
                "description": {
                    "identifier":            "geometry.head_attachable",
                    "texture_width":         64,
                    "texture_height":        64,
                    "visible_bounds_width":  2,
                    "visible_bounds_height": 2,
                    "visible_bounds_offset": [0, 1, 0]
                },
                "bones": [
                    {
                        "name":  "head",
                        "pivot": [0, 24, 0],
                        "cubes": [
                            {
                                "origin":  [-4, 24, -4],
                                "size":    [8, 8, 8],
                                "inflate": 0.5,
                                "uv": {
                                    "north": {"uv": [8,  8], "uv_size": [8, 8]},
                                    "south": {"uv": [24, 8], "uv_size": [8, 8]},
                                    "east":  {"uv": [16, 8], "uv_size": [8, 8]},
                                    "west":  {"uv": [0,  8], "uv_size": [8, 8]},
                                    "up":    {"uv": [8,  0], "uv_size": [8, 8]},
                                    "down":  {"uv": [16, 0], "uv_size": [8, 8]}
                                }
                            }
                        ]
                    }
                ]
            }
        ]
    }

    os.makedirs(os.path.dirname(attach_geo_path), exist_ok=True)
    with open(attach_geo_path, "w") as f:
        json.dump(attach_geo, f, indent=4)
    print(f"  Created attachable geometry: {attach_geo_path}")


def write_shared_attachable_geo():
    pass  # per-head attachable geos are written by create_geometry_files()


def create_json_from_template(template_type, head_name, model_name=None):
    """
    Creates a JSON file from a template, replacing placeholders with the
    supplied head_name and optional model_name.
    """
    lower_head_name = head_name.lower().replace(" ", "_")

    if template_type not in TEMPLATE_REGISTRY:
        print(f"Error: Invalid template type '{template_type}'.")
        return

    entry             = TEMPLATE_REGISTRY[template_type]
    template          = entry["template"]
    file_path_tpl     = entry["file_path"]

    # Deep-copy via JSON round-trip, substituting placeholders
    raw = (
        json.dumps(template)
        .replace("[custom name]",       head_name)
        .replace("[lower custom name]", lower_head_name)
        .replace("[custom model name]", model_name or "head")
    )
    customized = json.loads(raw)

    file_name = file_path_tpl.replace("[lower custom name]", lower_head_name)
    os.makedirs(os.path.dirname(file_name), exist_ok=True)

    try:
        with open(file_name, "w") as f:
            json.dump(customized, f, indent=4)
        print(f"Created {file_name}")
    except IOError as e:
        print(f"Error writing {file_name}: {e}")


# ---------------------------------------------------------------------------
# update_json  (general-purpose helper)
# ---------------------------------------------------------------------------
def update_json(file_name, key, update_data, nested_field=None):
    """
    Adds or updates a key inside a JSON file.
    If nested_field is given, the update is applied inside that sub-object.
    """
    try:
        with open(file_name, "r") as f:
            data = json.load(f)

        if nested_field:
            if nested_field not in data:
                print(f"Error: '{nested_field}' not found in {file_name}.")
                return
            data[nested_field][key] = update_data
        else:
            data[key] = update_data

        with open(file_name, "w") as f:
            json.dump(data, f, indent=4)
        print(f"Updated {file_name} with key '{key}'.")

    except FileNotFoundError:
        print(f"Error: {file_name} not found.")
    except json.JSONDecodeError:
        print(f"Error: Failed to parse {file_name} as JSON.")


# ---------------------------------------------------------------------------
# update_place_sounds
# Writes the placement sound for the block into RP/blocks.json.
# blocks.json is still valid in 1.26.30 as the sound-configuration layer
# (geometry/material overrides now live in BP block JSON).
# ---------------------------------------------------------------------------
def update_place_sounds(head_name):
    """Registers the block placement sound in RP/blocks.json."""
    lower_head_name = head_name.lower().replace(" ", "_")
    file_name  = "BPH_RP/blocks.json"
    block_key  = f"bph:{lower_head_name}_head_block"
    # "stone" gives the correct dull-thud skull placement sound
    new_block  = {"sound": "stone"}
    update_json(file_name, block_key, new_block)


# ---------------------------------------------------------------------------
# update_terrain_texture
# ---------------------------------------------------------------------------
def update_terrain_texture(head_name):
    """Adds the block texture shortname to RP/textures/terrain_texture.json."""
    lower_head_name = head_name.lower().replace(" ", "_")
    file_name    = "BPH_RP/textures/terrain_texture.json"
    shortname    = f"{lower_head_name}_head"
    texture_path = f"textures/blocks/skulls/{lower_head_name}"
    update_json(file_name, shortname, {"textures": texture_path}, nested_field="texture_data")


# ---------------------------------------------------------------------------
# update_item_texture
# NEW – registers the item icon shortname in RP/textures/item_texture.json
# so that minecraft:icon can reference it by shortname.
# ---------------------------------------------------------------------------
def update_item_texture(head_name):
    """Adds the item icon shortname to RP/textures/item_texture.json."""
    lower_head_name = head_name.lower().replace(" ", "_")
    file_name    = "BPH_RP/textures/item_texture.json"
    shortname    = f"{lower_head_name}_head"
    texture_path = f"textures/items/skulls/{lower_head_name}"
    update_json(file_name, shortname, {"textures": texture_path}, nested_field="texture_data")


# ---------------------------------------------------------------------------
# update_lang_file
# Uses the modern translation key format:
#   • block display_name key  →  "tile.<id>.name"
#   • item display_name key   →  "item.<id>"
# Note: the old "tile.bph:…" prefix still works in 1.26.30 for blocks
# because Minecraft falls back to it when minecraft:display_name is absent.
# We now also output the item key to match the minecraft:display_name
# component value set in items_bp above.
# ---------------------------------------------------------------------------
def update_lang_file(head_name):
    """Appends translation entries to RP/texts/en_US.lang."""
    file_name       = "BPH_RP/texts/en_US.lang"
    lower           = head_name.lower().replace(" ", "_")
    block_key       = f"tile.bph:{lower}_head_block.name={head_name} Head"
    item_key        = f"item.bph:{lower}_head={head_name} Head"

    try:
        with open(file_name, "a") as f:
            f.write(f"\n{block_key}\n{item_key}\n")
        print(f"Updated lang file for '{head_name}'.")
    except FileNotFoundError:
        print(f"Error: {file_name} not found.")


# ---------------------------------------------------------------------------
# createRecipes
# Generates a toHead and toBlock conversion recipe.
# format_version "1.20.10" is the correct stable version for recipes.
# unlock array now references the ingredient item so the recipe auto-
# unlocks when the player picks up the ingredient (1.20.10+ feature).
# ---------------------------------------------------------------------------
def _build_recipe(result_id, ingredient_id):
    """Returns a shaped recipe JSON dict converting ingredient → result."""
    return {
        "format_version": "1.20.10",
        "minecraft:recipe_shaped": {
            "description": {
                "identifier": f"bph:{result_id}"
            },
            "tags": ["crafting_table"],
            "group": "itemGroup.name.skull",
            "pattern": ["#"],
            "key": {
                "#": {"item": f"bph:{ingredient_id}"}
            },
            "unlock": [
                {"item": f"bph:{ingredient_id}"}
            ],
            "result": {
                "item":  f"bph:{result_id}",
                "count": 1
            }
        }
    }


def createRecipes(head_name):
    """Writes toHead and toBlock recipe files for the given head."""
    lower = head_name.lower().replace(" ", "_")
    head_id  = f"{lower}_head"
    block_id = f"{lower}_head_block"

    pairs = [
        (head_id,  block_id, "toHead"),   # block → item (hold/wear)
        (block_id, head_id,  "toBlock"),  # item  → block (place)
    ]

    for result, ingredient, suffix in pairs:
        path = f"BPH_BP/recipes/{lower}_{suffix}.json"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = _build_recipe(result, ingredient)
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=4)
            print(f"Created recipe: {path}")
        except IOError as e:
            print(f"Error writing {path}: {e}")


# ---------------------------------------------------------------------------
# get_player_data
# Reads head config directly from the HEADS dict at the top of this file.
# No external HeadsToCreate.txt needed — just edit HEADS above and re-run.
# ---------------------------------------------------------------------------
def get_player_data() -> dict:
    """Returns a normalised copy of the HEADS config dict."""
    normalised = {}
    for name, cfg in HEADS.items():
        model = (cfg.get("model") or "").strip() or None
        normalised[name] = {"model": model}
    return normalised


# ===========================================================================
# WANDERING TRADER TRADE TABLE
#
# Root cause of blank UI (confirmed from wiki.bedrock.dev/loot/trading-behavior):
#
#   "If you add the [trade_table] component in components, it will cause all
#    kinds of problems, including blank trading UIs for all entities in the
#    world. Because of an issue with the trading AI goals, they must be added
#    in component groups."
#
#   The vanilla wandering_trader entity declares minecraft:economy_trade_table
#   directly in "components" — which triggers this exact engine bug when our
#   BP override changes that file.
#
# CORRECT TWO-FILE APPROACH:
#
#   BP/trading/economy_trades/wandering_trader_trades.json
#     The combined trade table (vanilla trades + heads tier).
#     Placed at the exact vanilla path so Bedrock loads our version instead.
#     No entity override file is written — any entity override risks breaking
#     vanilla wandering trader AI, physics, and spawning behaviour.
# ===========================================================================

TRADER_MAX_USES   = 3
TRADER_PRICE_ITEM = "minecraft:diamond_block"
TRADER_PRICE_QTY  = 1

# ---------------------------------------------------------------------------
# Vanilla wandering trader groups — copied verbatim from the actual vanilla
# file at:
#   learn.microsoft.com → vanillabehaviorpack_snippets/trading/economy_trades/
#   wandering_trader_trades.json
#
# CRITICAL FINDINGS from reading the real file:
#   • There is ONE tier only — no total_exp_required on tier 0.
#   • Group 1: num_to_select=5  (picks 5 random trades from ~37 options)
#   • Group 2: num_to_select=1  (picks 1 special trade from 6 options)
#   • No "trader_exp" or "reward_exp" fields — vanilla omits them entirely.
#   • Our heads group is appended as Group 3 in the SAME tier so it always
#     shows — a second tier would never unlock because the wandering trader
#     never gains XP (all vanilla trader_exp values are 0 / absent).
# ---------------------------------------------------------------------------
_VANILLA_GROUP1 = {
    "num_to_select": 5,
    "trades": [
        {"max_uses": 5,  "wants": [{"item": "minecraft:emerald", "quantity": 2}], "gives": [{"item": "minecraft:sea_pickle"}]},
        {"max_uses": 5,  "wants": [{"item": "minecraft:emerald", "quantity": 4}], "gives": [{"item": "minecraft:slime_ball"}]},
        {"max_uses": 5,  "wants": [{"item": "minecraft:emerald", "quantity": 2}], "gives": [{"item": "minecraft:glowstone"}]},
        {"max_uses": 5,  "wants": [{"item": "minecraft:emerald", "quantity": 5}], "gives": [{"item": "minecraft:nautilus_shell"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:tallgrass:2"}]},
        {"max_uses": 8,  "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:reeds"}]},
        {"max_uses": 4,  "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:pumpkin"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 3}], "gives": [{"item": "minecraft:kelp"}]},
        {"max_uses": 8,  "wants": [{"item": "minecraft:emerald", "quantity": 3}], "gives": [{"item": "minecraft:cactus"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:yellow_flower"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:red_flower:0"}]},
        {"max_uses": 8,  "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:red_flower:1"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:red_flower:2"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:red_flower:3"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:red_flower:4"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:red_flower:5"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:red_flower:6"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:red_flower:7"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:red_flower:8"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:red_flower:9"}]},
        {"max_uses": 7,  "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:red_flower:10"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:wheat_seeds"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:beetroot_seeds"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:pumpkin_seeds"}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:melon_seeds"}]},
        {"max_uses": 12, "weight": 4, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"choice": [{"item": "minecraft:wheat_seeds"}, {"item": "minecraft:pumpkin_seeds"}, {"item": "minecraft:melon_seeds"}, {"item": "minecraft:beetroot_seeds"}]}]},
        {"max_uses": 8,  "weight": 6, "wants": [{"item": "minecraft:emerald", "quantity": 5}], "gives": [{"choice": [{"item": "minecraft:sapling", "functions": [{"function": "random_block_state", "block_state": "sapling_type", "values": {"min": 0, "max": 5}}]}, {"item": "minecraft:mangrove_propagule"}]}]},
        {"max_uses": 12, "weight": 16, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:dye", "quantity": 3, "functions": [{"function": "random_aux_value", "values": {"min": 0, "max": 15}}]}]},
        {"max_uses": 8,  "weight": 5, "wants": [{"item": "minecraft:emerald", "quantity": 3}], "gives": [{"item": "minecraft:coral_block", "quantity": 1, "functions": [{"function": "random_block_state", "block_state": "coral_color", "values": {"min": 0, "max": 4}}]}]},
        {"max_uses": 12, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:vine"}]},
        {"max_uses": 12, "weight": 2, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"choice": [{"item": "minecraft:brown_mushroom"}, {"item": "minecraft:red_mushroom"}]}]},
        {"max_uses": 5,  "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:waterlily", "quantity": 2}]},
        {"max_uses": 5,  "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:small_dripleaf_block", "quantity": 2}]},
        {"max_uses": 8,  "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:sand:0", "quantity": 8}]},
        {"max_uses": 6,  "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:sand:1", "quantity": 4}]},
        {"max_uses": 5,  "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:pointed_dripstone", "quantity": 2}]},
        {"max_uses": 5,  "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:dirt_with_roots", "quantity": 2}]},
        {"max_uses": 5,  "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:moss_block", "quantity": 2}]},
    ]
}

_VANILLA_GROUP2 = {
    "num_to_select": 1,
    "trades": [
        {"max_uses": 4, "wants": [{"item": "minecraft:emerald", "quantity": 5}], "gives": [{"item": "minecraft:bucket:4"}]},
        {"max_uses": 4, "wants": [{"item": "minecraft:emerald", "quantity": 5}], "gives": [{"item": "minecraft:bucket:5"}]},
        {"max_uses": 6, "wants": [{"item": "minecraft:emerald", "quantity": 3}], "gives": [{"item": "minecraft:packed_ice"}]},
        {"max_uses": 6, "wants": [{"item": "minecraft:emerald", "quantity": 6}], "gives": [{"item": "minecraft:blue_ice"}]},
        {"max_uses": 8, "wants": [{"item": "minecraft:emerald", "quantity": 1}], "gives": [{"item": "minecraft:gunpowder"}]},
        {"max_uses": 6, "wants": [{"item": "minecraft:emerald", "quantity": 3}], "gives": [{"item": "minecraft:podzol", "quantity": 3}]},
    ]
}


def build_trade_table(head_names):
    # Builds the combined trade table.
    #
    # Structure: single tier, three groups:
    #   Group 1 (vanilla): num_to_select=5 from ~37 trades
    #   Group 2 (vanilla): num_to_select=1 from 6 special trades
    #   Group 3 (custom):  num_to_select=all 24 — every head always shown
    #
    # All groups are in ONE tier with no total_exp_required, matching the
    # real vanilla file exactly. A second tier would NEVER unlock because
    # the wandering trader earns no XP (all trades have no trader_exp).
    import copy
    head_trades = []
    for name in head_names:
        lower = name.lower().replace(" ", "_")
        head_trades.append({
            "wants":    [{"item": TRADER_PRICE_ITEM, "quantity": TRADER_PRICE_QTY}],
            "gives":    [{"item": "bph:{}_head".format(lower)}],
            "max_uses": TRADER_MAX_USES,
        })

    return {
        "tiers": [
            {
                "groups": [
                    copy.deepcopy(_VANILLA_GROUP1),
                    copy.deepcopy(_VANILLA_GROUP2),
                    {
                        "num_to_select": len(head_trades),
                        "trades": head_trades,
                    },
                ]
            }
        ]
    }


def write_trade_table(head_names):
    # Writes the combined trade table to the vanilla path so Bedrock uses
    # our version instead of the built-in file.
    path = "{}/trading/economy_trades/wandering_trader_trades.json".format(BP_DIR)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = build_trade_table(head_names)
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
    print("  Written trade table ({} heads + vanilla): {}".format(len(head_names), path))



# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv=None):
    import shutil
    global VERSION
    args = parse_args(argv)
    apply_head_selection(args)
    if args.version:
        VERSION = list(args.version)

    # ------------------------------------------------------------------
    # Step 0 – Auto-increment version if any gamertag already has output
    # files from a previous run.  Checked before anything is written so
    # the new version number is used in manifests and the mcaddon filename.
    # ------------------------------------------------------------------
    def _existing_head_file(name):
        lower = name.lower().replace(" ", "_")
        return os.path.isfile(
            os.path.join(BP_DIR, "items", f"{lower}_head.json")
        )

    if any(_existing_head_file(tag) for tag in HEADS) and not args.no_version_bump and not args.version:
        VERSION = _bump_version(VERSION)
        _save_version(VERSION)
        ver_str = ".".join(str(x) for x in VERSION)
        print(f"Existing addon detected - bumped version to {ver_str}")
    else:
        _save_version(VERSION)
        ver_str = ".".join(str(x) for x in VERSION)
        print(f"First run - version {ver_str}")

    # ------------------------------------------------------------------
    # Step 0a – Remove stale mixed-case skull textures from previous runs.
    # If an old PPTribalize.png exists alongside the new pptribalize.png
    # Minecraft may load the wrong one.  Wipe both skull texture dirs so
    # only the freshly-downloaded lowercase files remain.
    # ------------------------------------------------------------------
    for skull_dir in (
        os.path.join(RP_DIR, "textures", "blocks", "skulls"),
        os.path.join(RP_DIR, "textures", "items",  "skulls"),
    ):
        if os.path.isdir(skull_dir):
            shutil.rmtree(skull_dir)
            print(f"Cleared stale textures: {skull_dir}")

    # ------------------------------------------------------------------
    # Step 0b – Scaffold the full pack directory + boilerplate files
    # Must run before anything else so every update_* function finds its file
    # ------------------------------------------------------------------
    initialize_pack_structure()

    # ------------------------------------------------------------------
    # Step 1 – Write manifests
    # ------------------------------------------------------------------
    print("--- Writing manifests ---")
    write_manifests()

    # ------------------------------------------------------------------
    # Step 2 – Auto-fetch player skin textures (needs internet + Pillow)
    # ------------------------------------------------------------------
    fetch_all_skins(GAMERTAGS)
    missing_textures = missing_texture_paths(GAMERTAGS)
    if args.require_textures and missing_textures:
        print("Error: Missing generated skin textures:")
        for path in missing_textures:
            print(f"  {path}")
        raise SystemExit(1)
    write_vibrant_visuals_texture_sets()

    # ------------------------------------------------------------------
    # Step 3 – Generate pack icons for RP and BP
    # ------------------------------------------------------------------
    generate_pack_icons()
    write_empty_loot_table()
    write_shared_attachable_geo()

    # ------------------------------------------------------------------
    # Step 4 – Process each head entry from the HEADS dict (top of file)
    # ------------------------------------------------------------------
    player_data = get_player_data()

    for head_name, data in player_data.items():
        model_name = data["model"] or "head"

        print(f"\n--- Processing: {head_name} ---")

        # Script registration
        update_index_js(head_name)

        # JSON files
        create_json_from_template("attachable", head_name, model_name)
        create_json_from_template("items_rp",   head_name)
        create_json_from_template("items_bp",   head_name)
        create_json_from_template("block",      head_name, model_name)
        create_geometry_files(head_name, model_name)


        # Registry / atlas updates
        update_lang_file(head_name)
        update_terrain_texture(head_name)
        update_item_texture(head_name)
        update_place_sounds(head_name)

        # Recipes
        createRecipes(head_name)

    # ------------------------------------------------------------------
    # Step 4b – Wandering trader trade table
    # Writes BP/trading/economy_trades/wandering_trader_trades.json at the
    # exact vanilla path. Bedrock uses the BP version instead of the
    # built-in one — no entity override needed or wanted (any entity
    # override file risks breaking vanilla AI/physics).
    # ------------------------------------------------------------------
    print("\n--- Generating wandering trader trades ---")
    write_trade_table(list(HEADS.keys()))

    # ------------------------------------------------------------------
    # Step 5 – Package everything into a distributable .mcaddon file
    # ------------------------------------------------------------------
    build_mcaddon(args.output)

    print("\nDone.")


if __name__ == "__main__":
    main()
