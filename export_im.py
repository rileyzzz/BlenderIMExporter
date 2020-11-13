import os
import io
import struct

import bpy
from mathutils import Matrix, Vector, Color
from bpy_extras import io_utils, node_shader_utils
import bmesh
from bpy_extras.wm_utils.progress_report import (
    ProgressReport,
    ProgressReportSubstep,
)

def name_compat(name):
    if name is None:
        return 'None'
    else:
        return name.replace(' ', '_')
    
def mesh_triangulate(me):
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()

#def split_obj(split_objects, obj):
#    print("Too many vertices on object " + obj.name + "! Splitting.")
#    objcount = len(obj.vertices) % 65535
#    for i in range(objcount):
#        baseIndex = i * 65535
#        bm = bmesh.new()
#        bm.from_mesh(me)
#        #new_obj.data = obj.data.copy()
#        bm.vertices = obj.vertices[baseIndex : baseIndex + 65535]
#        
        
    #new_obj = src_obj.copy()
    #new_obj.data = src_obj.data.copy()
    
def chunk_ver(f, ver):
    f.write(struct.pack("<I", ver))

def end_chunk(f, chunk):
    f.write(struct.pack("<I", chunk.tell()))
    f.write(chunk.getbuffer())
            
def write_file(filepath, objects, depsgraph, scene,
               EXPORT_APPLY_MODIFIERS=True,
               EXPORT_KIN=True,
               EXPORT_SEL_ONLY=False,
               EXPORT_GLOBAL_MATRIX=None,
               #progress=ProgressReport(),
               ):
    if EXPORT_GLOBAL_MATRIX is None:
        EXPORT_GLOBAL_MATRIX = Matrix()
    
    
    #split objects
#    split_objects = []
#    for obj in objects:
#        final = obj.evaluated_get(depsgraph)# if EXPORT_APPLY_MODIFIERS else ob.original
#        try:
#            me = final.to_mesh()
#        except RuntimeError:
#            me = None

#        if me is None:
#            continue
#        
#        mesh_triangulate(me)
#        #me.transform(EXPORT_GLOBAL_MATRIX @ ob_mat)
#        if(len(me.vertices) < 65535):
#            split_objects.append(me)
#        else:
#            split_obj(split_objects, me)
    
    #with ProgressReportSubstep(progress, 2, "IM Export path: %r" % filepath, "IM Export Finished") as subprogress1:
    
    meshes = []
    for obj in objects:
        final = obj.evaluated_get(depsgraph)# if EXPORT_APPLY_MODIFIERS else ob.original
        try:
            me = final.to_mesh()
        except RuntimeError:
            me = None

        if me is None:
            continue
        meshes.append([obj, me])
    
    with open(filepath, "wb") as f:
        #fw = f.write
        
        #JIRF, filesize
        f.write('JIRF'.encode('utf-8'))
        with io.BytesIO() as rf: #resource file
            rf.write('IDXM'.encode('utf-8'))
            
            rf.write('INFO'.encode('utf-8'))
            with io.BytesIO() as info:
                chunk_ver(info, 102)
                objLocation, objRotation, objScale = EXPORT_GLOBAL_MATRIX.decompose();
                #Position
                info.write(struct.pack("<fff", objLocation.x, objLocation.y, objLocation.z))
                #Rotation
                info.write(struct.pack("<ffff", objRotation.x, objRotation.y, objRotation.z, objRotation.w))
                #NumAttributes
                info.write(struct.pack("<I", 0)) #FIX
                #MaxInfluencePerVertex
                info.write(struct.pack("<I", 0))
                #MaxInfluencePerChunk
                info.write(struct.pack("<I", 0))
                end_chunk(rf, info)
            
            for i, entry in enumerate(meshes):
                obj = entry[0]
                mesh = entry[1]
                mat = obj.active_material
                if mat is None:
                    mat = bpy.data.materials.new("Material." + str(i))
                
                rf.write('CHNK'.encode('utf-8'))
                with io.BytesIO() as attr:
                    chunk_ver(attr, 101)
                    #Chunk ID
                    attr.write(struct.pack("<I", i))
                    attr.write('MATL'.encode('utf-8'))
                    with io.BytesIO() as matl:
                        chunk_ver(matl, 102)
                        #mat = mesh.active_material
                        #Name
                        encoded_name = mat.name.encode('utf-8') + '\0'
                        matl.write(struct.pack("<I", len(encoded_name)))
                        matl.write(encoded_name)
                        #NumProperties
                        matl.write(struct.pack("<I", 0))
                        #TwoSided
                        matl.write(struct.pack("<I", int(not mat.use_backface_culling)))
                        
                        end_chunk(attr, matl)
                        
                    end_chunk(rf, attr)
                
                
                mesh_triangulate(me)
                #me.transform(EXPORT_GLOBAL_MATRIX @ ob_mat)

            #with io.BytesIO() as attr:
                
            #for i, ob_main in enumerate(objects):
            end_chunk(f, rf)
            
        #fw('IDXM'.encode('utf-8'))
        
        
        
        
        
        
            
def _write(context, filepath,
           EXPORT_APPLY_MODIFIERS,
           EXPORT_KIN,
           EXPORT_SEL_ONLY,
           EXPORT_GLOBAL_MATRIX,
           ):

    base_name, ext = os.path.splitext(filepath)
    context_name = [base_name, '', '', ext]  # Base name, scene name, frame number, extension

    depsgraph = context.evaluated_depsgraph_get()
    scene = context.scene

    # Exit edit mode
    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode='OBJECT')

    #if EXPORT_SEL_ONLY:
        #objects = context.selected_objects
    #else:
        #objects = scene.objects
    objects = scene.objects
    
    #orig_frame = scene.frame_current
    full_path = ''.join(context_name)
        # EXPORT THE FILE.
    write_file(full_path, objects, depsgraph, scene,
               EXPORT_APPLY_MODIFIERS,
               EXPORT_KIN,
               EXPORT_SEL_ONLY,
               EXPORT_GLOBAL_MATRIX,
               #progress,
               )



def save(context,
         filepath,
         *,
         use_selection=False,
         use_mesh_modifiers=True,
         use_kin=True,
         global_matrix=None,
         path_mode='AUTO'
         ):

    _write(context, filepath,
           EXPORT_APPLY_MODIFIERS=use_mesh_modifiers,
           EXPORT_KIN=use_kin,
           EXPORT_SEL_ONLY=use_selection,
           EXPORT_GLOBAL_MATRIX=global_matrix,
           )

    return {'FINISHED'}
