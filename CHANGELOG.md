# Changelog

## v0.4 — Performance rewrite
- Rewrote the entire tool on `maya.cmds`, removing the PyMEL dependency
  entirely. PyMEL's import cost was responsible for a 5–10 second tool load
  time; `maya.cmds` has effectively none.
- Bake loop now suspends viewport refresh (`cmds.refresh(suspend=True)`)
  for its duration instead of relying on isolate select alone, which was
  still redrawing every frame on heavy rigs.
- Batched `setKeyframe` calls: one call per object per frame covering all
  its target attributes, instead of one call per attribute.
- Attribute existence is now resolved once up front instead of being
  re-checked every frame inside the bake loop.

## v0.3 — Correct additive capture
- Root-caused why baked results were flat/zero: `bakeResults` with
  `destinationLayer` doesn't reliably subtract the base/underlying value
  when computing an additive delta on this Maya version. Replaced with a
  per-frame `setKeyframe` loop with the target layer explicitly set as the
  active/selected AnimLayer — matches manual keying behavior exactly.
- Root-caused why the recreated constraint appeared to do nothing:
  skip-axis detection was checking the constrained object's attribute
  connections directly, which breaks when Maya inserts a `pairBlend` node
  (happens automatically when constraining an attribute that already has
  keyframed animation). Fixed by checking the constraint's own output plug
  for any downstream connection instead.
- Root-caused a "No valid query flags were specified" error: `animLayer
  -q -affectedLayers` isn't a valid flag for checking whether an attribute
  already belongs to a layer; switched to querying the target layer's own
  attribute list instead.
- Fixed a MEL parser error ("Invalid object or value: 0") triggered by an
  explicit `-mo 0` flag on constraint recreation; removed the flag
  entirely (equivalent behavior, since `false` is the default).
- Added a confirm dialog when re-running Step 1 on attributes already
  present in the target AnimLayer, with options to keep the same layer,
  pick a different one, or create a new uniquely-named layer via a prompt
  dialog.

## v0.2 — Constraint round-trip workflow
- Reworked the tool into a two-step workflow (Prep, then Bake) after
  discovering that an attribute must be added to an AnimLayer *before* a
  constraint is attached for the additive delta to compute correctly.
- Added constraint capture/delete/recreate logic so an *already*
  constrained-and-posed control can be run through the tool without losing
  the tweak: captures target list, per-target weights, offsets, and
  skipped axes, deletes the constraint, adds the attribute to the layer,
  then recreates the constraint identically.
- Fixed several PyMEL command-wrapper issues on Maya 2022 / Python 3.7
  (`getPanel`, `isolateSelect` flag names) by routing those specific calls
  through `mel.eval()` with hand-built MEL strings.

## v0.1 — Original MEL prototype
- Started as a MEL script: select objects, read highlighted Channel Box
  attributes via `channelBox -q -selectedMainAttributes`, isolate the
  viewport, and bake keys across the playback range using
  `setKeyframe -at`.
- Ported to Python/PyMEL and wrapped in a UI.
