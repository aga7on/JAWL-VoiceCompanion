"""Minimal VRM export smoke: one bone chain + cube -> .vrm through the addon.

Validates the pipeline (addon API names, export operator) before building
the full character.
"""
import bpy
import addon_utils

# ensure the VRM addon is active in this session and list its export ops
for mod in addon_utils.modules():
    if 'VRM' in mod.__name__:
        try:
            addon_utils.enable(mod.__name__, default_set=True, persistent=True)
            print("ENABLED", mod.__name__)
        except Exception as exc:
            print("ENABLE_FAIL", mod.__name__, exc)

# clean the scene WITHOUT read_factory_settings (that would drop the addon)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
print("OPS:", [o for o in dir(bpy.ops.export_scene) if 'vrm' in o.lower()])

# armature with VRM humanoid bone names (VRM 1.0 / three-vrm convention)
arm_data = bpy.data.armatures.new("Armature")
arm = bpy.data.objects.new("Armature", arm_data)
bpy.context.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode='EDIT')
eb = arm_data.edit_bones

def bone(name, head, tail, parent=None):
    b = eb.new(name)
    b.head = head
    b.tail = tail
    if parent:
        b.parent = parent
    return b

hips = bone("Hips", (0, 0, 0.9), (0, 0, 1.0))
spine = bone("Spine", (0, 0, 1.0), (0, 0, 1.2), hips)
chest = bone("Chest", (0, 0, 1.2), (0, 0, 1.4), spine)
neck = bone("Neck", (0, 0, 1.4), (0, 0, 1.5), chest)
head = bone("Head", (0, 0, 1.5), (0, 0, 1.7), neck)
# arms
lsh = bone("LeftShoulder", (0, 0, 1.38), (0.08, 0, 1.38), chest)
lup = bone("LeftUpperArm", (0.08, 0, 1.38), (0.28, 0, 1.38), lsh)
llo = bone("LeftLowerArm", (0.28, 0, 1.38), (0.48, 0, 1.38), lup)
lha = bone("LeftHand", (0.48, 0, 1.38), (0.56, 0, 1.38), llo)
rsh = bone("RightShoulder", (0, 0, 1.38), (-0.08, 0, 1.38), chest)
rup = bone("RightUpperArm", (-0.08, 0, 1.38), (-0.28, 0, 1.38), rsh)
rlo = bone("RightLowerArm", (-0.28, 0, 1.38), (-0.48, 0, 1.38), rup)
rha = bone("RightHand", (-0.48, 0, 1.38), (-0.56, 0, 1.38), rlo)
# legs
lul = bone("LeftUpperLeg", (0.09, 0, 0.9), (0.09, 0, 0.5), hips)
lll = bone("LeftLowerLeg", (0.09, 0, 0.5), (0.09, 0, 0.08), lul)
lfo = bone("LeftFoot", (0.09, 0, 0.08), (0.09, -0.1, 0.02), lll)
rul = bone("RightUpperLeg", (-0.09, 0, 0.9), (-0.09, 0, 0.5), hips)
rll = bone("RightLowerLeg", (-0.09, 0, 0.5), (-0.09, 0, 0.08), rul)
rfo = bone("RightFoot", (-0.09, 0, 0.08), (-0.09, -0.1, 0.02), rll)
bpy.ops.object.mode_set(mode='OBJECT')

# body cube parented with automatic weights
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 1.0))
cube = bpy.context.active_object
cube.scale = (0.25, 0.18, 0.7)
bpy.ops.object.transform_apply(scale=True)
bpy.context.view_layer.objects.active = arm
arm.select_set(True)
cube.select_set(True)
bpy.ops.object.parent_set(type='ARMATURE_AUTO')

# select all for export
for obj in bpy.data.objects:
    obj.select_set(True)

# VRM export via the addon (VRM 1.0)
out = r"G:\AI\JAWL-VoiceCompanion\runtime\vrm-models\_smoke_minimal.vrm"
props = bpy.ops.export_scene.vrm.get_rna_type().properties.keys()
print("EXPORT_PROPS:", sorted(p for p in props if 'vrm' in p.lower() or 'export' in p.lower())[:30])
bpy.ops.export_scene.vrm(filepath=out)
print("EXPORT_OK", out)
