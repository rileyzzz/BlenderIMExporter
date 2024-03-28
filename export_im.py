import os
import io
import struct
import bmesh
import bpy
import math
import mathutils
import bl_math
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
    #import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()

def veckey2d(v):
    return round(v[0], 4), round(v[1], 4)

def veckey3d(v):
    return round(v[0], 4), round(v[1], 4), round(v[2], 4)
    
def power_of_two(n):
    return (n & (n-1) == 0) and n != 0

def remove_scale_from_matrix(mat):
    loc, rot, scale = mat.decompose()
    return mathutils.Matrix.Translation(loc) @ rot.to_matrix().to_4x4()

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

def sanitize_filename(str):
    outstr = ''
    for c in str:
        outchar = c
        if c == '{' or c == '}' or c == '<' or c == '>':
            outchar = '_'
        
        outstr += outchar
    
    return outstr

GLOBAL_WIDE_STRINGS = False

def jet_str(f, str, wide=False):
    global GLOBAL_WIDE_STRINGS
    wide = wide or GLOBAL_WIDE_STRINGS
    
    encoded_name = bytearray(str.encode('utf-16le' if wide else 'utf-8'))

    #wacky Jet byte alignment
    str_length = len(encoded_name)

    numTerminators = 4 - str_length % 4 if str_length % 4 != 0 else 0
    encoded_name += bytes('\0' * numTerminators, 'utf-8')

    len_bytes = bytearray(struct.pack("<I", len(encoded_name)))
    if(wide):
        len_bytes[3] = 0x40
    
    f.write(len_bytes)
    f.write(encoded_name)

def texture_file(type, img_path, target_dir, is_npo2, alpha):
    basename = os.path.basename(img_path).lower()
    texturepath = sanitize_filename(target_dir + '\\' + os.path.splitext(basename)[0] + ".texture")
    txtpath = texturepath + ".txt"
    print("write to " + txtpath)
    with open(txtpath, "w") as f:
        f.write("Primary=" + basename + "\n")
        if alpha:
            f.write("Alpha=" + basename + "\n")
        f.write("Tile=st" + "\n")
        if is_npo2:
            f.write("nonpoweroftwo=1\n")
        if type == 8:
            f.write("NormalMapHint=normalmap\n")
    return texturepath

def chunk_ver(f, ver):
    f.write(struct.pack("<I", ver))

def end_chunk(f, chunk):
    f.write(struct.pack("<I", chunk.tell()))
    f.write(chunk.getbuffer())

def recursive_writebone(chnk, srcBone, bones_flat, EXPORT_ALL_BONES):
    bones_flat.append(srcBone)

    relevant_children = []
    for child in srcBone.children:
        if "b.r." in child.name or EXPORT_ALL_BONES:
            relevant_children.append(child)

    chnk.write('BONE'.encode('utf-8'))
    with io.BytesIO() as bone:
        chunk_ver(bone, 100)
        #BoneName
        bone_name = srcBone.name
        if not bone_name.startswith("b.r."):
            bone_name = "b.r." + bone_name
        jet_str(bone, bone_name)

        #NumChildren
        bone.write(struct.pack("<I", len(relevant_children)))
        #BoneList
        for child in relevant_children:
            recursive_writebone(bone, child, bones_flat, EXPORT_ALL_BONES)
        end_chunk(chnk, bone)

#Recursive SKEL for embedded .im export
def recursive_writebone_skel(chnk, srcBone, armature, EXPORT_GLOBAL_MATRIX, EXPORT_ALL_BONES):
    relevant_children = []
    for child in srcBone.children:
        if "b.r." in child.name or EXPORT_ALL_BONES:
            relevant_children.append(child)

    chnk.write('BONE'.encode('utf-8'))
    with io.BytesIO() as bone:
        chunk_ver(bone, 100)
        #BoneName
        bone_name = srcBone.name
        if not bone_name.startswith("b.r."):
            bone_name = "b.r." + bone_name
        jet_str(bone, bone_name)

        if srcBone.parent == None:
            boneMat = srcBone.matrix_local
        else:
            boneMat = srcBone.parent.matrix_local.inverted() @ srcBone.matrix_local

        if armature != None:
            boneMat = EXPORT_GLOBAL_MATRIX @ armature.matrix_world @ boneMat
        else:
            boneMat = EXPORT_GLOBAL_MATRIX @ boneMat

        position, rotation, scale = boneMat.decompose()
        rotation = rotation.inverted()

        #Position
        bone.write(struct.pack("<fff", *position))
        #Orientation
        bone.write(struct.pack("<ffff", rotation.x, rotation.y, rotation.z, rotation.w))

        #NumChildren
        bone.write(struct.pack("<I", len(relevant_children)))

        #BoneList
        for child in relevant_children:
            recursive_writebone_skel(bone, child, armature, EXPORT_GLOBAL_MATRIX, EXPORT_ALL_BONES)
        end_chunk(chnk, bone)


def write_kin(filepath, bones, armature, frame_start, frame_end, framerate, events, EXPORT_GLOBAL_MATRIX, EXPORT_ANIM_SCALE, EXPORT_ANIM_RELATIVE_POSITIONING, EXPORT_ALL_BONES):
    print("Writing .kin to " + filepath)

    scene = bpy.context.scene
    NumFrames = frame_end - frame_start + 1

    
    armatureMat = mathutils.Matrix.Identity(4)

    if armature != None:
        armatureMat = armature.matrix_world

    _, _, armatureScale = armatureMat.decompose()

    root_bone = None
    for key in bones:
        bonegroup = bones[key]
        bone = bonegroup["srcBone"]

        if bone.parent is None:
            root_bone = bone
            break

    if root_bone is None:
        print("Could not find a root bone!")
        return

    with open(filepath, "wb") as f:
        #JIRF, filesize
        f.write('JIRF'.encode('utf-8'))
        with io.BytesIO() as rf: #resource file
            rf.write('ANIM'.encode('utf-8'))

            rf.write('INFO'.encode('utf-8'))
            with io.BytesIO() as info:
                version_needed = 100
                if EXPORT_ANIM_SCALE or EXPORT_ANIM_RELATIVE_POSITIONING:
                    version_needed = 102
                # if EXPORT_ANIM_RELATIVE_POSITIONING:
                #     version_needed = 257
                flags_needed = version_needed >= 102

                chunk_ver(info, version_needed)
                #FileName
                jet_str(info, os.path.basename(filepath).lower())
                #NumFrames
                info.write(struct.pack("<I", NumFrames))
                #FrameRate
                info.write(struct.pack("<I", framerate))
                #MetricScale
                info.write(struct.pack("<f", 1.0))

                #Flags
                if flags_needed:
                    flags = 0
                    if EXPORT_ANIM_SCALE:
                        flags |= 0x2
                    if EXPORT_ANIM_RELATIVE_POSITIONING:
                        flags |= 0x1
                        #flags |= 0x8
                    
                    info.write(struct.pack("<I", flags))

                end_chunk(rf, info)

            # AFAIK, supported event types are AET_SOUND_EVENT (0), and AET_GENERIC_EVENT (4)
            # sound events will play the entry of the same name within the soundscript container in the config - best example of this is the PB interior coalman (<kuid:-25:696>)
            # generic events are probably used by script

            #Events
            rf.write('EVNT'.encode('utf-8'))
            with io.BytesIO() as evnt:
                chunk_ver(evnt, 100)
                #NumEvents
                #evnt.write(struct.pack("<I", 0))
                evnt.write(struct.pack("<I", len(events)))

                for evt in events:
                    typeid = 4 #AET_GENERIC_EVENT
                    if(evt["type"] == "sound"):
                        typeid = 0 #AET_SOUND_EVENT
                    
                    evnt.write(struct.pack("<I", evt["frame"]))
                    evnt.write(struct.pack("<I", typeid))
                    jet_str(evnt, evt["name"])
                    

                end_chunk(rf, evnt)

            bones_flat = []

            #Skeleton
            rf.write('SKEL'.encode('utf-8'))
            with io.BytesIO() as skel:
                chunk_ver(skel, 100)
                #SkeletonBlock
                recursive_writebone(skel, root_bone, bones_flat, EXPORT_ALL_BONES)
                #skel.write(struct.pack("<I", 0))
                end_chunk(rf, skel)

            posebones_flat = []
            if armature != None:
                for bone in bones_flat:
                    print("bone " + bone.name)
                    for posebone in armature.pose.bones:
                        if posebone.name == bone.name:
                            posebones_flat.append(posebone)
                            break

            objbones_flat = []
            for obj in bones_flat:
                if hasattr(obj, 'type') and (obj.type == 'EMPTY' or obj.type == 'LATTICE' or obj.type == 'MESH'):
                    objbones_flat.append(obj)

                #pose_bone = (b for b in armature.pose.bones if b.bone is bone)
                #posebones_flat.append(pose_bone)
            if armature != None:
                print("Found " + str(len(posebones_flat)) + "/" + str(len(armature.pose.bones)) + " pose bones")

            print("Found " + str(len(objbones_flat)) + " object bones")
            #FrameList
            for i in range(frame_start, frame_end + 1):
                scene.frame_set(i)
                rf.write('FRAM'.encode('utf-8'))
                with io.BytesIO() as fram:
                    if not EXPORT_ANIM_SCALE:
                        chunk_ver(fram, 100)
                    else:
                        chunk_ver(fram, 101)
                    
                    #version 101 fixes a lot of things - bone matrices are parent relative rather than global, and rotations aren't backwards anymore

                    #game may not bother animating if this is outside 0 to NumFrames - 1
                    #FrameNum
                    fram.write(struct.pack("<I", i - frame_start))

                    #BoneDataList
                    for pose_bone in posebones_flat:
                        #mat = pose_bone.matrix_basis
                        
                        # if not EXPORT_ANIM_RELATIVE_POSITIONING or pose_bone.parent is None:
                        #     mat = mat @ pose_bone.matrix
                        # else:
                        #     mat = mat @ pose_bone.parent.matrix.inverted() @ pose_bone.matrix
                        
                        if not EXPORT_ANIM_RELATIVE_POSITIONING:
                            mat = armatureMat @ pose_bone.matrix
                        else:
                            if pose_bone.parent == None:
                                # limitation here where the root node will ignore scaling data
                                # we can't remove the scaling from the armature matrix alone as that will break the world space conversion of the root node's matrix
                                mat = remove_scale_from_matrix(armatureMat @ pose_bone.matrix)
                                #mat = pose_bone.matrix
                            else:
                                #convert bone transforms into world space and remove the scale if necessary
                                parentMatrix = pose_bone.parent.matrix
                                childMatrix = pose_bone.matrix

                                # if not EXPORT_ANIM_SCALE:
                                #     parentMatrix = remove_scale_from_matrix(parentMatrix)
                                #     childMatrix = remove_scale_from_matrix(childMatrix)
                                
                                mat = parentMatrix.inverted() @ childMatrix

                        
                        mat = EXPORT_GLOBAL_MATRIX @ mat

                        position, rotation, scale = mat.decompose()

                        if EXPORT_ANIM_RELATIVE_POSITIONING: # and pose_bone.parent != None
                            position = position * armatureScale
                            #scale = scale * armatureScale
                        
                        if not EXPORT_ANIM_RELATIVE_POSITIONING:
                            rotation = rotation.inverted()
                        
                        #Position
                        fram.write(struct.pack("<fff", *position))
                        #Orientation
                        fram.write(struct.pack("<ffff", rotation.x, rotation.y, rotation.z, rotation.w))

                        if EXPORT_ANIM_SCALE:
                            #Scale
                            fram.write(struct.pack("<fff", scale.x, scale.y, scale.z))

                    for obj_bone in objbones_flat:
                        #objMat = obj_bone.matrix_world
                        #if obj_bone.parent != None:
                            #objMat = obj_bone.parent.matrix_world.inverted() @ objMat
                        #objMat = EXPORT_GLOBAL_MATRIX @ objMat

                        objMat = obj_bone.matrix_world

                        if EXPORT_ANIM_RELATIVE_POSITIONING:
                            objMat = obj_bone.matrix_local

                        objMat = EXPORT_GLOBAL_MATRIX @ objMat
                        position, rotation, scale = objMat.decompose()

                        if not EXPORT_ANIM_RELATIVE_POSITIONING:
                            rotation = rotation.inverted()
                        
                        #Position
                        fram.write(struct.pack("<fff", *position))
                        #Orientation
                        fram.write(struct.pack("<ffff", rotation.x, rotation.y, rotation.z, rotation.w))

                        if EXPORT_ANIM_SCALE:
                            #Scale
                            fram.write(struct.pack("<fff", scale.x, scale.y, scale.z))

                    end_chunk(rf, fram)

            end_chunk(f, rf)

def gather_curve_data(me, obj, objectParent, material, EXPORT_BOUNDS, bounds_set, meshes):

    if len(me.uv_layers) == 0:
        uv_layer = None
    else:
        uv_layer = me.uv_layers.active.data[:]

    print("Processing curve...")

    #should be final - edge split, etc
    vertgroups = obj.vertex_groups

    #uv dictionary must be per object, otherwise duplicate objects (with similar normals and uvs) get merged
    uv_dict = {}
    uv = uv_key = uv_val = None
    
    unique_verts = []
    indices = []
    normals = []

    influence_bones = []

    for i, edge in enumerate(me.edges):
        for v in edge.vertices:
            vert = me.vertices[v]

            #texcoords are transformed 1.0 - y
            uv = [0, 1]
            no = vert.normal

            uv_key = v, veckey3d(no)
            uv_val = uv_dict.get(uv_key)

            if uv_val is None:
                uv_dict[uv_key] = len(unique_verts)

                influences = {}
                for group in vertgroups:
                    try:
                        weight = group.weight(v)
                    except RuntimeError:
                        weight = 0.0
                    if weight != 0.0:
                        influences[group.name] = weight
                        if group.name not in influence_bones:
                            influence_bones.append(group.name)

                unique_verts.append([vert.co[:], uv[:], influences])
                normals.append(no.normalized())
                
                if EXPORT_BOUNDS:
                    if bounds_set:
                        bounds_min.x = min(bounds_min.x, vert.co.x)
                        bounds_min.y = min(bounds_min.y, vert.co.y)
                        bounds_min.z = min(bounds_min.z, vert.co.z)
                        bounds_max.x = max(bounds_max.x, vert.co.x)
                        bounds_max.y = max(bounds_max.y, vert.co.y)
                        bounds_max.z = max(bounds_max.z, vert.co.z)
                    else:
                        bounds_set = True
                        bounds_min = mathutils.Vector(vert.co)
                        bounds_max = mathutils.Vector(vert.co)

            indices.append(uv_dict[uv_key])

        if len(unique_verts) > 65532 or len(indices) // 3 > 65535:
            #apply and update
            mesh_data = {
                "obj": obj,
                "material": material,
                "unique_verts": unique_verts.copy(),
                "indices": indices.copy(),
                "normals": normals.copy(),
                "face_normals": [],
                "face_list": [],
                "tangents": [],
                "area": 0.0,
                "uv_layer": uv_layer,
                "parent": objectParent,
                "is_curve": True,
                "max_influence": len(influence_bones)
            }

            meshes.append(mesh_data)

            unique_verts.clear()
            indices.clear()
            normals.clear()

            uv_dict.clear()
            uv = uv_key = uv_val = None

            influence_bones.clear()
            
            print("Block split.")

    if len(unique_verts) > 0:
        mesh_data = {
            "obj": obj,
            "material": material,
            "unique_verts": unique_verts.copy(),
            "indices": indices.copy(),
            "normals": normals.copy(),
            "face_normals": [],
            "face_list": [],
            "tangents": [],
            "area": 0.0,
            "uv_layer": uv_layer,
            "parent": objectParent,
            "is_curve": True,
            "max_influence": len(influence_bones)
        }

        meshes.append(mesh_data)



def write_file(self, filepath, objects, scene,
               EXPORT_APPLY_MODIFIERS=True,
               EXPORT_CURVES=False,
               EXPORT_TEXTURETXT=True,
               EXPORT_CONVERT_TGA=False,
               EXPORT_TANGENTS=True,
               EXPORT_BOUNDS=True,
               EXPORT_VERTEX_COLORS=False,
               EXPORT_NEIGHBOR_INFO=False,
               EXPORT_SUBSURF_AMBIENT=False,
               EXPORT_CUSTOM_PROPERTIES=False,
               EXPORT_KIN=True,
               EXPORT_BLENDER_FRAMERATE=False,
               EXPORT_SKEL=False,
               EXPORT_ANIM_SCALE=False,
               EXPORT_ANIM_RELATIVE_POSITIONING=False,
               EXPORT_ALL_BONES=False,
               EXPORT_ANIM_NLA=False,
               EXPORT_ANIM_EVENTS=True,
               EXPORT_EXPLICIT_VERSIONING=False,
               EXPORT_INFO_VERSION=None,
               EXPORT_MATL_VERSION=None,
               EXPORT_GEOM_VERSION=None,
               EXPORT_SEL_ONLY=False,
               EXPORT_GLOBAL_MATRIX=None,
               EXPORT_PATH_MODE='AUTO',
               #progress=ProgressReport(),
               ):
    if EXPORT_GLOBAL_MATRIX is None:
        EXPORT_GLOBAL_MATRIX = Matrix()

    #split objects
    meshes = []
    hold_meshes = [] #prevent garbage collection of bmeshes

    #set to defaults
    bounds_set = False
    bounds_min = mathutils.Vector((0.0, 0.0, 0.0))
    bounds_max = mathutils.Vector((0.0, 0.0, 0.0))
    use_anim_bounds = EXPORT_KIN and EXPORT_BOUNDS
    max_vert_influences = 0
    max_chunk_influences = 0

    material_groups = {}
    curves = []

    if use_anim_bounds:
        for i in range(scene.frame_start, scene.frame_end + 1):
            scene.frame_set(i)
            for obj in objects:
                for coord in obj.bound_box:
                    co_vector = mathutils.Vector((coord[0], coord[1], coord[2], 1.0))
                    co_vector = EXPORT_GLOBAL_MATRIX @ obj.matrix_world @ co_vector
                    if bounds_set:
                        bounds_min.x = min(bounds_min.x, co_vector.x)
                        bounds_min.y = min(bounds_min.y, co_vector.y)
                        bounds_min.z = min(bounds_min.z, co_vector.z)
                        bounds_max.x = max(bounds_max.x, co_vector.x)
                        bounds_max.y = max(bounds_max.y, co_vector.y)
                        bounds_max.z = max(bounds_max.z, co_vector.z)
                    else:
                        bounds_set = True
                        bounds_min = mathutils.Vector(co_vector)
                        bounds_max = mathutils.Vector(co_vector)
                    
        scene.frame_set(scene.frame_start)


    for obj in objects:

        #curves can be converted into meshes
        is_curve = obj.type == 'CURVE'

        if not EXPORT_CURVES and is_curve:
            continue

        if EXPORT_APPLY_MODIFIERS:
            armature_modifiers = {}
            if EXPORT_KIN:
                # temporarily disable Armature modifiers if exporting skins
                for idx, modifier in enumerate(obj.modifiers):
                    if modifier.type == 'ARMATURE':
                        armature_modifiers[idx] = modifier.show_viewport
                        modifier.show_viewport = False
            
            depsgraph = bpy.context.evaluated_depsgraph_get()
            final = obj.evaluated_get(depsgraph)
            try:
                me = final.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph).copy()
            except RuntimeError:
                me = None

            if EXPORT_KIN:
                # restore Armature modifiers
                for idx, show_viewport in armature_modifiers.items():
                    obj.modifiers[idx].show_viewport = show_viewport
        else:
            me = obj.data

        if me is None:
            continue

        #uv_layer = me.uv_layers.active.data
        #mesh_triangulate(me)
        objectParent = None #empty and lattice parents
        #meshes can be nodes themselves
        if "b.r." in obj.name:
            objectParent = obj
        elif obj.parent != None:
            if "b.r." in obj.parent.name:
                objectParent = obj.parent
        
        print("Pre-processing object " + obj.name)
        me.transform(EXPORT_GLOBAL_MATRIX @ obj.matrix_world)
        
        if bpy.app.version < (4, 1, 0):
            me.calc_normals_split()

        use_tangents = EXPORT_TANGENTS
        if EXPORT_TANGENTS:
            if len(me.uv_layers) > 0 or me.uv_layers.active: # or len(me.uv_layers.active.data) < len(me.loops)
                try:
                    me.calc_tangents()
                except Exception:
                    self.report({'INFO'}, 'Mesh \'' + obj.name + '\' has polygons with more than 4 vertices. Unable to calculate tangents.')
                    use_tangents = False
            else:
                self.report({'WARNING'}, 'Object \'' + obj.name + '\' is missing UV data, which is required for tangent generation.')
                use_tangents = False
            

        materials = me.materials[:]
        print("object contains " + str(len(materials)) + " materials")
        if len(materials) == 0:
            materials.append(None)

        if EXPORT_CURVES and is_curve:
            gather_curve_data(me, obj, objectParent, materials[0], EXPORT_BOUNDS, bounds_set, meshes)
            continue
        
        me.calc_loop_triangles()

        mats_2_faces = {}
        edges_2_faces = {}

        invalid_material_indices = {}

        for face in me.loop_triangles:
            mat_index = face.material_index
            if mat_index is None:
                mat_index = 0
            if mat_index < 0 or mat_index >= len(materials):
                mat_index = 0
                if mat_index not in invalid_material_indices:
                    invalid_material_indices[mat_index] = True
                    self.report({'WARNING'}, f'Object \'{obj.name}\' contains an invalid material index {face.material_index}.')

            mat = materials[mat_index]
            if mat not in mats_2_faces:
                mats_2_faces[mat] = []
            mats_2_faces[mat].append(face)

            if EXPORT_NEIGHBOR_INFO:
                for l in face.loops:
                    edge_index = me.loops[l].edge_index
                    if not edge_index in edges_2_faces:
                        edges_2_faces[edge_index] = []
                    edges_2_faces[edge_index].append(face)
        
        for mat in materials:
            #if objects have a different parent (animation) they shouldn't be collated
            mat_key = mat, use_tangents, objectParent

            if mat_key not in material_groups:
                material_groups[mat_key] = []

            #if the material doesn't have any faces assigned to it, don't bother giving it a chunk
            if mat not in mats_2_faces:
                continue

            obj_data = {
                "me": me,
                "obj": final,
                "materials": materials,
                "faces": mats_2_faces[mat],
                "edges_2_faces": edges_2_faces,
                "parent": objectParent
            }

            material_groups[mat_key].append(obj_data)

    neighbor_map = {}
    face_2_index_map = {}

    for mat_key, group in material_groups.items():
        material = mat_key[0]
        use_tangents = mat_key[1]
        print("Processing material")
        #per-chunk data

        unique_verts = []
        indices = []
        normals = []
        face_normals = []
        face_list = []
        tangents = []
        colors = []

        area = 0.0
        influence_bones = []
        
        for obj_data in group:
            me = obj_data["me"]
            obj = obj_data["obj"]
            materials = obj_data["materials"]
            obj_faces = obj_data["faces"]
            edges_2_faces = obj_data["edges_2_faces"]
            objectParent = obj_data["parent"]

            if len(me.uv_layers) == 0:
                uv_layer = None
            else:
                uv_layer = me.uv_layers.active.data[:]
            me_verts = me.vertices[:]
            me_edges = me.edges[:]

            if len(me.vertex_colors) == 0:
                color_layer = None
            else:
                color_layer = me.vertex_colors.active.data[:]

            print("Processing mesh...")

            #should be final - edge split, etc
            vertgroups = obj.vertex_groups

            #uv dictionary must be per object, otherwise duplicate objects (with similar normals and uvs) get merged
            uv_dict = {}
            uv = uv_key = uv_val = None

            for i, face in enumerate(obj_faces):
                area += face.area

                face_normals.append(face.normal.normalized())

                neighbors = []

                if EXPORT_NEIGHBOR_INFO:
                    #store the face's parent chunk
                    neighbor_map[face] = [f for e in face.loops
                        for f in edges_2_faces[me.loops[e].edge_index] if f is not face]
                    face_2_index_map[face] = {
                        "index": len(face_list),
                        "attribute": len(meshes)
                    }
                    face_list.append(face)


                for uv_index, l_index in enumerate(face.loops):
                    loop = me.loops[l_index]
                    vert = me_verts[loop.vertex_index]
                    
                    #no = loop.normal
                    if bpy.app.version < (4, 1, 0):
                        no = mathutils.Vector(face.split_normals[uv_index])
                    else:
                        no = me.corner_normals[l_index].vector
                    
                    tg = loop.tangent

                    color = color_layer[l_index].color if color_layer else [1, 1, 1, 1]
                    uv = uv_layer[l_index].uv if uv_layer != None else [0, 0]

                    uv_key = loop.vertex_index, veckey2d(uv), veckey3d(no), veckey3d(color)
                    # todo - is this necessary? probably not, tangents don't seem to be affected by split normals
                    # veckey3d(tg),

                    uv_val = uv_dict.get(uv_key)

                    if uv_val is None:
                        uv_dict[uv_key] = len(unique_verts)

                        influences = {}
                        for group in vertgroups:
                            try:
                                weight = group.weight(loop.vertex_index)
                            except RuntimeError:
                                weight = 0.0
                            if weight != 0.0:
                                influences[group.name] = weight
                                if group.name not in influence_bones:
                                    influence_bones.append(group.name)

                        max_vert_influences = max(max_vert_influences, len(influences))

                        unique_verts.append([vert.co[:], uv[:], influences])
                        normals.append(no.normalized())

                        if use_tangents:
                            tangents.append(tg.normalized())

                        if EXPORT_VERTEX_COLORS:
                            colors.append(color)
                        
                        if EXPORT_BOUNDS and not use_anim_bounds:
                            if bounds_set:
                                bounds_min.x = min(bounds_min.x, vert.co.x)
                                bounds_min.y = min(bounds_min.y, vert.co.y)
                                bounds_min.z = min(bounds_min.z, vert.co.z)
                                bounds_max.x = max(bounds_max.x, vert.co.x)
                                bounds_max.y = max(bounds_max.y, vert.co.y)
                                bounds_max.z = max(bounds_max.z, vert.co.z)
                            else:
                                bounds_set = True
                                bounds_min = mathutils.Vector(vert.co)
                                bounds_max = mathutils.Vector(vert.co)

                    indices.append(uv_dict[uv_key])
                


                if len(unique_verts) > 65532 or len(indices) // 3 > 65535:
                    #apply and update
                    mesh_data = {
                        "obj": obj,
                        "material": material,
                        "unique_verts": unique_verts.copy(),
                        "indices": indices.copy(),
                        "normals": normals.copy(),
                        "face_normals": face_normals.copy(),
                        "face_list": face_list.copy(),
                        "tangents": tangents.copy(),
                        "colors": colors.copy(),
                        "area": area,
                        "uv_layer": uv_layer,
                        "parent": objectParent,
                        "is_curve": False,
                        "max_influence": len(influence_bones)
                    }

                    meshes.append(mesh_data)

                    unique_verts.clear()
                    indices.clear()
                    normals.clear()
                    face_normals.clear()
                    face_list.clear()
                    tangents.clear()
                    colors.clear()
                    area = 0.0
                    uv_dict.clear()
                    uv = uv_key = uv_val = None

                    max_chunk_influences = max(max_chunk_influences, len(influence_bones))
                    influence_bones.clear()

                    print("Block split.")

        #Add remaining verts
        if len(unique_verts) > 0:
            mesh_data = {
                "obj": obj,
                "material": material,
                "unique_verts": unique_verts.copy(),
                "indices": indices.copy(),
                "normals": normals.copy(),
                "face_normals": face_normals.copy(),
                "face_list": face_list.copy(),
                "tangents": tangents.copy(),
                "colors": colors.copy(),
                "area": area,
                "uv_layer": uv_layer,
                "parent": objectParent,
                "is_curve": False,
                "max_influence": len(influence_bones)
            }
            meshes.append(mesh_data)

            max_chunk_influences = max(max_chunk_influences, len(influence_bones))
            

        print("Complete.")

        #bm.free()

    active_armature = None
    bones = {}
    root_bone = None
    for ob in objects:
        if ob.type != 'ARMATURE':
            continue
        active_armature = ob
        break

    if active_armature is None:
        print("No armature in scene.")
        #EXPORT_KIN = False
    else:
        for bone in active_armature.data.bones:
            if "b.r." in bone.name or EXPORT_ALL_BONES:
                #bone, chunk influences

                if bone.parent == None:
                    boneMat = active_armature.matrix_world @ bone.matrix_local
                else:
                    #convert bone transforms into world space and remove the scale
                    parentMatrix = active_armature.matrix_world @ bone.parent.matrix_local
                    parentMatrix = remove_scale_from_matrix(parentMatrix)
                    childMatrix = active_armature.matrix_world @ bone.matrix_local
                    childMatrix = remove_scale_from_matrix(childMatrix)

                    boneMat = parentMatrix.inverted() @ childMatrix
                
                boneMat = EXPORT_GLOBAL_MATRIX @ boneMat
                worldMat = EXPORT_GLOBAL_MATRIX @ remove_scale_from_matrix(active_armature.matrix_world @ bone.matrix_local)

                bone_data = {
                    "srcBone": bone,
                    "matrix": boneMat,
                    "worldMatrix": worldMat,
                    "infl": [[] for _ in range(len(meshes))]
                }

                bones[bone.name] = bone_data
                if bone.parent == None:
                    root_bone = bone

    #legacy empty, lattice support
    for ob in objects:
        if "b.r." in ob.name:
            print("Found bone object " + ob.name)
            
            if ob.parent == None:
                boneMat = ob.matrix_world
            else:
                boneMat = ob.matrix_parent_inverse @ ob.matrix_world

            boneMat = EXPORT_GLOBAL_MATRIX @ boneMat
            worldMat = EXPORT_GLOBAL_MATRIX @ ob.matrix_world
            
            bone_data = {
                "srcBone": ob,
                "matrix": boneMat,
                "worldMatrix": worldMat,
                "infl": [[] for _ in range(len(meshes))]
            }

            bones[ob.name] = bone_data
            if ob.parent == None:
                root_bone = ob

    if EXPORT_KIN:
        anim_framerate = 30
        scene = bpy.context.scene

        events = []
        if EXPORT_ANIM_EVENTS:
            for evt in scene.timeline_markers:
                name = evt.name
                type = "generic"
                if name.startswith("s."):
                    name = name[2:]
                    type = "sound"
                
                data = {
                    "frame": evt.frame,
                    "type": type,
                    "name": name
                }
                events.append(data)

        if EXPORT_BLENDER_FRAMERATE:
            anim_framerate = int(scene.render.fps / scene.render.fps_base)
        
        if not EXPORT_ANIM_NLA:
            write_kin(os.path.splitext(filepath)[0] + ".kin", bones, active_armature, scene.frame_start, scene.frame_end, anim_framerate, events, EXPORT_GLOBAL_MATRIX, EXPORT_ANIM_SCALE, EXPORT_ANIM_RELATIVE_POSITIONING, EXPORT_ALL_BONES)
        else:
            for track in active_armature.animation_data.nla_tracks:
                if len(track.strips) == 0:
                    continue

                frame_start = track.strips[0].action_frame_start
                frame_end = track.strips[0].action_frame_end

                for strip in track.strips:
                    frame_start = min(frame_start, strip.action_frame_start)
                    frame_end = max(frame_end, strip.action_frame_end)
                
                track.is_solo = True
                write_kin(os.path.join(os.path.dirname(filepath), track.name + ".kin"), bones, active_armature, int(frame_start), int(frame_end), anim_framerate, events, EXPORT_GLOBAL_MATRIX, EXPORT_ANIM_SCALE, EXPORT_ANIM_RELATIVE_POSITIONING, EXPORT_ALL_BONES)
                track.is_solo = False

        #reset frame after writing kin, for object transforms
        # scene.frame_set(0)
        scene.frame_set(scene.frame_start)

    #Attachment setup
    attachments = []
    for ob in objects:
        if ob.type == 'EMPTY' and 'a.' in ob.name:
            print("Attachment " + ob.name)
            attachments.append(ob)

            obj_loc = ob.matrix_world.translation
            #extend bounds for attachments too
            if EXPORT_BOUNDS:
                if bounds_set:
                    bounds_min.x = min(bounds_min.x, obj_loc.x)
                    bounds_min.y = min(bounds_min.y, obj_loc.y)
                    bounds_min.z = min(bounds_min.z, obj_loc.z)
                    bounds_max.x = max(bounds_max.x, obj_loc.x)
                    bounds_max.y = max(bounds_max.y, obj_loc.y)
                    bounds_max.z = max(bounds_max.z, obj_loc.z)
                else:
                    bounds_set = True
                    bounds_min = mathutils.Vector(obj_loc)
                    bounds_max = mathutils.Vector(obj_loc)


    copy_set = set()
    with open(filepath, "wb") as f:
        #fw = f.write
        source_dir = os.path.dirname(bpy.data.filepath)
        dest_dir = os.path.dirname(filepath)

        #JIRF, filesize
        f.write('JIRF'.encode('utf-8'))
        with io.BytesIO() as rf: #resource file
            rf.write('IDXM'.encode('utf-8'))

            rf.write('INFO'.encode('utf-8'))
            with io.BytesIO() as info:
                info_version = 104
                if EXPORT_EXPLICIT_VERSIONING:
                    info_version = int(EXPORT_INFO_VERSION)
                else:
                    if EXPORT_BOUNDS:
                        info_version = 104
                    else:
                        info_version = 102
                
                chunk_ver(info, info_version)

                objLocation, objRotation, objScale = EXPORT_GLOBAL_MATRIX.decompose()

                #Position
                info.write(struct.pack("<fff", objLocation.x, objLocation.y, objLocation.z))
                #Rotation
                info.write(struct.pack("<ffff", objRotation.w, objRotation.x, objRotation.y, objRotation.z))
                #NumAttributes
                info.write(struct.pack("<I", len(meshes)))

                if info_version >= 102:
                    #MaxInfluencePerVertex
                    info.write(struct.pack("<I", max_vert_influences))
                    #MaxInfluencePerChunk
                    info.write(struct.pack("<I", max_chunk_influences))

                #Bounding Box
                if info_version >= 104:
                    info.write(struct.pack("<fff", bounds_min.x, bounds_min.y, bounds_min.z))
                    info.write(struct.pack("<fff", bounds_max.x, bounds_max.y, bounds_max.z))

                end_chunk(rf, info)


            for i, entry in enumerate(meshes):

                obj             = entry["obj"]
                mat             = entry["material"]
                verts           = entry["unique_verts"]
                indices         = entry["indices"]
                normals         = entry["normals"]
                face_normals    = entry["face_normals"]
                face_list       = entry["face_list"]
                tangents        = entry["tangents"]
                colors          = entry["colors"]
                area            = entry["area"]
                uv_layer        = entry["uv_layer"]
                objParent       = entry["parent"]
                is_curve        = entry["is_curve"]
                max_influence   = entry["max_influence"]


                defaultMaterial = bpy.data.materials.new(obj.name + ".m.notex")
                if mat is None:
                    mat = defaultMaterial
                
                #initial period before material name extension isn't required
                #TrainzMeshImporter name structure?
                # filename, CRC32?, material name, extension
                #*rmines2*4B6A2F83*material #1*m.onetex
                #*waterglass_left*704EDB8B*bulb*m.onetex

                if not mat.name.endswith("m.notex") and \
                    not mat.name.endswith("m.onetex") and \
                    not mat.name.endswith("m.reflect") and \
                    not mat.name.endswith("m.gloss") and \
                    not mat.name.endswith("m.tbumptex") and \
                    not mat.name.endswith("m.tbumpgloss") and \
                    not mat.name.endswith("m.tbumpenv"):
                    self.report({'WARNING'}, "Material " + mat.name + " on object " + obj.name + " is missing a valid material extension. This may cause issues in games earlier than TANE. A list of valid legacy material extensions is available here: https://online.ts2009.com/mediaWiki/index.php/Material_Types")
                
                rf.write('CHNK'.encode('utf-8'))
                with io.BytesIO() as attr:
                    chunk_ver(attr, 100)
                    #Chunk ID
                    attr.write(struct.pack("<I", i))
                    attr.write('MATL'.encode('utf-8'))
                    with io.BytesIO() as matl:
                        matl_version = 103
                        if EXPORT_EXPLICIT_VERSIONING:
                            matl_version = int(EXPORT_MATL_VERSION)
                        
                        chunk_ver(matl, matl_version)

                        # MATL versions:
                        # 101
                        # 102 - 101 + properties, opacity
                        # 103 - same as 102
                        
                        if matl_version >= 102:
                            # Name
                            jet_str(matl, mat.name)

                            custom_properties = {}
                            if EXPORT_CUSTOM_PROPERTIES:
                                for K in mat.keys():
                                    data = mat[K]
                                    if K not in '_RNA_UI' and (isinstance(data, float) or isinstance(data, int) or isinstance(data, str) or isinstance(data, bool)):
                                        if not isinstance(data, str):
                                            data = str(data)
                                        custom_properties[K] = data
                            
                            #NumProperties
                            matl.write(struct.pack("<I", len(custom_properties)))
                            for k in custom_properties:
                                jet_str(matl, k)
                                jet_str(matl, custom_properties[k])
                        
                        #nodes
                        mat_wrap = node_shader_utils.PrincipledBSDFWrapper(mat)

                        #TwoSided
                        matl.write(struct.pack("<I", int(not mat.use_backface_culling)))

                        #Opacity
                        if matl_version >= 102:
                            matl.write(struct.pack("<f", mat_wrap.alpha))

                        base_color = mat_wrap.base_color
                        if mat_wrap.base_color_texture != None and mat_wrap.base_color_texture.image != None:
                            base_color = [1.0, 1.0, 1.0]

                        #Ambient
                        matl.write(struct.pack("<fff", base_color[0] if not EXPORT_SUBSURF_AMBIENT or mat_wrap.node_principled_bsdf is None else mat_wrap.node_principled_bsdf.inputs["Subsurface Color"].default_value[0],
                                                       base_color[1] if not EXPORT_SUBSURF_AMBIENT or mat_wrap.node_principled_bsdf is None else mat_wrap.node_principled_bsdf.inputs["Subsurface Color"].default_value[1],
                                                       base_color[2] if not EXPORT_SUBSURF_AMBIENT or mat_wrap.node_principled_bsdf is None else mat_wrap.node_principled_bsdf.inputs["Subsurface Color"].default_value[2]))
                        #Diffuse
                        matl.write(struct.pack("<fff", base_color[0],
                                                       base_color[1],
                                                       base_color[2]))
                        #Specular
                        if isinstance(mat_wrap.specular_tint, Color):
                            # Blender 4.0 - specular tint is now a Color
                            matl.write(struct.pack("<fff", mat_wrap.specular_tint[0] * mat_wrap.specular,
                                                           mat_wrap.specular_tint[1] * mat_wrap.specular,
                                                           mat_wrap.specular_tint[2] * mat_wrap.specular))
                        else:
                            matl.write(struct.pack("<fff", bl_math.lerp(mat_wrap.specular, mat_wrap.specular * base_color[0], mat_wrap.specular_tint),
                                                        bl_math.lerp(mat_wrap.specular, mat_wrap.specular * base_color[1], mat_wrap.specular_tint),
                                                        bl_math.lerp(mat_wrap.specular, mat_wrap.specular * base_color[2], mat_wrap.specular_tint)))
                        
                        #Emissive
                        if hasattr(mat_wrap, 'emission_strength'):
                            emission_strength = mat_wrap.emission_strength
                        else:
                            emission_strength = 1.0

                        emission = [emission_strength * c for c in mat_wrap.emission_color[:3]]
                        matl.write(struct.pack("<fff", emission[0],
                                                       emission[1],
                                                       emission[2]))
                        
                        #Shininess
                        shininess = (1.0 - mat_wrap.roughness) * 128.0
                        shininess = min(max(shininess, 10.0), 128.0)
                        matl.write(struct.pack("<f", shininess))

                        #Texture setup
                        #texCount = 0
                        textures = []

                        image_source = [
                            None, #TEX_Ambient
                            "base_color_texture", #TEX_Diffuse
                            "specular_texture", #TEX_Specular
                            "roughness_texture", #TEX_Shine
                            "normalmap_texture" if mat.name.endswith(".m.tbumptex") else None, #TEX_Shinestrength, tbumptex uses the normal map alpha to determine shine strength?
                            "emission_color_texture" if emission_strength != 0.0 else None, #TEX_Selfillum
                            "alpha_texture", #TEX_Opacity
                            None, #TEX_Filtercolor
                            "normalmap_texture", #TEX_Bump,
                            "metallic_texture", #TEX_Reflect,
                            "ior_texture", #TEX_Refract,
                            None, #TEX_Displacement
                            ]
                        for type, entry in enumerate(image_source):
                            if entry is None:
                                continue
                            tex_wrap = getattr(mat_wrap, entry, None)
                            if tex_wrap is None:
                                continue
                            image = tex_wrap.image
                            if image is None:
                                continue
                            is_npo2 = not power_of_two(image.size[0]) or not power_of_two(image.size[1])
                            if is_npo2:
                                self.report({'WARNING'}, 'Texture ' + image.filepath + ' is not a power of two. Consider resizing it.')

                            if not EXPORT_CONVERT_TGA:
                                filepath = io_utils.path_reference(image.filepath, source_dir, dest_dir,
                                                        EXPORT_PATH_MODE, "", copy_set, image.library)
                            else:
                                # Windows sucks.
                                image_path = image.filepath.lstrip('\\/')

                                # Resave the image.
                                filepath = dest_dir + '\\' + os.path.basename(image_path).lower() + ".tga"
                                output_image = image.copy()

                                # Don't allow images bigger than 4k.
                                # if output_image.size[0] > 2048 or output_image.size[1] > 2048:
                                #     output_image.scale(2048, 2048)
                                    
                                output_image.file_format = 'TARGA_RAW'
                                print(f"Saved image to {filepath}, src={image_path}")
                                output_image.save(filepath=filepath)

                                bpy.data.images.remove(output_image)
                            
                            strength = 1.0

                            #don't modify strength for tbumptex shinestrength
                            if entry == "normalmap_texture" and type == 8:
                                strength = 0.2 * mat_wrap.normalmap_strength

                            # TODO: adjust strength value for TEX_Reflect (m.reflect)
                            
                            if EXPORT_TEXTURETXT:
                                texturepath = texture_file(type, filepath, dest_dir, is_npo2, image.depth == (128 if image.is_float else 32))
                            else:
                                basename = os.path.basename(filepath).lower()
                                texturepath = dest_dir + '\\' + os.path.splitext(basename)[0] + ".texture"

                            textures.append([type, texturepath, strength])

                        #NumTextures
                        matl.write(struct.pack("<I", len(textures)))
                        for tex in textures:
                            #Type
                            matl.write(struct.pack("<I", tex[0]))
                            #FileName
                            jet_str(matl, tex[1])
                            #Amount
                            matl.write(struct.pack("<f", tex[2]))

                        end_chunk(attr, matl)

                    attr.write('GEOM'.encode('utf-8'))
                    with io.BytesIO() as geom:
                        geom_version = 201
                        if EXPORT_EXPLICIT_VERSIONING:
                            geom_version = int(EXPORT_GEOM_VERSION)
                        else:
                            if EXPORT_VERTEX_COLORS:
                                ver = 104
                        
                        chunk_ver(geom, geom_version)
                        
                        # GEOM versions:
                        # 103 - Multiple texturesets
                        # 104 - 103 + vertex colors
                        # 200 - Parent bones
                        # 201 - 200 + tangent data

                        # I've only ever seen 103 and 104 show up in Bridge It - if any legacy Trainz assets actually use these let me know

                        #Flags
                        if not is_curve:
                            if geom_version >= 101:
                                geom.write(struct.pack("<I", 4)) #GC_TRIANGLES
                        else:
                            if geom_version >= 101:
                                geom.write(struct.pack("<I", 2)) #GC_LINES
                            else:
                                # Curves not supported.
                                self.report({'WARNING'}, 'Curves not supported in GEOM v100!')
                        
                        # UseTangents (201)
                        if geom_version >= 201:
                            if EXPORT_TANGENTS and len(tangents) > 0:
                                geom.write(struct.pack("<I", 1))
                            else:
                                geom.write(struct.pack("<I", 0))

                        # Area
                        geom.write(struct.pack("<f", area))

                        # NumVertices
                        geom.write(struct.pack("<I", len(verts)))

                        # NumPrimitives
                        # NOTE: NumPrimitives is supposed to be geom_version >= 101 according to JET docs,
                        # but D20 meshes are v100 and have this field.
                        if not is_curve:
                            geom.write(struct.pack("<I", len(indices) // 3))
                        else:
                            geom.write(struct.pack("<I", len(indices) // 2))
                        
                        #NumIndices
                        if geom_version >= 101:
                            geom.write(struct.pack("<I", len(indices)))
                        
                        #NumFaceNormals
                        if geom_version >= 101:
                            geom.write(struct.pack("<I", len(face_normals)))

                        #NumTexCoordSets
                        if geom_version == 103 or geom_version == 104:
                            geom.write(struct.pack("<I", 1))
                        
                        #Required for games pre-TANE, otherwise mesh refuses to animate
                        #MaxInfluence (102)
                        if geom_version >= 102:
                            geom.write(struct.pack("<I", max_influence))

                        #Parent (200)
                        if geom_version >= 200:
                            if objParent != None:
                                jet_str(geom, objParent.name)
                            else:
                                geom.write(struct.pack("<I", 0))

                        #Vertices
                        for idx, vert in enumerate(verts):
                            co = vert[0]
                            texcoord = vert[1]
                            influences = vert[2]

                            #geom.write(struct.pack("<fff", co[0], co[1], co[2]))
                            #geom.write(struct.pack("<ff", texcoord[0], 1.0 - texcoord[1]))

                            co_vector = mathutils.Vector((co[0], co[1], co[2], 1.0))
                            if objParent != None:
                                #OLD METHOD
                                #parentMat = EXPORT_GLOBAL_MATRIX @ objParent.matrix_world
                                #co_vector = parentMat.inverted() @ co_vector

                                parentLoc, parentRot, parentScale = objParent.matrix_world.decompose()

                                locMat = mathutils.Matrix.Translation(parentLoc)
                                rotMat = parentRot.to_matrix().to_4x4()
                                parentMat = locMat @ rotMat
                                co_vector = EXPORT_GLOBAL_MATRIX @ parentMat.inverted() @ co_vector

                            if math.isnan(co_vector[0]) or math.isnan(co_vector[1]) or math.isnan(co_vector[2]):
                                self.report({'WARNING'}, 'NaN position data detected in chunk ' + str(i) + " {" + obj.name + "}")
                                if math.isnan(co_vector[0]): co_vector[0] = 0.0
                                if math.isnan(co_vector[1]): co_vector[1] = 0.0
                                if math.isnan(co_vector[2]): co_vector[2] = 0.0
                                
                            #co_vector = EXPORT_GLOBAL_MATRIX @ obj.matrix_parent_inverse @ co_vector

                            geom.write(struct.pack("<fff", co_vector[0], co_vector[1], co_vector[2]))
                            geom.write(struct.pack("<ff", texcoord[0], 1.0 - texcoord[1]))

                            #BoneTransform = None #identity?
                            for name, weight in influences.items():
                                if name in bones:
                                    bonegroup = bones[name]
                                    bone = bonegroup["srcBone"]
                                    chunkinfl = bonegroup["infl"][i]

                                    #boneMat = bone.matrix_local.inverted()
                                    boneMat = bonegroup["worldMatrix"].inverted()
                                    chunkinfl.append([idx, weight, boneMat @ co_vector]) #boneMat @ co_vector

                        #Indices
                        for idx in indices:
                            geom.write(struct.pack("<H", idx))
                        
                        #VertexNormals
                        for normal in normals:
                            geom.write(struct.pack("<fff", normal[0], normal[1], normal[2]))
                        
                        #FaceNormals
                        if geom_version >= 101:
                            for normal in face_normals:
                                geom.write(struct.pack("<fff", normal[0], normal[1], normal[2]))
                        
                        #VertexColors (104 only)
                        if geom_version == 104 and EXPORT_VERTEX_COLORS and len(colors) > 0:
                            for color in colors:
                                geom.write(struct.pack("<BBBB", int(color[0] * 255.0), int(color[1] * 255.0), int(color[2] * 255.0), int(color[3] * 255.0)))
                        
                        #Tangents (201)
                        if geom_version >= 201 and EXPORT_TANGENTS and len(tangents) > 0:
                            for tangent in tangents:
                                geom.write(struct.pack("<fff", tangent[0], tangent[1], tangent[2]))

                        #bm.free()

                        end_chunk(attr, geom)
                    
                    if EXPORT_NEIGHBOR_INFO:
                        attr.write('NINF'.encode('utf-8'))
                        with io.BytesIO() as ninf:
                            chunk_ver(ninf, 100)
                            for face in face_list:
                                neighbors = neighbor_map[face]
                                for i in range(3):
                                    primitiveIndex = 0xFFFF
                                    neighborChunkIdx = 0xFFFF
                                    if i < len(neighbors):
                                        face_data = face_2_index_map[neighbors[i]]
                                        primitiveIndex = face_data["index"]
                                        neighborChunkIdx = face_data["attribute"]
                                    
                                    ninf.write(struct.pack("<H", primitiveIndex))
                                    ninf.write(struct.pack("<H", neighborChunkIdx))
                            
                            end_chunk(attr, ninf)
                    
                    end_chunk(rf, attr)
                bpy.data.materials.remove(defaultMaterial)

            if not EXPORT_SKEL or not EXPORT_KIN:
                rf.write('INFL'.encode('utf-8'))
                with io.BytesIO() as infl:
                    chunk_ver(infl, 100)

                    #NumBones
                    infl.write(struct.pack("<I", len(bones)))
                    #Bones
                    for key in bones:
                        bonegroup = bones[key]
                        bone = bonegroup["srcBone"]
                        chunkinfl = bonegroup["infl"] # per chunk influences

                        #Name
                        bone_name = bone.name
                        if not bone_name.startswith("b.r."):
                            bone_name = "b.r." + bone_name
                        jet_str(infl, bone_name)

                        #Parent
                        if bone.parent != None:
                            parent_name = bone.parent.name
                            if not parent_name.startswith("b.r."):
                                parent_name = "b.r." + parent_name
                            jet_str(infl, parent_name)
                        else:
                            infl.write(struct.pack("<I", 0))


                        #boneMat = bone.matrix_local
                        loc, rot, scale = bonegroup["matrix"].decompose()

                        #rot = mathutils.Quaternion()

                        #LocalPosition
                        #infl.write(struct.pack("<fff", bone.head[0], bone.head[1], bone.head[2]))
                        infl.write(struct.pack("<fff", loc[0], loc[1], loc[2]))
                        print("bone " + bone.name + " location: " + str(loc[0]) + " " + str(loc[1]) + " " + str(loc[2]))
                        #infl.write(struct.pack("<fff", 0.0, 0.0, 5.0))
                        #LocalOrientation
                        print("bone " + bone.name + " rotation: " + str(rot.x) + " " + str(rot.y) + " " + str(rot.z) + " " + str(rot.w))

                        rotationMat = rot.to_matrix().transposed()
                        #rotationMat = rot.to_matrix()
                        infl.write(struct.pack("<fffffffff", *rotationMat[0], *rotationMat[1], *rotationMat[2]))

                        necessary_infl = []
                        for influencelist in chunkinfl:
                            #having this breaks stuff
                            #if len(influencelist) > 0:
                            necessary_infl.append(influencelist)

                        #NumInfluences
                        infl.write(struct.pack("<I", len(necessary_infl)))
                        #Influences
                        for i, influencelist in enumerate(necessary_infl):
                            #ChunkIndex
                            infl.write(struct.pack("<I", i))
                            #NumVertices
                            infl.write(struct.pack("<I", len(influencelist)))
                            for influence in influencelist:
                                #Index
                                infl.write(struct.pack("<I", influence[0]))
                                #Weight
                                infl.write(struct.pack("<f", influence[1]))
                                #Position
                                vertpos = influence[2]
                                infl.write(struct.pack("<fff", vertpos[0], vertpos[1], vertpos[2]))
                    end_chunk(rf, infl)
            else:
                rf.write('SKEL'.encode('utf-8'))
                with io.BytesIO() as skel:
                    chunk_ver(skel, 100)
                    if root_bone is not None:
                        recursive_writebone_skel(skel, root_bone, active_armature, EXPORT_GLOBAL_MATRIX, EXPORT_ALL_BONES)
                    end_chunk(rf, skel)

            #AttachmentInfo
            if len(attachments) > 0:
                rf.write('ATCH'.encode('utf-8'))
                with io.BytesIO() as atch:
                    chunk_ver(atch, 100)
                    #NumAttachments
                    atch.write(struct.pack("<I", len(attachments)))
                    #Attachments
                    for att in attachments:

                        att_name = att.name

                        att_parent_name = ""
                        if att.parent is not None and "b.r." in att.parent.name:
                            att_parent_name = att.parent.name
                        elif att.parent_bone is not None and "b.r." in att.parent_bone:
                            att_parent_name = att.parent_bone
                        
                        #attachment parent bones
                        if att.parent is not None:
                            if(not "/" in att_name):
                                att_name = "a." + att_parent_name[2:] + "/" + att_name
                            
                        #Name
                        jet_str(atch, att_name)

                        attMat = EXPORT_GLOBAL_MATRIX @ att.matrix_world
                        loc, rot, scale = attMat.decompose()
                        rotationMat = rot.to_matrix().transposed()
                        #Orientation
                        atch.write(struct.pack("<fffffffff", *rotationMat[0], *rotationMat[1], *rotationMat[2]))
                        #Position
                        atch.write(struct.pack("<fff", loc[0], loc[1], loc[2]))

                    end_chunk(rf, atch)


                #me.transform(EXPORT_GLOBAL_MATRIX @ ob_mat)

            #with io.BytesIO() as attr:

            #for i, ob_main in enumerate(objects):
            end_chunk(f, rf)

        #fw('IDXM'.encode('utf-8'))
    #copy images?
    io_utils.path_reference_copy(copy_set)
    print("done")




def _write(self, context, filepath,
           EXPORT_APPLY_MODIFIERS,
           EXPORT_CURVES,
           EXPORT_TEXTURETXT,
           EXPORT_CONVERT_TGA,
           EXPORT_TANGENTS,
           EXPORT_BOUNDS,
           EXPORT_VERTEX_COLORS,
           EXPORT_NEIGHBOR_INFO,
           EXPORT_WIDE_STRINGS,
           EXPORT_SUBSURF_AMBIENT,
           EXPORT_CUSTOM_PROPERTIES,
           EXPORT_KIN,
           EXPORT_BLENDER_FRAMERATE,
           EXPORT_SKEL,
           EXPORT_ANIM_SCALE,
           EXPORT_ANIM_RELATIVE_POSITIONING,
           EXPORT_ALL_BONES,
           EXPORT_ANIM_NLA,
           EXPORT_ANIM_EVENTS,
           EXPORT_EXPLICIT_VERSIONING,
           EXPORT_INFO_VERSION,
           EXPORT_MATL_VERSION,
           EXPORT_GEOM_VERSION,
           EXPORT_SEL_ONLY,
           EXPORT_GLOBAL_MATRIX,
           EXPORT_PATH_MODE,
           ):
    
    global GLOBAL_WIDE_STRINGS
    GLOBAL_WIDE_STRINGS = EXPORT_WIDE_STRINGS

    base_name, ext = os.path.splitext(filepath)
    context_name = [base_name, '', '', ext]  # Base name, scene name, frame number, extension

    scene = context.scene
    scene.frame_set(0)

    #depsgraph = context.evaluated_depsgraph_get()

    # Exit edit mode
    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode='OBJECT')

    if EXPORT_SEL_ONLY:
        objects = context.selected_objects
    else:
        objects = scene.objects
    #objects = scene.objects

    #orig_frame = scene.frame_current
    full_path = ''.join(context_name)
        # EXPORT THE FILE.
    write_file(self, full_path, objects, scene,
               EXPORT_APPLY_MODIFIERS,
               EXPORT_CURVES,
               EXPORT_TEXTURETXT,
               EXPORT_CONVERT_TGA,
               EXPORT_TANGENTS,
               EXPORT_BOUNDS,
               EXPORT_VERTEX_COLORS,
               EXPORT_NEIGHBOR_INFO,
               EXPORT_SUBSURF_AMBIENT,
               EXPORT_CUSTOM_PROPERTIES,
               EXPORT_KIN,
               EXPORT_BLENDER_FRAMERATE,
               EXPORT_SKEL,
               EXPORT_ANIM_SCALE,
               EXPORT_ANIM_RELATIVE_POSITIONING,
               EXPORT_ALL_BONES,
               EXPORT_ANIM_NLA,
               EXPORT_ANIM_EVENTS,
               EXPORT_EXPLICIT_VERSIONING,
               EXPORT_INFO_VERSION,
               EXPORT_MATL_VERSION,
               EXPORT_GEOM_VERSION,
               EXPORT_SEL_ONLY,
               EXPORT_GLOBAL_MATRIX,
               EXPORT_PATH_MODE,
               #progress,
               )



def save(self, context,
         filepath,
         *,
         use_selection=False,
         use_mesh_modifiers=True,
         export_curves=False,
         use_texturetxt=True,
         convert_tga=False,
         export_tangents=True,
         export_bounds=True,
         export_vertex_colors=False,
         export_neighbor_info=False,
         use_wide_strings=False,
         subsurf_ambient=False,
         mat_custom_properties=False,
         use_kin=True,
         use_blender_framerate=False,
         use_skel=False,
         export_anim_scale=False,
         use_relative_positioning=False,
         export_all_bones=False,
         use_nla=False,
         export_events=True,
         use_explicit_versioning=False,
         info_version=None,
         matl_version=None,
         geom_version=None,
         global_matrix=None,
         path_mode='AUTO'
         ):

    _write(self, context, filepath,
           EXPORT_APPLY_MODIFIERS=use_mesh_modifiers,
           EXPORT_CURVES=export_curves,
           EXPORT_TEXTURETXT=use_texturetxt,
           EXPORT_CONVERT_TGA=convert_tga,
           EXPORT_TANGENTS=export_tangents,
           EXPORT_BOUNDS=export_bounds,
           EXPORT_VERTEX_COLORS=export_vertex_colors,
           EXPORT_NEIGHBOR_INFO=export_neighbor_info,
           EXPORT_WIDE_STRINGS=use_wide_strings,
           EXPORT_SUBSURF_AMBIENT=subsurf_ambient,
           EXPORT_CUSTOM_PROPERTIES=mat_custom_properties,
           EXPORT_KIN=use_kin,
           EXPORT_BLENDER_FRAMERATE=use_blender_framerate,
           EXPORT_SKEL=use_skel,
           EXPORT_ANIM_SCALE=export_anim_scale,
           EXPORT_ANIM_RELATIVE_POSITIONING=use_relative_positioning,
           EXPORT_ALL_BONES=export_all_bones,
           EXPORT_ANIM_NLA=use_nla,
           EXPORT_ANIM_EVENTS=export_events,
           EXPORT_EXPLICIT_VERSIONING=use_explicit_versioning,
           EXPORT_INFO_VERSION=info_version,
           EXPORT_MATL_VERSION=matl_version,
           EXPORT_GEOM_VERSION=geom_version,
           EXPORT_SEL_ONLY=use_selection,
           EXPORT_GLOBAL_MATRIX=global_matrix,
           EXPORT_PATH_MODE=path_mode,
           )

    return {'FINISHED'}
