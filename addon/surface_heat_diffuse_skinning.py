bl_info = {
    "name": "Surface Heat Diffuse Skinning",
    "author": "mesh online",
    "version": (3, 0),
    "blender": (2, 78, 0),
    "location": "View3D > Tools > Animation",
    "description": "Surface Heat Diffuse Skinning",
    "warning": "",
    "wiki_url": "http://www.mesh-online.net/vhd.html",
    "category": "Object"
}


import bpy
import sys
import os
import time
import platform
from subprocess import PIPE, Popen
from threading  import Thread
from bpy.props import *
from queue import Queue, Empty

class ModalTimerOperator(bpy.types.Operator):
    """Operator which runs its self from a timer"""
    bl_idname = "wm.surface_heat_diffuse"
    bl_label = "Surface Heat Diffuse Skinning"
    bl_options = {'REGISTER', 'UNDO'}
    
    _timer = None
    _pid = None
    _queue = None
    
    _objs = []
    _permulation = []
    _selected_indices = []
    _selected_group_index_weights = []
    
    _start_time = None

    def write_bone_data(self, obj, filepath):
        f = open(filepath, 'w', encoding='utf-8')
    
        f.write("# surface heat diffuse bone export.\n")

        amt = obj.data
        bpy.ops.object.mode_set(mode='EDIT')
        for bone in amt.edit_bones:
            if bone.use_deform:
                world_bone_head = obj.matrix_world * bone.head
                world_bone_tail = obj.matrix_world * bone.tail
                f.write("b,{},{:.6f},{:.6f},{:.6f},{:.6f},{:.6f},{:.6f}\n".format(
                bone.name, world_bone_head[0], world_bone_head[1], world_bone_head[2],
                world_bone_tail[0], world_bone_tail[1], world_bone_tail[2]))
        bpy.ops.object.mode_set(mode='OBJECT')

        f.close()

    def write_mesh_data(self, objs, filepath):
        f = open(filepath, 'w', encoding='utf-8')
    
        f.write("# surface heat diffuse mesh export.\n")
        
        vertex_offset = 0
        for obj in objs:
            for v in obj.data.vertices:
                world_v_co = obj.matrix_world * v.co
                f.write("v,{:.6f},{:.6f},{:.6f}\n".format(world_v_co[0], world_v_co[1], world_v_co[2]))
        
            for poly in obj.data.polygons:
                f.write("f");
                for loop_ind in poly.loop_indices:
                    vert_ind = obj.data.loops[loop_ind].vertex_index
                    f.write(",{}".format(vertex_offset + vert_ind))
                f.write("\n")
    
            vertex_offset += len(obj.data.vertices)

        f.close()

    def read_weight_data(self, objs, filepath):
        # make permulation for all vertices
        vertex_offset = 0;
        for obj in objs:
            for index in range(len(obj.data.vertices)):
                self._permulation.append((vertex_offset + index, index, obj))
            vertex_offset += len(obj.data.vertices)

        if bpy.context.scene.surface_protect:
            for index in range(len(objs)):
                obj = objs[index]
                # get selected vertex indices
                self._selected_indices.append([i.index for i in obj.data.vertices if i.select])
                self._selected_group_index_weights.append([])
        
                # push protected vertices weight
                for vert_ind in self._selected_indices[index]:
                    for g in obj.data.vertices[vert_ind].groups:
                        self._selected_group_index_weights[index].append((obj.vertex_groups[g.group].name, vert_ind, g.weight))

        f = open(filepath, 'r', encoding='utf-8')

        bones = []
        for line in f:
            if len(line) == 0:
                continue
            tokens = line.strip("\r\n").split(",")
            if tokens[0] == "b":
                group_name = tokens[1]
                bones.append(group_name)
                for obj in objs:
                    #check for existing group with the same name
                    if None != obj.vertex_groups.get(group_name):
                        group = obj.vertex_groups[group_name]
                        obj.vertex_groups.remove(group)
                    obj.vertex_groups.new(name = group_name)
            if tokens[0] == "w":
                group_name = bones[int(tokens[2])]
                index = int(tokens[1])
                vert_ind = self._permulation[index][1]
                weight = float(tokens[3])
                obj = self._permulation[index][2]
                # protect vertices weight
                if bpy.context.scene.surface_protect and vert_ind in self._selected_indices[objs.index(obj)]:
                    continue
                obj.vertex_groups[group_name].add([vert_ind], weight, 'REPLACE')

        f.close()
        
        if bpy.context.scene.surface_protect:
            for index in range(len(objs)):
                obj = objs[index]
                # pop protected vertices weight
                for (group_name, vert_ind, weight) in self._selected_group_index_weights[index]:
                    obj.vertex_groups[group_name].add([vert_ind], weight, 'REPLACE')

    def modal(self, context, event):
        if event.type == 'ESC':
            self._pid.terminate()
            return self.cancel(context)
        
        if event.type == 'TIMER':
            # background task is still running
            if None == self._pid.poll():
                # read line without blocking
                try:  rawline = self._queue.get_nowait()
                except Empty:
                    pass
                else:
                    line = rawline.decode().strip("\r\n")
                    self.report({'INFO'}, line)
            else:
                # background task finished running
                self.read_weight_data(self._objs, os.path.join(bpy.utils.script_path_user(), "addons", "surface_heat_diffuse_skinning", "data", "untitled-weight.txt"))
                running_time = time.time() - self._start_time
                self.report({'INFO'}, "".join(("Complete, ", "running time: ", \
                str(int(running_time / 60))," minutes ", str(int(running_time % 60)), " seconds")))
                # bind meshes to the armature
                bpy.ops.object.parent_set(type='ARMATURE')
                return self.cancel(context)

        return {'RUNNING_MODAL'}

    def execute(self, context):
        self._objs = []
        self._permulation = []
        self._selected_indices = []
        self._selected_group_index_weights = []

        arm = None
        objs = []
        
        # get armature and mesh
        for ob in bpy.context.selected_objects:
            if 'ARMATURE' == ob.type:
                arm = ob
            if 'MESH' == ob.type:
                objs.append(ob)
            
        # sort meshes by name
        objs.sort(key=lambda obj:obj.name);
        # save the reference for later use
        self._objs = objs
        
        for obj in objs:
            # focus on the mesh
            bpy.context.scene.objects.active = obj
            # synchronize data
            bpy.ops.object.mode_set(mode='OBJECT')
        
        # write mesh data
        self.write_mesh_data(objs, os.path.join(bpy.utils.script_path_user(), "addons", "surface_heat_diffuse_skinning", "data", "untitled-mesh.txt"))

        # we must focus on the armature before we can write bone data
        bpy.context.scene.objects.active = arm
        # synchronize data
        bpy.ops.object.mode_set(mode='OBJECT')
    
        # write bone data
        self.write_bone_data(arm, os.path.join(bpy.utils.script_path_user(), "addons", "surface_heat_diffuse_skinning", "data", "untitled-bone.txt"))
        
        # do voxel skinning in background
        ON_POSIX = 'posix' in sys.builtin_module_names
        
        # chmod
        if ON_POSIX:
            os.chmod(os.path.join(bpy.utils.script_path_user(), "addons", "surface_heat_diffuse_skinning", "bin", platform.system(), "shd"), 0o755)

        def enqueue_output(out, queue):
            for line in iter(out.readline, b''):
                queue.put(line)
            out.close()

        self._pid = Popen([os.path.join(bpy.utils.script_path_user(), "addons", "surface_heat_diffuse_skinning", "bin", platform.system(), "shd"),
                        "untitled-mesh.txt",
                        "untitled-bone.txt",
                        "untitled-weight.txt",
                        str(context.scene.surface_resolution),
                        str(context.scene.surface_loops),
                        str(context.scene.surface_samples),
                        str(context.scene.surface_influence),
                        str(context.scene.surface_falloff),
                        context.scene.surface_sharpness],
                        cwd = os.path.join(bpy.utils.script_path_user(), "addons", "surface_heat_diffuse_skinning", "data"),
                        stdout = PIPE,
                        bufsize = 1,
                        close_fds = ON_POSIX)

        self._queue = Queue()
        t = Thread(target=enqueue_output, args=(self._pid.stdout, self._queue))
        t.daemon = True
        t.start()
        
        self._start_time = time.time()
        # start timer to poll data
        self._timer = context.window_manager.event_timer_add(0.1, context.window)
        context.window_manager.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def cancel(self, context):
        # remove timer
        context.window_manager.event_timer_remove(self._timer)
        self._objs = []
        self._permulation = []
        self._selected_indices = []
        self._selected_group_index_weights = []
        return {'CANCELLED'}

def init_properties():
    bpy.types.Scene.surface_resolution = IntProperty(
        name = "Voxel Resolution",
        description = "Maximum voxel grid size",
        default = 128,
        min = 32,
        max = 256)
 
    bpy.types.Scene.surface_loops = IntProperty(
        name = "Diffuse Loops",
        description = "Heat diffuse pass = Voxel Resolution * Diffuse Loops",
        default = 5,
        min = 1,
        max = 9)
 
    bpy.types.Scene.surface_samples = IntProperty(
        name = "Sample Rays",
        description = "Ray samples count",
        default = 64,
        min = 32,
        max = 128)
 
    bpy.types.Scene.surface_influence = IntProperty(
        name = "Influence Bones",
        description = "Max influence bones",
        default = 4,
        min = 1,
        max = 8)
 
    bpy.types.Scene.surface_falloff = FloatProperty(
        name = "Diffuse Falloff",
        description = "Heat diffuse falloff",
        default = 0.2,
        min = 0.01,
        max = 0.99)
 
    bpy.types.Scene.surface_protect = BoolProperty(
        name = "Protect Selected Vertex Weight", 
        description = "Protect selected vertex weight",
        default = False)

    bpy.types.Scene.surface_sharpness = EnumProperty(
        name = "Edges",
        description = "Edges",
        items = [
	('1','Soft','Soft Curvature'),
	('2','Normal','Normal Curvature'),
	('3','Sharp','Sharp Curvature'),
	('4','Sharpest','Sharpest Curvature')],
	default = '3')

def clear_properties():
    props = ["surface_resolution",
    "surface_samples",
    "surface_falloff",
    "surface_loops",
    "surface_influence",
    "surface_protect"]

    for p in props:
        if p in bpy.types.Scene.bl_rna.properties:
            exec("del bpy.types.Scene." + p)

class SurfaceHeatDiffuseSkinningPanel(bpy.types.Panel):
    """Creates a Panel in the Object properties window"""
    bl_label = "Surface Heat Diffuse Skinning"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_category = 'Animation'

    @classmethod
    def poll(self, context):
        arm_count = 0
        obj_count = 0
        for ob in bpy.context.selected_objects:
            if 'ARMATURE' == ob.type:
                arm_count += 1
            if 'MESH' == ob.type:
                obj_count += 1
        return (context.mode == 'OBJECT' and arm_count == 1 and obj_count >= 1)

    
    def draw(self, context):
        layout = self.layout

        layout.prop(context.scene, 'surface_resolution', icon='BLENDER', toggle=True)
        layout.prop(context.scene, 'surface_loops', icon='BLENDER', toggle=True)
        layout.prop(context.scene, 'surface_samples', icon='BLENDER', toggle=True)
        layout.prop(context.scene, 'surface_influence', icon='BLENDER', toggle=True)
        layout.prop(context.scene, 'surface_falloff', icon='BLENDER', toggle=True)
        layout.prop(context.scene, 'surface_sharpness')
        layout.prop(context.scene, 'surface_protect')

        row = layout.row()
        row.operator("wm.surface_heat_diffuse")


def register():
    bpy.utils.register_class(SurfaceHeatDiffuseSkinningPanel)
    bpy.utils.register_class(ModalTimerOperator)
    init_properties()


def unregister():
    bpy.utils.unregister_class(SurfaceHeatDiffuseSkinningPanel)
    bpy.utils.unregister_class(ModalTimerOperator)
    clear_properties()


if __name__ == "__main__":
    register()
