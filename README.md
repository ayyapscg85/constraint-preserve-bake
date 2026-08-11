# ConstraintPreserveBake

A `maya.cmds` tool for Autodesk Maya that captures constraint-driven "secondary"
motion (e.g. tweaking a control by constraining it to a locator) into an
**additive AnimLayer**, without disturbing the original animation underneath.

![Maya](https://img.shields.io/badge/Maya-2022%2B-0696D7)
![Python](https://img.shields.io/badge/Python-2.7%2F3.7-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## The problem

A common rigging/animation technique: constrain a control to a locator to
nudge part of its motion, then bake that offset into an additive AnimLayer
so the original animation curve stays intact underneath. In practice this
runs into a real Maya limitation — a constraint has to be attached to an
attribute **before** that attribute is added to a layer for the additive
delta to compute correctly, but you often only decide you want the offset
*after* you've already constrained and posed the object.

This tool automates the round-trip:

1. Captures the existing constraint(s) on the selected control(s) — targets,
   per-target weights, offsets, and which axes are skipped.
2. Deletes the constraint(s).
3. Adds the freed attributes to a new or existing **additive** AnimLayer
   (highlighted Channel Box attributes if any are selected, otherwise a
   translate/rotate fallback that only includes channels that actually
   exist, are keyable, and aren't locked — handles rigs where a control
   doesn't expose all six channels).
4. Recreates the constraint(s) with identical settings, now routed through
   the layer.
5. Bakes the resulting motion into the layer as a true additive delta.

The pose never changes — the tool just relocates *how* it's being driven.

## Usage

1. Run the script to open the tool window.
2. Select your constrained control(s) (or select first, then constrain — both work).
3. **Step 1 — Prep For Additive Layer**: removes existing constraints, adds
   the object to the target AnimLayer, restores the constraints.
   - If the selection is already partly in the target layer, a confirm
     dialog offers to keep it there, target a different layer, or create a
     new uniquely-named layer via a prompt dialog.
4. Adjust your locator/offset as needed.
5. **Step 2 — Bake Into AnimLayer**: bakes the live constrained motion into
   the layer as an additive delta.

## Performance

Built on `maya.cmds` rather than PyMEL, specifically for two reasons:

- **Load time.** PyMEL's first import in a Maya session is commonly several
  seconds due to the introspected API wrapper it builds. `maya.cmds` has
  effectively zero import cost.
- **Bake speed on heavy rigs.** The bake loop suspends viewport refresh for
  its duration (`cmds.refresh(suspend=True)`) rather than relying on
  isolate select alone — isolate select only reduces what gets *drawn*, the
  viewport still redraws every frame unless refresh itself is suspended,
  which is usually the dominant cost on a heavily rigged character. It also
  keys all of an object's target attributes in a single `setKeyframe` call
  per frame instead of one call per attribute, and pre-resolves which
  attributes exist once up front rather than re-checking every frame.

## Technical notes

A few non-obvious issues came up during development, documented here for
anyone extending this (see [CHANGELOG.md](CHANGELOG.md) for the full history):

- **`pairBlend` nodes break naive skip-axis detection.** When you constrain
  an attribute that already has keyframed animation, Maya inserts a
  `pairBlend` node to blend the animCurve and the constraint output — the
  object's attribute connects to the `pairBlend`, not directly to the
  constraint. Skip-axis detection has to check the *constraint's own output
  plug* for any downstream connection (direct or via `pairBlend`), not the
  object's input side, or every axis looks incorrectly "skipped."

- **`bakeResults(destinationLayer=...)` does not reliably compute the
  additive delta** on this Maya version — it was found to write the base
  layer's values into the additive layer instead of the offset. A plain
  per-frame `setKeyframe` loop, with the target layer explicitly set as the
  selected/active AnimLayer, matches manual keying behavior and produces
  the correct delta.

- **Constraint recreation goes through hand-built MEL strings via
  `mel.eval()`**, not native `cmds.parentConstraint(...)` calls — an
  explicit `-mo 0` (maintainOffset false) flag was found to trip Maya's MEL
  parser on this version with an "Invalid object or value" error; omitting
  the flag entirely (equivalent, since `false` is the default) resolved it.

## Requirements

- Autodesk Maya 2022+ (`maya.cmds`, no PyMEL dependency)
- Tested on Python 3.7 (Maya 2022's embedded interpreter)

## License

MIT — see [LICENSE](LICENSE).
