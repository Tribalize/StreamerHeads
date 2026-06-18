# StreamerHeads

StreamerHeads is a Minecraft Bedrock add-on generator for custom player-head items and placeable head blocks. It downloads Java player skins, builds the behavior and resource packs, adds wandering trader trades, writes Vibrant Visuals texture-set metadata, and packages everything as a `.mcaddon`.

## Current Target

- Minecraft Bedrock stable target: `1.26.30`
- Script API dependency: `@minecraft/server` `2.8.0`
- Resource pack folder/name: `StreamerheadsResources`
- Resource pack capability: `pbr` for Vibrant Visuals
- Behavior and resource packs depend on each other so they install together when added to a world.

## Build With GitHub Actions

1. Open the repository on GitHub.
2. Go to **Actions**.
3. Select **Build StreamerHeads Add-on**.
4. Click **Run workflow**.
5. Choose one of these inputs:
   - `player_names`: comma-separated names such as `Grian,MumboJumbo,GeminiTay`.
   - Leave `player_names` empty to use `heads.json`.
   - `version`: the version to stamp into the manifests and artifact name.
6. Download the uploaded `.mcaddon` artifact from the workflow run.

GitHub Actions does not provide a dynamic checkbox list from repo data, so the workflow uses a text field for custom player selection and `heads.json` for saved presets.

## Build Locally

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Build from `heads.json`:

```powershell
python buildheads.py --heads-file heads.json --version 2.1.3 --no-version-bump --output dist/StreamerHeads-v2.1.3.mcaddon
```

Build with a one-off list:

```powershell
python buildheads.py --heads "Grian,MumboJumbo,GeminiTay" --version 2.1.3 --no-version-bump --output dist/StreamerHeads-custom.mcaddon
```

## Configure Heads

Edit `heads.json` to change the default list:

```json
{
  "heads": [
    "Grian",
    "MumboJumbo",
    {
      "name": "GoodTimeWithScar",
      "model": "head"
    }
  ]
}
```

Each entry can be either a string player name or an object with:

- `name`: exact Java Edition player name.
- `model`: optional model name. Use `null` or omit it for the default `head` model.

## Output

The generated `.mcaddon` contains:

- `StreamerHeads_BP/`
- `StreamerheadsResources/`

Double-click the `.mcaddon` or import it into Minecraft Bedrock. The behavior and resource packs are linked in both manifests so they are added to the world together.

## Tests

```powershell
python -m unittest discover -s tests
```
