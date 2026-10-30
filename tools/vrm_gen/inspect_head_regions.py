"""Read-only UV/material localization on the editable candidate's face skin."""
from pathlib import Path
import json
import sys

import bpy


ROOT = Path(__file__).resolve().parents[2]
args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
candidate = args[0] if args else 'jawlie-hair-v7'
if candidate not in ('jawlie-hair-v7', 'jawlie-hair-v8'):
    raise ValueError('Select an explicitly supported editable candidate')
bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'runtime/character-reference' / (candidate + '.blend')))
face = bpy.data.objects['Face']
for material in face.data.materials:
    if 'Face_00_SKIN' not in material.name:
        continue
    images = [(node.name, node.image) for node in material.node_tree.nodes
              if node.type == 'TEX_IMAGE' and node.image is not None]
    print('SKIN_IMAGE_NODES', [(name, image.name) for name, image in images])
    image = next((image for name, image in images if 'BaseColorTexture' in name), None)
    if image is None:
        raise RuntimeError('Expected source skin atlas is unavailable')
    width, height = image.size
    pixels = image.pixels[:]
    uv = face.data.uv_layers.active.data
    samples = []
    for polygon in face.data.polygons:
        if face.data.materials[polygon.material_index] != material:
            continue
        co = sum((face.data.vertices[i].co for i in polygon.vertices), start=face.data.vertices[0].co * 0) / len(polygon.vertices)
        if abs(co.x) < .062 or not 1.37 < co.z < 1.52:
            continue
        u = sum(uv[i].uv.x for i in polygon.loop_indices) / len(polygon.loop_indices)
        v = sum(uv[i].uv.y for i in polygon.loop_indices) / len(polygon.loop_indices)
        x, y = min(width - 1, max(0, int(u * width))), min(height - 1, max(0, int(v * height)))
        offset = (y * width + x) * 4
        samples.append({'polygon': polygon.index, 'xyz': [round(value, 5) for value in co],
                        'uv': [round(u, 5), round(v, 5)],
                        'rgb': [round(value, 4) for value in pixels[offset:offset + 3]]})
    dark = [s for s in samples if max(s['rgb']) < .5]
    print('HEAD_SKIN_LOCALIZATION', json.dumps({'image': image.name, 'size': list(image.size),
          'material': material.name, 'sampled_polygons': len(samples), 'dark_polygons': dark,
          'skin_examples': [s for s in samples if min(s['rgb']) > .6][:8]}))
    destination = ROOT / 'runtime/character-reference' / (candidate + '-face-skin-atlas.png')
    image.save_render(str(destination))
    print('ATLAS_COPY', destination)
