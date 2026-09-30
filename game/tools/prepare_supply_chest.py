import bpy, json, math
from pathlib import Path
from mathutils import Vector, Quaternion

import argparse, sys
parser = argparse.ArgumentParser(description='Prepare the Phalanx supply chest in Blender')
parser.add_argument('input', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
source = args.input.resolve(strict=True)
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=False)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
obj = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
obj.name = 'HQ_SupplyChest'
obj.data.name = 'HQ_SupplyChest_Mesh'
original_faces = len(obj.data.polygons)
# Author dimensions in metres; origin stays at the centre of its ground footprint.
obj.dimensions = (0.9, 0.5, 0.55)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
modifier = obj.modifiers.new('Game silhouette reduction', 'DECIMATE')
modifier.ratio = 12000 / original_faces
modifier.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier=modifier.name)
for polygon in obj.data.polygons:
    polygon.use_smooth = True
obj.data.materials[0].name = 'HQ_Chest_WoodBronze'
for im in bpy.data.images:
    if im.source != 'FILE': continue
    im.scale(1024, 1024)
    # Pack the edited pixels into the native source, independent of Downloads.
    im.pack()
obj['source'] = 'Tripo H2.5; af81f1ef-a882-498c-be67-374fa72319d7; 2026-09-29'
obj['usage'] = 'Free-plan non-commercial prototype asset. Verify rights before release.'
obj['dimensions_metres'] = 'width 0.90, depth 0.50, height 0.55'
obj['source_triangle_count'] = original_faces
obj['game_triangle_count'] = len(obj.data.polygons)
bpy.ops.export_scene.gltf(filepath=str(out/'supply_chest.glb'), export_format='GLB', use_selection=True, export_apply=True, export_image_format='AUTO')

# A labelled preview rig is stored in Blender, but excluded from the game export.
rig = bpy.data.collections.new('Preview rig (not exported)')
bpy.context.scene.collection.children.link(rig)
def rig_object(name, data):
    o = bpy.data.objects.new(name, data)
    rig.objects.link(o)
    return o
camera = rig_object('Preview Camera', bpy.data.cameras.new('Preview Camera'))
camera.location = (1.5,-3.4,1.5)
aim = Vector((0,0,0.27))
camera.rotation_euler = (aim-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.type='ORTHO'
camera.data.ortho_scale=1.32
bpy.context.scene.camera=camera
for name, location, energy, size, color in [
    ('Warm key',(-2,-3,4),230,3,(1.0,0.86,0.68)),
    ('Soft fill',(3,-1,2),100,3,(0.7,0.8,1.0)),
    ('Rim',(0,3,3),180,2,(1.0,0.85,0.65))]:
    light = rig_object(name,bpy.data.lights.new(name,'AREA'))
    light.location=location
    light.rotation_euler=(aim-light.location).to_track_quat('-Z','Y').to_euler()
    light.data.energy=energy
    light.data.shape='DISK'
    light.data.size=size
    light.data.color=color
scene=bpy.context.scene
scene.world=bpy.data.worlds.new('Preview ambient')
scene.world.use_nodes=True
scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(0.12,0.14,0.17,1)
scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=0.3
scene.render.engine='CYCLES'
scene.cycles.samples=24
scene.cycles.use_denoising=True
scene.render.resolution_x=1024
scene.render.resolution_y=768
scene.render.resolution_percentage=100
scene.render.film_transparent=True
scene.render.image_settings.file_format='PNG'
scene.view_settings.view_transform='AgX'
scene.unit_settings.system='METRIC'
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':
            area.spaces.active.shading.type='MATERIAL'
            area.spaces.active.region_3d.view_distance=1.6
            area.spaces.active.region_3d.view_location=(0,0,0.275)
            area.spaces.active.region_3d.view_rotation=camera.rotation_euler.to_quaternion()
bpy.ops.wm.save_as_mainfile(filepath=str(out/'supply_chest.blend'))
report={'source_triangles':original_faces,'game_triangles':len(obj.data.polygons),'game_vertices':len(obj.data.vertices),'dimensions_metres':list(obj.dimensions),'textures':[{ 'name':im.name,'size':list(im.size)} for im in bpy.data.images if im.type=='IMAGE'],'glb_bytes':(out/'supply_chest.glb').stat().st_size}
(out/'asset_stats.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('CHEST_PREPARED',json.dumps(report))
scene.render.filepath=str(out/'supply_chest_preview.png')
bpy.ops.render.render(write_still=True)
