import maya.cmds as cmds
import maya.mel as mel

CONSTRAINT_TYPES = ["parentConstraint", "pointConstraint", "orientConstraint"]


class ConstraintPreserveBake(object):
    WINDOW_NAME = "constraintPreserveBakeWin"

    def __init__(self):
        self.win = None
        self.new_layer_name_field = None
        self.existing_layer_menu = None
        self.use_existing_cb = None
        self.override_cb = None
        self.range_mode_radio = None
        self.start_field = None
        self.end_field = None
        self.step_field = None
        self.isolate_cb = None
        self.clear_range_cb = None
        self.active_layer_text = None

        self._active_layer = None

    # ------------------------------------------------------------------
    # Channel Box / attribute helpers
    # ------------------------------------------------------------------
    def _get_channelbox_selected_attrs(self):
        cb_name = mel.eval("global string $gChannelBoxName; $temp = $gChannelBoxName;")
        attrs = cmds.channelBox(cb_name, q=True, selectedMainAttributes=True)
        return attrs or []

    def _get_fallback_attrs(self, obj):
        candidates = ["translateX", "translateY", "translateZ",
                      "rotateX", "rotateY", "rotateZ"]
        result = []
        for a in candidates:
            if cmds.attributeQuery(a, node=obj, exists=True):
                full = "{0}.{1}".format(obj, a)
                if cmds.getAttr(full, keyable=True) and not cmds.getAttr(full, lock=True):
                    result.append(a)
        return result

    def _get_target_attrs_per_object(self, objs, cb_attrs):
        mapping = {}
        for obj in objs:
            if cb_attrs:
                mapping[obj] = [a for a in cb_attrs
                                if cmds.attributeQuery(a, node=obj, exists=True)]
            else:
                mapping[obj] = self._get_fallback_attrs(obj)
        return mapping

    # ------------------------------------------------------------------
    # Constraint capture / delete / recreate
    # ------------------------------------------------------------------
    def _get_constraints(self, obj):
        children = cmds.listRelatives(obj, children=True, type="constraint", fullPath=True) or []
        return [c for c in children if cmds.nodeType(c) in CONSTRAINT_TYPES]

    def _skip_axes(self, obj, constraint, base_attr, axes="XYZ"):
        """Return list of lowercase axis letters NOT driven by this constraint.

        Checks the constraint's own output plug for ANY downstream connection
        (direct to obj, or indirect via a pairBlend node inserted by Maya when
        the attribute already had keyframed animation).
        """
        skipped = []
        prefix = "constraint" + base_attr.capitalize()
        for axis in axes:
            out_attr = prefix + axis
            if not cmds.attributeQuery(out_attr, node=constraint, exists=True):
                skipped.append(axis.lower())
                continue
            full_out = "{0}.{1}".format(constraint, out_attr)
            outs = cmds.listConnections(full_out, source=False, destination=True, plugs=True) or []
            if not outs:
                skipped.append(axis.lower())
        return skipped

    def _capture_constraint(self, obj, constraint):
        ctype = cmds.nodeType(constraint)
        info = {"type": ctype, "targets": [], "weights": [],
                "skip_t": [], "skip_r": [], "offset": None,
                "interp_type": None, "per_target_offset": []}

        if ctype == "parentConstraint":
            targets = cmds.parentConstraint(obj, q=True, targetList=True) or []
            info["targets"] = list(targets)
            for i in range(len(targets)):
                ot = cmds.getAttr("{0}.target[{1}].targetOffsetTranslate".format(constraint, i))[0]
                orot = cmds.getAttr("{0}.target[{1}].targetOffsetRotate".format(constraint, i))[0]
                info["per_target_offset"].append((ot, orot))
            info["skip_t"] = self._skip_axes(obj, constraint, "translate")
            info["skip_r"] = self._skip_axes(obj, constraint, "rotate")
            aliases = cmds.parentConstraint(constraint, q=True, weightAliasList=True) or []
            info["weights"] = [cmds.getAttr("{0}.{1}".format(constraint, a)) for a in aliases]

        elif ctype == "pointConstraint":
            targets = cmds.pointConstraint(obj, q=True, targetList=True) or []
            info["targets"] = list(targets)
            info["offset"] = cmds.getAttr(constraint + ".offset")[0]
            info["skip_t"] = self._skip_axes(obj, constraint, "translate")
            aliases = cmds.pointConstraint(constraint, q=True, weightAliasList=True) or []
            info["weights"] = [cmds.getAttr("{0}.{1}".format(constraint, a)) for a in aliases]

        elif ctype == "orientConstraint":
            targets = cmds.orientConstraint(obj, q=True, targetList=True) or []
            info["targets"] = list(targets)
            info["offset"] = cmds.getAttr(constraint + ".offset")[0]
            info["interp_type"] = cmds.getAttr(constraint + ".interpType")
            info["skip_r"] = self._skip_axes(obj, constraint, "rotate")
            aliases = cmds.orientConstraint(constraint, q=True, weightAliasList=True) or []
            info["weights"] = [cmds.getAttr("{0}.{1}".format(constraint, a)) for a in aliases]

        return info

    def _skip_flags(self, flag, axes):
        """Build repeated -flag "axis" tokens. Empty string if nothing to skip
        (omitting the flag entirely means no axes are skipped)."""
        if not axes:
            return ""
        return " ".join('-{0} "{1}"'.format(flag, a) for a in axes)

    def _recreate_constraint(self, obj, info):
        """Recreated via mel.eval with hand-built strings (not native
        cmds.parentConstraint/etc create calls) — this exact approach was
        needed to work around a MEL flag-parsing quirk on -mo in this Maya
        version. Left unchanged from the working, tested version."""
        ctype = info["type"]
        targets = info["targets"]
        if not targets:
            cmds.warning("No targets captured for a {0} on {1}; skipping restore.".format(ctype, obj))
            return None

        target_names = " ".join('"{0}"'.format(t) for t in targets)
        obj_name = obj

        try:
            if ctype == "parentConstraint":
                skip_t_flags = self._skip_flags("skipTranslate", info["skip_t"])
                skip_r_flags = self._skip_flags("skipRotate", info["skip_r"])
                cmd = 'parentConstraint {0} {1} {2} "{3}"'.format(
                    skip_t_flags, skip_r_flags, target_names, obj_name)
                result = mel.eval(cmd)
                new_c = result[0]
                for i, (ot, orot) in enumerate(info["per_target_offset"]):
                    cmds.setAttr("{0}.target[{1}].targetOffsetTranslate".format(new_c, i), *ot)
                    cmds.setAttr("{0}.target[{1}].targetOffsetRotate".format(new_c, i), *orot)
                aliases = mel.eval('parentConstraint -q -weightAliasList "{0}"'.format(new_c)) or []

            elif ctype == "pointConstraint":
                skip_t_flags = self._skip_flags("skip", info["skip_t"])
                cmd = 'pointConstraint {0} {1} "{2}"'.format(skip_t_flags, target_names, obj_name)
                result = mel.eval(cmd)
                new_c = result[0]
                cmds.setAttr(new_c + ".offset", *info["offset"])
                aliases = mel.eval('pointConstraint -q -weightAliasList "{0}"'.format(new_c)) or []

            elif ctype == "orientConstraint":
                skip_r_flags = self._skip_flags("skip", info["skip_r"])
                cmd = 'orientConstraint {0} {1} "{2}"'.format(skip_r_flags, target_names, obj_name)
                result = mel.eval(cmd)
                new_c = result[0]
                cmds.setAttr(new_c + ".offset", *info["offset"])
                cmds.setAttr(new_c + ".interpType", info["interp_type"])
                aliases = mel.eval('orientConstraint -q -weightAliasList "{0}"'.format(new_c)) or []

            else:
                return None

        except Exception as e:
            cmds.warning("Failed to recreate {0} on {1}: {2}".format(ctype, obj, e))
            return None

        try:
            for alias, weight in zip(aliases, info["weights"]):
                cmds.setAttr("{0}.{1}".format(new_c, alias), weight)
        except Exception as e:
            cmds.warning("{0} recreated on {1} but weight restore failed: {2}".format(
                ctype, obj, e))

        return new_c

    # ------------------------------------------------------------------
    # AnimLayer helpers
    # ------------------------------------------------------------------
    def _get_existing_anim_layers(self):
        layers = cmds.ls(type="animLayer") or []
        return [l for l in layers if l != "BaseAnimation"]

    def _set_only_layer_selected(self, target_layer):
        """Make target_layer the sole selected/active AnimLayer for keying.

        Covers EVERY layer including BaseAnimation. Leaving BaseAnimation
        selected=True alongside our target was causing Maya to resolve the
        ambiguous "which layer is active" state onto Base instead of the
        intended layer during Step 2 — this is the fix for that.
        """
        all_layers = cmds.ls(type="animLayer") or []
        for l in all_layers:
            if l != target_layer:
                try:
                    cmds.animLayer(l, edit=True, selected=False)
                except Exception:
                    pass
        cmds.animLayer(target_layer, edit=True, selected=True)

    def _create_or_get_layer(self, name, use_existing, override=False):
        if use_existing:
            if not cmds.animLayer(name, q=True, exists=True):
                cmds.warning("Selected existing AnimLayer '{0}' not found.".format(name))
                return None
            return name

        if not name:
            name = "constraintBake_AnimLayer"
        unique_name = name
        index = 1
        while cmds.animLayer(unique_name, q=True, exists=True):
            unique_name = "{0}_{1}".format(name, index)
            index += 1
        layer = cmds.animLayer(unique_name, addSelectedObjects=False)
        cmds.animLayer(layer, edit=True, override=override)
        return layer

    def _add_attrs_to_layer(self, layer, attrs_per_obj):
        added = 0
        for obj, attrs in attrs_per_obj.items():
            for attr in attrs:
                full_attr = "{0}.{1}".format(obj, attr)
                if cmds.objExists(full_attr):
                    cmds.animLayer(layer, edit=True, attribute=full_attr)
                    added += 1
        self._set_only_layer_selected(layer)
        return added

    # ------------------------------------------------------------------
    # STEP 1: Prep — pull constraint out, attach layer, put constraint back
    # ------------------------------------------------------------------
    def _resolve_target_layer(self, objs):
        cb_attrs = self._get_channelbox_selected_attrs()
        attrs_per_obj = self._get_target_attrs_per_object(objs, cb_attrs)
        attrs_per_obj = {o: a for o, a in attrs_per_obj.items() if a}

        use_existing = cmds.checkBox(self.use_existing_cb, q=True, value=True)
        if use_existing:
            layer_name = cmds.optionMenu(self.existing_layer_menu, q=True, value=True)
        else:
            layer_name = cmds.textField(self.new_layer_name_field, q=True, text=True) or \
                "constraintBake_AnimLayer"

        already_in_target = []
        if cmds.animLayer(layer_name, q=True, exists=True):
            layer_attrs = cmds.animLayer(layer_name, q=True, attribute=True) or []
            for obj, attrs in attrs_per_obj.items():
                for attr in attrs:
                    full_attr = "{0}.{1}".format(obj, attr)
                    if full_attr in layer_attrs:
                        already_in_target.append(full_attr)

        if not already_in_target:
            return layer_name, use_existing

        choice = cmds.confirmDialog(
            title="Already In AnimLayer",
            message="{0} attribute(s) on the selection are already in AnimLayer "
                    "'{1}'.\n\nWhat would you like to do?".format(
                        len(already_in_target), layer_name),
            button=["Keep In Same Layer", "Choose Different Layer",
                    "New Layer (Alt Name)", "Cancel"],
            defaultButton="Keep In Same Layer",
            cancelButton="Cancel",
            dismissString="Cancel")

        if choice == "Cancel":
            print("Step 1 cancelled by user.")
            return None, None

        if choice == "Keep In Same Layer":
            return layer_name, True

        if choice == "Choose Different Layer":
            cmds.warning("Pick a different layer from the 'Use Existing Layer' dropdown "
                        "(or type a new name in the layer name field), then run Step 1 again.")
            return None, None

        if choice == "New Layer (Alt Name)":
            suggested_name = layer_name
            idx = 1
            while cmds.animLayer(suggested_name, q=True, exists=True):
                suggested_name = "{0}_alt{1}".format(layer_name, idx)
                idx += 1

            result = cmds.promptDialog(
                title="New AnimLayer Name",
                message="Enter a name for the new AnimLayer:",
                text=suggested_name,
                button=["OK", "Cancel"],
                defaultButton="OK",
                cancelButton="Cancel",
                dismissString="Cancel")

            if result != "OK":
                print("Step 1 cancelled by user.")
                return None, None

            new_name = cmds.promptDialog(q=True, text=True).strip()
            if not new_name:
                new_name = suggested_name

            final_name = new_name
            idx = 1
            while cmds.animLayer(final_name, q=True, exists=True):
                final_name = "{0}_{1}".format(new_name, idx)
                idx += 1

            cmds.textField(self.new_layer_name_field, e=True, text=final_name)
            cmds.checkBox(self.use_existing_cb, e=True, value=False)
            self._toggle_layer_mode()
            return final_name, False

        return None, None

    def add_to_layer(self, *args):
        objs = cmds.ls(selection=True, long=True) or []
        if not objs:
            cmds.warning("Select at least one control before running Step 1.")
            return

        layer_name, use_existing = self._resolve_target_layer(objs)
        if layer_name is None:
            return

        # 1. Capture and delete existing constraints (if any) per object
        captured_per_obj = {}
        for obj in objs:
            constraints = self._get_constraints(obj)
            captured = [self._capture_constraint(obj, c) for c in constraints]
            if constraints:
                for info in captured:
                    print("Captured {0} on {1}: targets={2} skip_t={3} skip_r={4}".format(
                        info["type"], obj, info["targets"], info["skip_t"], info["skip_r"]))
                cmds.delete(constraints)
            captured_per_obj[obj] = captured

        # 2. Determine attrs now that the object is free of constraints
        cb_attrs = self._get_channelbox_selected_attrs()
        attrs_per_obj = self._get_target_attrs_per_object(objs, cb_attrs)
        attrs_per_obj = {o: a for o, a in attrs_per_obj.items() if a}

        if not attrs_per_obj:
            cmds.warning("No valid attributes found (highlighted or T/R fallback). "
                        "Restoring original constraints and aborting.")
            for obj, captured in captured_per_obj.items():
                for info in captured:
                    self._recreate_constraint(obj, info)
            return

        # Show exactly which attributes were picked up per object, so it's
        # easy to verify a control with only some channels (e.g. a shoulder
        # with only translateX/Z + rotateY) was segregated correctly.
        for obj, attrs in attrs_per_obj.items():
            print("Attrs for {0}: {1}".format(obj, attrs))

        # 3. Add to target additive/override layer
        override = cmds.checkBox(self.override_cb, q=True, value=True)
        layer = self._create_or_get_layer(layer_name, use_existing, override)
        if not layer:
            for obj, captured in captured_per_obj.items():
                for info in captured:
                    self._recreate_constraint(obj, info)
            return

        added = self._add_attrs_to_layer(layer, attrs_per_obj)
        self._active_layer = layer

        # 4. Recreate constraints so the object is live again, now through the layer
        restored = 0
        for obj, captured in captured_per_obj.items():
            for info in captured:
                if self._recreate_constraint(obj, info):
                    restored += 1

        cmds.text(self.active_layer_text, e=True,
                  label="Active layer: {0}  (Additive)".format(layer))
        self._refresh_existing_layers()
        cmds.optionMenu(self.existing_layer_menu, e=True, value=layer)

        print("Step 1 done: added {0} attribute(s) to AnimLayer '{1}', "
              "restored {2} constraint(s). Ready to bake.".format(added, layer, restored))

    # ------------------------------------------------------------------
    # STEP 2: Bake — optimized for speed on heavy rigs
    # ------------------------------------------------------------------
    def _clear_keys_in_range(self, obj, attrs, start, end):
        for attr in attrs:
            full_attr = "{0}.{1}".format(obj, attr)
            if cmds.objExists(full_attr) and (cmds.keyframe(full_attr, q=True, keyframeCount=True) or 0) > 0:
                cmds.cutKey(obj, attribute=attr, time=(start, end), clear=True)

    def bake_layer(self, *args):
        objs = cmds.ls(selection=True, long=True) or []
        if not objs:
            cmds.warning("Select at least one control before running Step 2.")
            return

        use_existing = cmds.checkBox(self.use_existing_cb, q=True, value=True)
        layer = cmds.optionMenu(self.existing_layer_menu, q=True, value=True) if use_existing else self._active_layer

        if not layer or not cmds.animLayer(layer, q=True, exists=True):
            cmds.warning("No valid target AnimLayer. Run Step 1 first (or pick an existing layer).")
            return

        cb_attrs = self._get_channelbox_selected_attrs()
        attrs_per_obj = self._get_target_attrs_per_object(objs, cb_attrs)
        attrs_per_obj = {o: a for o, a in attrs_per_obj.items() if a}
        if not attrs_per_obj:
            cmds.warning("No valid attributes found (highlighted or T/R fallback) on the selection.")
            return

        # Precompute which attrs actually exist ONCE, up front — avoids a
        # redundant objExists() check on every single frame in the loop below.
        valid_attrs_per_obj = {}
        for obj, attrs in attrs_per_obj.items():
            existing = [a for a in attrs if cmds.objExists("{0}.{1}".format(obj, a))]
            if existing:
                valid_attrs_per_obj[obj] = existing
        if not valid_attrs_per_obj:
            cmds.warning("None of the target attributes exist on the selection.")
            return

        use_custom_range = cmds.radioButtonGrp(self.range_mode_radio, q=True, select=True) == 2
        if use_custom_range:
            start = cmds.intField(self.start_field, q=True, value=True)
            end = cmds.intField(self.end_field, q=True, value=True)
        else:
            start = int(cmds.playbackOptions(q=True, minTime=True))
            end = int(cmds.playbackOptions(q=True, maxTime=True))
        step = max(1, cmds.intField(self.step_field, q=True, value=True))
        isolate = cmds.checkBox(self.isolate_cb, q=True, value=True)
        clear_range = cmds.checkBox(self.clear_range_cb, q=True, value=True)

        # Make sure the target layer is the ONLY selected/active AnimLayer —
        # this is what makes setKeyframe compute the additive delta and land
        # keys on the right layer, same as manually pressing S with just
        # that layer selected. BaseAnimation has to be explicitly deselected
        # too, or Maya can resolve the ambiguous "active layer" state onto
        # Base instead of the intended target.
        self._set_only_layer_selected(layer)
        cmds.text(self.active_layer_text, e=True,
                  label="Baking into: {0}".format(layer))
        print("Baking into AnimLayer: {0}".format(layer))

        panel = mel.eval("getPanel -withFocus")
        is_viewport = "modelPanel" in panel
        isolate_was_on = False

        if isolate and is_viewport:
            isolate_was_on = mel.eval('isolateSelect -q -state "{0}"'.format(panel))
            mel.eval('isolateSelect -state 1 "{0}"'.format(panel))
            mel.eval('isolateSelect -loadSelected "{0}"'.format(panel))
        elif isolate:
            cmds.warning("Active panel is not a viewport. Isolation skipped.")

        if clear_range:
            for obj, attrs in valid_attrs_per_obj.items():
                self._clear_keys_in_range(obj, attrs, start, end)

        original_time = cmds.currentTime(query=True)

        # Prime: explicitly move to the start frame and re-confirm the layer
        # selection, then set one key there BEFORE suspending refresh. This
        # was found to reliably lock in which layer the rest of the bake
        # lands on. The main loop below will key the start frame again as
        # its first iteration — harmless, same value.
        cmds.currentTime(start, edit=True)
        self._set_only_layer_selected(layer)
        for obj, attrs in valid_attrs_per_obj.items():
            cmds.setKeyframe(obj, attribute=attrs, breakdown=False,
                              preserveCurveShape=False, hierarchy="none",
                              controlPoints=False, shape=True)

        # Suspend viewport redraws for the whole bake — usually the single
        # biggest speed win on heavy rigs. Isolate select only reduces WHAT
        # would be drawn; it still redraws every frame unless refresh itself
        # is suspended. Wrapped in try/finally so a mid-bake error can't
        # leave the viewport permanently frozen.
        cmds.refresh(suspend=True)
        try:
            frame = start
            while frame <= end:
                cmds.currentTime(frame, edit=True)
                for obj, attrs in valid_attrs_per_obj.items():
                    # One setKeyframe call per object per frame, keying ALL
                    # its target attributes together, instead of one call
                    # per attribute — cuts command overhead a lot on rigs
                    # with many keyed channels.
                    cmds.setKeyframe(obj, attribute=attrs, breakdown=False,
                                      preserveCurveShape=False, hierarchy="none",
                                      controlPoints=False, shape=True)
                frame += step
        finally:
            cmds.refresh(suspend=False)
            cmds.currentTime(original_time, edit=True)
            cmds.refresh()

        if isolate and is_viewport:
            restore_state = 1 if isolate_was_on else 0
            mel.eval('isolateSelect -state {0} "{1}"'.format(restore_state, panel))

        keyed_count = sum(len(a) for a in valid_attrs_per_obj.values())
        print("Step 2 done: baked {0} attribute(s) into AnimLayer '{1}' "
              "across frames {2}-{3} (step {4}).".format(keyed_count, layer, start, end, step))

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _refresh_existing_layers(self, *args):
        for item in cmds.optionMenu(self.existing_layer_menu, q=True, itemListLong=True) or []:
            cmds.deleteUI(item)
        layers = self._get_existing_anim_layers()
        if not layers:
            cmds.menuItem(parent=self.existing_layer_menu, label="<no AnimLayers>")
        else:
            for l in layers:
                cmds.menuItem(parent=self.existing_layer_menu, label=l)

    def _toggle_layer_mode(self, *args):
        use_existing = cmds.checkBox(self.use_existing_cb, q=True, value=True)
        cmds.textField(self.new_layer_name_field, e=True, enable=not use_existing)
        cmds.optionMenu(self.existing_layer_menu, e=True, enable=use_existing)
        if use_existing:
            self._refresh_existing_layers()

    def _toggle_range_mode(self, *args):
        custom = cmds.radioButtonGrp(self.range_mode_radio, q=True, select=True) == 2
        cmds.intField(self.start_field, e=True, enable=custom)
        cmds.intField(self.end_field, e=True, enable=custom)

    def show(self):
        if cmds.window(self.WINDOW_NAME, exists=True):
            cmds.deleteUI(self.WINDOW_NAME)

        self.win = cmds.window(self.WINDOW_NAME, title="Constraint Preserve Bake",
                               widthHeight=(380, 640), sizeable=True)
        cmds.columnLayout(adjustableColumn=True, rowSpacing=6, columnAttach=("both", 10))

        cmds.text(label="Select constrained controls, run STEP 1.\n"
                        "This removes the constraint, adds the object to an\n"
                        "additive AnimLayer, then puts the same constraint back.\n"
                        "Then run STEP 2 to bake the extra motion into that layer.",
                 align="left", ww=True, height=64)

        cmds.separator(height=6, style="in")

        cmds.frameLayout(label="AnimLayer", collapsable=True, collapse=False,
                         marginWidth=6, marginHeight=6)
        cmds.columnLayout(adjustableColumn=True, rowSpacing=4)
        self.use_existing_cb = cmds.checkBox(label="Use Existing Layer", value=False,
                                             changeCommand=self._toggle_layer_mode)
        self.new_layer_name_field = cmds.textField(text="constraintBake_AnimLayer")
        self.existing_layer_menu = cmds.optionMenu(enable=False)
        self._refresh_existing_layers()
        self.override_cb = cmds.checkBox(
            label="Override Mode (unchecked = Additive, only applies to new layers)",
            value=False)
        self.active_layer_text = cmds.text(label="Active layer: <none yet>", align="left")
        cmds.setParent("..")
        cmds.setParent("..")

        cmds.separator(height=4, style="in")
        cmds.button(label="STEP 1:  Prep For Additive Layer", height=36,
                   backgroundColor=(0.45, 0.6, 0.45), command=self.add_to_layer)
        cmds.text(label="removes -> adds to layer -> restores constraint",
                 align="center", height=16)

        cmds.separator(height=10, style="in")

        cmds.frameLayout(label="Bake Options", collapsable=True, collapse=False,
                         marginWidth=6, marginHeight=6)
        cmds.columnLayout(adjustableColumn=True, rowSpacing=4)
        self.range_mode_radio = cmds.radioButtonGrp(
            labelArray2=["Playback Range", "Custom"], numberOfRadioButtons=2,
            select=1, changeCommand=self._toggle_range_mode)
        cmds.rowLayout(numberOfColumns=4, columnWidth4=(40, 80, 40, 80), adjustableColumn=4)
        cmds.text(label="Start")
        self.start_field = cmds.intField(value=1, enable=False)
        cmds.text(label="End")
        self.end_field = cmds.intField(value=48, enable=False)
        cmds.setParent("..")
        cmds.rowLayout(numberOfColumns=2, columnWidth2=(40, 80))
        cmds.text(label="Step")
        self.step_field = cmds.intField(value=1, minValue=1)
        cmds.setParent("..")
        self.isolate_cb = cmds.checkBox(label="Isolate Viewport During Bake", value=True)
        self.clear_range_cb = cmds.checkBox(
            label="Clear This Layer's Existing Keys In Range Before Baking", value=True)
        cmds.setParent("..")
        cmds.setParent("..")

        cmds.separator(height=4, style="in")
        cmds.button(label="STEP 2:  Bake Into AnimLayer", height=36,
                   backgroundColor=(0.55, 0.45, 0.45), command=self.bake_layer)

        cmds.showWindow(self.win)


def show_constraint_preserve_bake():
    tool = ConstraintPreserveBake()
    tool.show()


show_constraint_preserve_bake()
