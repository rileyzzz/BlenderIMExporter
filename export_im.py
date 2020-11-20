import os
import io
import struct
import bmesh
import bpy
import math
import mathutils
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
    
def jet_str(f, str):
    encoded_name = (str + '\0').encode('utf-8')
    f.write(struct.pack("<I", len(encoded_name)))
    f.write(encoded_name)

def texture_file(type, img_path, target_dir):
    basename = os.path.basename(img_path).lower()
    texturepath = target_dir + '\\' + os.path.splitext(basename)[0] + ".texture"
    txtpath = texturepath + ".txt"
    print("write to " + txtpath)
    with open(txtpath, "w") as f:
        f.write("Primary=" + basename + "\n")
        f.write("Alpha=" + basename + "\n")
        f.write("Tile=st" + "\n")
        if type is 8:
            f.write("NormalMapHint=normalmap")
    return texturepath
    
def chunk_ver(f, ver):
    f.write(struct.pack("<I", ver))

def end_chunk(f, chunk):
    f.write(struct.pack("<I", chunk.tell()))
    f.write(chunk.getbuffer())

def recursive_writebone(chnk, srcBone, bones_flat):
    bones_flat.append(srcBone)
    
    relevant_children = []
    for child in srcBone.children:
        if "b.r." in child.name:
            relevant_children.append(child)
    
    chnk.write('BONE'.encode('utf-8'))
    with io.BytesIO() as bone:
        chunk_ver(bone, 100)
        #BoneName
        jet_str(bone, srcBone.name)
        #NumChildren
        bone.write(struct.pack("<I", len(relevant_children)))
        #BoneList
        for child in relevant_children:
            recursive_writebone(bone, child, bones_flat)
        end_chunk(chnk, bone)
    
    
def write_kin(filepath, bones, armature, EXPORT_GLOBAL_MATRIX):
    print("Writing .kin to " + filepath)
    
    scene = bpy.context.scene
    NumFrames = scene.frame_end - scene.frame_start + 1
    
    #preprocess
    root_bone = None
    for key in bones:
        bonegroup = bones[key]
        bone = bonegroup[0]
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
                chunk_ver(info, 100)
                #FileName
                jet_str(info, os.path.basename(filepath).lower())
                #NumFrames
                info.write(struct.pack("<I", NumFrames))
                #FrameRate
                info.write(struct.pack("<I", 30))
                #MetricScale
                info.write(struct.pack("<f", 1.0))
                end_chunk(rf, info)
            
            #Events
            rf.write('EVNT'.encode('utf-8'))
            with io.BytesIO() as evnt:
                chunk_ver(evnt, 100)
                #NumEvents
                evnt.write(struct.pack("<I", 0))
                end_chunk(rf, evnt)
            
            bones_flat = []
            
            #Skeleton
            rf.write('SKEL'.encode('utf-8'))
            with io.BytesIO() as skel:
                chunk_ver(skel, 100)
                #SkeletonBlock
                recursive_writebone(skel, root_bone, bones_flat)
                #skel.write(struct.pack("<I", 0))
                end_chunk(rf, skel)
                
            posebones_flat = []
            for bone in bones_flat:
                print("bone " + bone.name)
                for posebone in armature.pose.bones:
                    if posebone.name == bone.name:
                        posebones_flat.append(posebone)
                        break
                    
            objbones_flat = []
            for obj in bones_flat:
                if hasattr(obj, 'type') and obj.type == 'EMPTY' or obj.type == 'LATTICE':
                    objbones_flat.append(obj)
                    
                #pose_bone = (b for b in armature.pose.bones if b.bone is bone)
                #posebones_flat.append(pose_bone)
            print("Found " + str(len(posebones_flat)) + "/" + str(len(armature.pose.bones)) + " pose bones")
            print("Found " + str(len(objbones_flat)) + " object bones")
            #FrameList
            for i in range(NumFrames):
                scene.frame_set(i)
                rf.write('FRAM'.encode('utf-8'))
                with io.BytesIO() as fram:
                    chunk_ver(fram, 100)
                    #FrameNum
                    fram.write(struct.pack("<I", i))
                    #BoneDataList
                    for pose_bone in posebones_flat:
                        #mat = pose_bone.matrix_basis
                        mat = EXPORT_GLOBAL_MATRIX @ armature.matrix_world @ pose_bone.matrix
                        position, rotation, scale = mat.decompose()
                        rotation = rotation.inverted()
                        #Position
                        fram.write(struct.pack("<fff", *position))
                        #Orientation
                        fram.write(struct.pack("<ffff", rotation.x, rotation.y, rotation.z, rotation.w))
                    
                    for obj_bone in objbones_flat:
                        #objMat = obj_bone.matrix_world
                        #if obj_bone.parent != None:
                            #objMat = obj_bone.parent.matrix_world.inverted() @ objMat
                        #objMat = EXPORT_GLOBAL_MATRIX @ objMat
                        objMat = EXPORT_GLOBAL_MATRIX @ obj_bone.matrix_world
                        position, rotation, scale = objMat.decompose()
                        rotation = rotation.inverted()
                        #Position
                        fram.write(struct.pack("<fff", *position))
                        #Orientation
                        fram.write(struct.pack("<ffff", rotation.x, rotation.y, rotation.z, rotation.w))
                    
                    end_chunk(rf, fram)
            
            end_chunk(f, rf)
    
    
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
    meshes = []
    hold_meshes = [] #prevent garbage collection of bmeshes
    for obj in objects:
        final = obj.evaluated_get(depsgraph)# if EXPORT_APPLY_MODIFIERS else ob.original
        
        try:
            me = final.to_mesh()
        except RuntimeError:
            me = None

        if me is None:
            continue
        if len(me.uv_layers) is 0:
            print("Object " + obj.name + " is missing UV coodinates! Skipping.")
            continue
        uv_layer = me.uv_layers.active.data[:]
        me.transform(EXPORT_GLOBAL_MATRIX @ obj.matrix_world)
        me.calc_normals_split() #unsure
        bm = bmesh.new()
        hold_meshes.append(bm)
        bm.from_mesh(me)
        bmesh.ops.triangulate(bm, faces=bm.faces)
        
        objectParent = None #empty and lattice parents
        if obj.parent != None:
            if "b.r." in obj.parent.name:
                objectParent = obj.parent
        
        
        #split_faces = []
        #idx2idxmap = {}
        print("Processing mesh...")

        vertgroups = obj.vertex_groups
        
        #split into materials
        materials = me.materials
        print("object contains " + str(len(materials)) + " materials")
        #split_matblocks = [None] * len(materials)
        split_matblocks = [[] for i in range(len(materials))]
        for face in bm.faces:
            split_matblocks[face.material_index].append(face)
        
        for i, srcobject in enumerate(split_matblocks):
            wasCopied = [None] * len(bm.verts)
            unique_verts = []
            indices = []
            normals = []
            face_normals = [] #[]
            
            area = 0.0
            for face in srcobject:
                area += face.calc_area()
                
                #split_faces.append(face)
                face_normals.append(face.normal.normalized())
                #face_normals.append([0.0, 0.0, 1.0])
                for loop in face.loops:
                    vert = loop.vert
                    if wasCopied[vert.index] is None:
                        wasCopied[vert.index] = len(unique_verts)
                        
                        influences = []
                        for group in vertgroups:
                            try:
                                weight = group.weight(vert.index)
                            except RuntimeError:
                                weight = 0.0
                            if weight != 0.0:
                                influences.append([group.name, weight])
                            
                        #for infl in influences:
                            #print("vert infl obj " + obj.name + " " + infl[0] + ": " + str(infl[1]))
                        unique_verts.append([vert.co[:], uv_layer[loop.index].uv[:], influences])
                        normals.append(vert.normal.normalized())
                        #normals.append([0.0, 0.0, 1.0])
                    indices.append(wasCopied[vert.index])
                    
                if len(unique_verts) > 65532:
                    #apply and update
                    #ret = bmesh.ops.split(bm, geom=split_faces)
                    #split_blocks.append(ret["geom"])
                    meshes.append([obj, materials[i],
                                   unique_verts.copy(),
                                   indices.copy(),
                                   normals.copy(),
                                   face_normals.copy(),
                                   area,
                                   uv_layer,
                                   objectParent])
                    
                    unique_verts.clear()
                    indices.clear()
                    normals.clear()
                    face_normals.clear()
                    area = 0.0
                    #split_faces.clear()
                    #idx2idxmap.clear()
                    wasCopied = [None] * len(bm.verts)
                    print("Block split.")
                    
            #Add remaining verts
            if len(unique_verts) > 0:
                meshes.append([obj, materials[i],
                               unique_verts.copy(),
                               indices.copy(),
                               normals.copy(),
                               face_normals.copy(),
                               area,
                               uv_layer,
                               objectParent])
        print("Complete.")

        #bm.free()
    
    active_armature = None
    bones = {}
    root_bone = None
    for ob in bpy.data.objects:
        if ob.type != 'ARMATURE':
            continue
        active_armature = ob
        break
    
    if active_armature is None:
        print("No armature in scene.")
        #EXPORT_KIN = False
    else:
        for bone in active_armature.data.bones:
            if "b.r." in bone.name:
                #bone, chunk influences
                bones[bone.name] = [bone, [[] for _ in range(len(meshes))]]
                if bone.parent == None:
                    root_bone = bone
    
    #legacy empty, lattice support
    for ob in bpy.data.objects:
        if "b.r." in ob.name:
            print("Found bone object " + ob.name)
            #ob.scale = [1.0, 1.0, 1.0]
            #bpy.context.view_layer.update()
            bones[ob.name] = [ob, [[] for _ in range(len(meshes))]]
            if ob.parent == None:
                root_bone = ob
    
    if EXPORT_KIN:
        write_kin(os.path.dirname(filepath) + "\\anim.kin", bones, active_armature, EXPORT_GLOBAL_MATRIX)
    
    #Attachment setup
    attachments = []
    for ob in bpy.data.objects:
        if ob.type == 'EMPTY' and 'a.' in ob.name:
            print("Attachment " + ob.name)
            attachments.append(ob)
    
    
    copy_set = set()
    with open(filepath, "wb") as f:
        #fw = f.write
        source_dir = os.path.dirname(bpy.data.filepath)
        dest_dir = os.path.dirname(filepath)
        path_mode = 'AUTO'
        
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
                #info.write(struct.pack("<ffff", objRotation.x, objRotation.y, objRotation.z, objRotation.w))
                info.write(struct.pack("<ffff", objRotation.w, objRotation.x, objRotation.y, objRotation.z))
                #NumAttributes
                info.write(struct.pack("<I", len(meshes)))
                #MaxInfluencePerVertex
                info.write(struct.pack("<I", 0))
                #MaxInfluencePerChunk
                info.write(struct.pack("<I", 0))
                end_chunk(rf, info)
            
            
            for i, entry in enumerate(meshes):
                
                obj = entry[0]
                #mesh = entry[1]
                #uv_layer = entry[2]
##                [obj, materials[i]
#                               unique_verts.copy(),
#                               indices.copy(),
#                               normals.copy(),
#                               face_normals.copy(),
#                               area,
#                               uv_layer]
                mat = entry[1]
                verts = entry[2]
                indices = entry[3]
                normals = entry[4]
                face_normals = entry[5]
                area = entry[6]
                uv_layer = entry[7]
                objParent = entry[8]
                #uv_layer = mesh.uv_layers.active.data
                #mesh_triangulate(mesh)
                #mat = obj.active_material
                
                defaultMaterial = bpy.data.materials.new(obj.name)
                if mat is None:
                    mat = defaultMaterial
       
                rf.write('CHNK'.encode('utf-8'))
                with io.BytesIO() as attr:
                    chunk_ver(attr, 100)
                    #Chunk ID
                    attr.write(struct.pack("<I", i))
                    attr.write('MATL'.encode('utf-8'))
                    with io.BytesIO() as matl:
                        chunk_ver(matl, 103)
                        #Name
                        jet_str(matl, mat.name)
                        #NumProperties
                        matl.write(struct.pack("<I", 0))
                        
                        #nodes
                        mat_wrap = node_shader_utils.PrincipledBSDFWrapper(mat)
                        
                        #TwoSided
                        matl.write(struct.pack("<I", int(not mat.use_backface_culling)))
                        #matl.write(struct.pack("<I", 0))
                        #Opacity
                        matl.write(struct.pack("<f", mat_wrap.alpha))
                        #Ambient
                        matl.write(struct.pack("<fff", mat_wrap.base_color[0],
                                                       mat_wrap.base_color[1],
                                                       mat_wrap.base_color[2]))
                        #Diffuse
                        matl.write(struct.pack("<fff", mat_wrap.base_color[0],
                                                       mat_wrap.base_color[1],
                                                       mat_wrap.base_color[2]))
                        #Specular
                        matl.write(struct.pack("<fff", mat_wrap.specular,
                                                       mat_wrap.specular,
                                                       mat_wrap.specular))
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
                        matl.write(struct.pack("<f", (1.0 - mat_wrap.roughness) * 128.0))
                        #Texture setup
                        #texCount = 0
                        textures = []
                        
                        image_source = [
                            None, #TEX_Ambient
                            "base_color_texture", #TEX_Diffuse
                            "specular_texture", #TEX_Specular
                            "roughness_texture", #TEX_Shine
                            "normalmap_texture" if mat.name.endswith(".m.tbumptex") else None, #TEX_Shinestrength
                            "emission_color_texture" if emission_strength != 0.0 else None, #TEX_Selfillum
                            "alpha_texture", #TEX_Opacity
                            None, #TEX_Filtercolor
                            "normalmap_texture", #TEX_Bump,
                            "metallic_texture", #TEX_Reflect,
                            None, #TEX_Refract,
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
                            filepath = io_utils.path_reference(image.filepath, source_dir, dest_dir,
                                                       path_mode, "", copy_set, image.library)
                            strength = 1.0
                            if entry is "normalmap_texture":
                                strength = 0.2 * mat_wrap.normalmap_strength
                            textures.append([type, texture_file(type, filepath, dest_dir), strength])
                        
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
                        chunk_ver(geom, 201)
                        #bm = bmesh.new()
                        #bm.from_mesh(mesh)
                        #bm = mesh
                        
                        
#                        verts = []
#                        indices = block_indices #[]
#                        normals = []
#                        facenormals = [] #[]
##                        for i, vert in enumerate(bm.verts):
##                            verts.append([vert.co, uv_layer[i].uv]) #vert.index
##                            normals.append(vert.normal)
##                        
##                        for face in bm.faces:
##                            for vert in face.verts:
##                                indices.append(vert.index)
##                            facenormals.append(face.normal)
#                        for vert in block_verts:
#                            verts.append([vert.co, uv_layer[vert.index].uv])
#                            normals.append(vert.normal)
#                        for face in block_faces:
#                            facenormals.append(face.normal)

                        #Flags
                        geom.write(struct.pack("<I", 4)) #GC_TRIANGLES
                        #UseTangents (201)
                        geom.write(struct.pack("<I", 0))
                        
                        #Area
                        #area = sum(face.calc_area() for face in bm.faces)
                        geom.write(struct.pack("<f", area))
                        #NumVerticies
                        geom.write(struct.pack("<I", len(verts)))
                        #NumPrimitives
                        geom.write(struct.pack("<I", len(indices) // 3))
                        #NumIndices
                        geom.write(struct.pack("<I", len(indices)))
                        #NumFaceNormals
                        geom.write(struct.pack("<I", len(face_normals)))
                        #MaxInfluence
                        geom.write(struct.pack("<I", 0)) #FIX FOR ANIMATION
                        
                        #Parent (201)
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
                                parentMat = EXPORT_GLOBAL_MATRIX @ objParent.matrix_world
                                co_vector = parentMat.inverted() @ co_vector
                                                       
                            geom.write(struct.pack("<fff", co_vector[0], co_vector[1], co_vector[2]))
                            geom.write(struct.pack("<ff", texcoord[0], 1.0 - texcoord[1]))
                            
                            #BoneTransform = None #identity?
                            for influence in influences:
                                name = influence[0]
                                weight = influence[1]
                                if name in bones:
                                    bonegroup = bones[name]
                                    bone = bonegroup[0]
                                    chunkinfl = bonegroup[1][i]

#                                    if BoneTransform == None:
#                                        BoneTransform = bone.matrix_local * weight
#                                    else:
#                                        BoneTransform += bone.matrix_local * weight
                                    
                                    boneMat = bone.matrix_local.inverted()
                                    chunkinfl.append([idx, weight, boneMat @ co_vector]) #boneMat @ co_vector
                                    
                            #if BoneTransform == None:
                                #BoneTransform = mathutils.Matrix.Identity()
                                
                            #BoneTransform = EXPORT_GLOBAL_MATRIX @ obj.matrix_world @ BoneTransform
                            
                            #inverse_vector = BoneTransform.inverted() @ co_vector
                            #inverse_vector = co_vector @ BoneTransform.inverted()
                            
                            #geom.write(struct.pack("<fff", inverse_vector[0], inverse_vector[1], inverse_vector[2]))
                            #geom.write(struct.pack("<ff", texcoord[0], 1.0 - texcoord[1]))
                            
                        #Indices
                        for idx in indices:
                            geom.write(struct.pack("<H", idx))
                        #VertexNormals
                        for normal in normals:
                            geom.write(struct.pack("<fff", normal[0], normal[1], normal[2]))
                        #FaceNormals
                        for normal in face_normals:
                            geom.write(struct.pack("<fff", normal[0], normal[1], normal[2]))
                            
                        bm.free()
                        
                        end_chunk(attr, geom)
                    end_chunk(rf, attr)
                bpy.data.materials.remove(defaultMaterial)

            
            rf.write('INFL'.encode('utf-8'))
            with io.BytesIO() as infl:
                chunk_ver(infl, 100)
                
                #NumBones
                infl.write(struct.pack("<I", len(bones)))
                #Bones
                for key in bones:
                    bonegroup = bones[key]
                    bone = bonegroup[0]
                    chunkinfl = bonegroup[1] # per chunk influences
                    
                    #Name
                    jet_str(infl, bone.name)
                    #Parent
                    if bone.parent != None:
                        jet_str(infl, bone.parent.name)
                    else:
                        infl.write(struct.pack("<I", 0))
                    
                    if not hasattr(bone, 'type'): #bone.type != 'EMPTY'
                        print("BONE TYPE")
                        if bone.parent == None:
                            boneMat = bone.matrix_local
                        else:
                            boneMat = bone.parent.matrix_local.inverted() @ bone.matrix_local
                        boneMat = EXPORT_GLOBAL_MATRIX @ active_armature.matrix_world @ boneMat
                    else:
                        print("NOT BONE TYPE")
                        #boneMat = bone.matrix_local
                        #boneMat = mathutils.Matrix.Identity(4)
                        if bone.parent == None:
                            print("no parent")
                            boneMat = bone.matrix_world
                        else:
                            print("bone " + bone.name + " parent " + bone.parent.name)
                            #boneMat = bone.parent.matrix_world.inverted() @ bone.matrix_world
                            boneMat = bone.matrix_parent_inverse @ bone.matrix_world
                        boneMat = EXPORT_GLOBAL_MATRIX @ boneMat

                    #boneMat = bone.matrix_local
                    loc, rot, scale = boneMat.decompose()
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
                
            #AttachmentInfo
            if len(attachments) > 0:
                rf.write('ATCH'.encode('utf-8'))
                with io.BytesIO() as atch:
                    chunk_ver(atch, 100)
                    #NumAttachments
                    atch.write(struct.pack("<I", len(attachments)))
                    #Attachments
                    for att in attachments:
                        #Name
                        jet_str(atch, att.name)
                        
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
