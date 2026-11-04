# item_presets - edit item spawns in game, save layouts per map

Task: `qlsm-extra-0031`. Design agreed with the operator in chat on 2026-11-04.

## Goal

Admins change where items spawn on a map from inside the game (add, remove,
replace, move), save the result as a named preset for that map and switch
presets on and off, to test item balance. The vanilla map is never changed:
no preset active means the map's own layout.

## Decisions

| Topic | Decision |
|-------|----------|
| Editor | In game only, chat/console commands. A web editor is out of scope. |
| Preset content | A diff against the vanilla map: `removed` (map items) and `added` (our items). Untouched items keep every map key and timing. |
| Activation | `!preset load` makes a preset active and restarts warmup; it stays active on this map through restarts and reloads until `!preset off`. |
| Storage | Redis of the host (`self.db`): presets shared by every instance on the host, active preset per instance (port). |
| Access | Permission `qlx_itemEditPerm` (default 3); editing commands only in warmup. |
| Default | Off: `qlx_itemPresetsEnabled 0`. |

## Commands

| Command | Effect |
|---------|--------|
| `!item add <type>` | spawns an item where the admin stands |
| `!item remove` | removes the nearest item within `qlx_itemEditRadius` (default 64): a map item or one added before |
| `!item replace <type>` | the nearest item becomes another type at the same spot |
| `!item move` | first call picks the nearest item, second call moves it to the admin |
| `!item list` | the current edits (works during a match too) |
| `!preset save <name>` | saves the current edits as a preset of this map |
| `!preset load <name>` | makes it active, `map_restart`, applied on `new_game` |
| `!preset off` | no active preset, `map_restart`, vanilla layout |
| `!preset list` / `!preset delete <name>` | presets of this map |

`<type>`: short names from `skills/ql-items/SKILL.md` (`rl lg rg pg sg gl mg cg
ng pl hmg bfg gh`, `ra ya ga shard`, `mh 5hp 25hp 50hp`, `quad bs haste invis
regen`) or any item classname the engine knows (`minqlx.items()`), for example
`ammo_rockets`.

The current edits are a draft in memory: they survive a restart, not a map
change. On a map load the draft becomes the active preset of that map (or empty).

## Engine facts the design rests on

Checked in `_build/minqlxtended-fork` (branch `demo-match-capture`) and on
germany `qlds@27960` on 2026-11-04.

- `spawn_item(id, x, y, z)` calls `LaunchItem` and clears `think`: the item is
  a launched one (`python_embed.c` `PyMinqlxtended_SpawnItem`); `match_restore`
  notes it does not behave like a map item. Not used.
- `spawn_entity(classname, keys)` spawns "as if it had been in the map's entity
  text": items go through `G_SpawnItem`, appear two frames later, keys such as
  `wait` and `spawnflags` apply. Returns the `Entity` or `None`. Present in the
  `.so` on germany. Used for every added item.
- `remove_entity(id)` frees a map item. Hiding via fields is not reliable: a
  hidden powerup comes back visible on its first respawn (`gungame.py`).
- A restart respawns the map items a couple of frames after `new_game`
  (`qlsm-extra-0027` journal), so the preset is applied on the next frame and
  again 0.5 s later. Applying is idempotent: removed items are matched by
  classname within 8 units of the stored origin; added items are tracked by
  entity number and respawned only when their entity is gone.
- `Entity` exposes `s.origin`, `wait`, `spawnflags`; moving a map item copies
  its non-zero `wait` and `spawnflags` into the added entry.
- `Player.position` is a property (`Vector3`) in minqlxtended, a method in
  minqlx; both are handled. Items are spawned at the player's origin and drop
  to the floor in `G_SpawnItem`'s finish step (to verify live).

## Data

```json
{"map": "bloodrun", "name": "ra-swap",
 "removed": [{"cn": "item_health_mega", "o": [-120, 640, 32]}],
 "added":   [{"cn": "item_armor_body", "o": [300, 112, 56], "k": {"wait": 30}}]}
```

Redis keys:

- `minqlx:item_presets:<map>` - hash, preset name -> JSON above.
- `minqlx:item_presets:active:<net_port>` - JSON `{"map": ..., "name": ...}`.

Redis is read and written in worker threads (`@minqlx.thread`); results come
back to the game thread through `minqlx.next_frame`. Redis down: in-game edits
still work, save/load/list answer with an error.

## Edits on the draft

- Map item removed: append `{cn, o}` to `removed`, `remove_entity` now.
- Added item removed: drop its `added` entry, `remove_entity` now.
- Replace: remove as above, then add the new type at the old item's origin.
- Move: remove as above, add the same classname (and copied keys) at the admin.
  Moving an added item rewrites its entry, so no remove/add chains pile up.

## Errors

Every refused command answers the admin in one short line: disabled, no
permission (minqlx itself), not in warmup, unknown type (with the list), no item
within the radius, engine refused the spawn, Redis error, no such preset.
Unloading the plugin leaves its items in place; the next restart without an
active preset returns the vanilla map.

## Tests

`tests/test_item_presets.py` with the shared stub (`tests/_minqlx_stub.py`):
type parsing, nearest-item search, removed matching with tolerance, draft edits
(add, remove map/added, replace, move map/added), idempotent apply, refusals,
save/load/delete JSON through a fake Redis. Only this file and
`tests/test_descriptions.py` are run.

## Live check (germany `sD test server`, 91.99.3.72:27960)

On a map: remove MH, add RA, replace YA with RA, move RL; `save`, `off` gives
vanilla, `load` brings the edits back, a restart keeps them. Measured live: the
added item lies on the floor and respawns after pickup (time noted).

## Out of scope

Web editor; overlay and ql-stats-hub awareness of the edits (they still read the
BSP); custom respawn time per item; voting for a preset; moving presets between
hosts.
