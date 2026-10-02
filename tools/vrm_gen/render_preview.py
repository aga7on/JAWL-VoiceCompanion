"""Render a preview of the generated character (front + 3/4 + face closeup).

Loads Jawlie.vrm's source .blend state by re-running the generator is heavy;
instead this script imports the VRM via the addon and renders turntable PNGs.
Used by the vision feedback loop.
"""
import sys
from pathlib import Path

import bpy
import addon_utils

VRM = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else r"G:\AI\JAWL-VoiceCompanion\runtime\vrm-models\Jawlie.vrm"
OUT_DIR = Path(r"G:\AI\JAWL-VoiceCompanion\runtime\browser-evidence")

bpy.ops.wm.read_factory_settings(use_empty=False)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()

# enable AFTER factory reset (read_factory_settings unloads addons)
for mod in addon_utils.modules():
    if "VRM" in mod.__name__:
        try:
            addon_utils.enable(mod.__name__, default_set=True, persistent=False)
        except Exception as exc:
            print("ENABLE_FAIL", exc)

bpy.ops.import_scene.vrm(filepath=VRM)

# studio light
world = bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.08, 0.10, 1)
key = bpy.data.objects.new("Key", bpy.data.lights.new("Key", "SUN"))
key.data.energy = 2.2
key.location = (3, -3, 5)
key.rotation_euler = (0.9, 0.3, 0.2)
bpy.context.collection.objects.link(key)
fill = bpy.data.objects.new("Fill", bpy.data.lights.new("Fill", "AREA"))
fill.data.energy = 200
fill.location = (-3, -2, 2)
bpy.context.collection.objects.link(fill)

# camera framing the full body
cam_data = bpy.data.cameras.new("Cam")
cam = bpy.data.objects.new("Cam", cam_data)
bpy.context.collection.objects.link(cam)
bpy.context.scene.camera = cam
cam.location = (0, -2.6, 0.85)
cam.rotation_euler = (1.5708 / 2 * 1.05, 0, 0)

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 512
scene.render.resolution_y = 896
scene.render.film_transparent = False

def render(name):
    scene.render.filepath = str(OUT_DIR / name)
    bpy.ops.render.render(write_still=True)

# apply all armature rotations? the imported VRM should be in rest pose
render("vrm-gen-front.png")

# 3/4 view
cam.location = (1.6, -2.1, 0.9)
cam.rotation_euler = (1.62, 0, 0.65)
render("vrm-gen-threeq.png")

# face closeup
cam.location = (0, -0.85, 1.42)
cam.rotation_euler = (1.5708, 0, 0)
scene.render.resolution_x = 640
scene.render.resolution_y = 640
render("vrm-gen-face.png")

print("PREVIEW_OK")
