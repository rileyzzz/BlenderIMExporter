
# Check if this add-on is being reloaded
#if "bpy" in locals():
#    # reloading .py files
#    import importlib
#    # from . blendzmq_props import ZMQSocketProperties
#    # importlib.reload(ZMQSocketProperties)
#    # from . blendzmq_panel import BLENDZMQ_PT_zmqConnector
#    # importlib.reload(BLENDZMQ_PT_zmqConnector)
#    print("reloading .im")
#    from . import export_im  # addon_props.py (properties are created here)
#    importlib.reload(export_im)  # does this file need a def register() / def unregister() for the classes inside?
## or if this is the first load of this add-on
#else:
#    print("importing .py files")
#    import bpy
#    from . import export_im


bl_info = {
    "name": "Export Indexed Mesh Format (.im)",
    "author": "Riley Lemmler",
    "version": (1, 3, 6),
    "blender": (2, 81, 6),
    "location": "File > Export",
    "description": "Export Trainz indexed meshes",
    "warning": "",
    "doc_url": "",
    "support": 'COMMUNITY',
    "category": "Import-Export",
}

if "bpy" in locals():
    import importlib
    print("reload im local")
    if "export_im" in locals():
        print("lib reload")
        importlib.reload(export_im)
import bpy

from bpy.props import (
        BoolProperty,
        FloatProperty,
        StringProperty,
        EnumProperty,
        )
from bpy_extras.io_utils import (
        ExportHelper,
        orientation_helper,
        path_reference_mode,
        axis_conversion,
        )


@orientation_helper(axis_forward='Y', axis_up='Z')
class ExportIM(bpy.types.Operator, ExportHelper):
    """Save an Indexed Mesh File"""

    bl_idname = "export_scene.im"
    bl_label = 'Export IM'
    bl_options = {'PRESET'}

    filename_ext = ".im"
    filter_glob: StringProperty(
            default="*.im",
            options={'HIDDEN'},
            )

    # context group
    use_selection: BoolProperty(
            name="Selection Only",
            description="Export selected objects only",
            default=False,
            )

    use_mesh_modifiers: BoolProperty(
            name="Apply Modifiers",
            description="Apply modifiers",
            default=True,
            )
    
    export_curves: BoolProperty(
            name="Export Curves",
            description="Export curves as line primitives (broken in TANE+)",
            default=False,
            )

    use_texturetxt: BoolProperty(
            name="Create texture.txt",
            description="Create a texture.txt metadata file for each used texture",
            default=True,
            )

    export_tangents: BoolProperty(
            name="Tangents",
            description="Export tangent data",
            default=True,
            )

    export_bounds: BoolProperty(
            name="Bounding Box",
            description="Export bounding box data",
            default=True,
            )

    export_neighbor_info: BoolProperty(
            name="Adjacency Data",
            description="Export triangle adjacency information (used by progressive meshes). Requires triangulated geometry. This can be slow",
            default=False,
            )

    use_wide_strings: BoolProperty(
            name="Force Wide Strings",
            description="Export all .im/.kin strings with wide 16 bit formatting instead of 8 bit. This may protect against some ripping software",
            default=False,
            )

    subsurf_ambient: BoolProperty(
            name="Use Subsurface Color as Ambient",
            description="Export the Principled BSDF Subsurface Color as the material ambient",
            default=False,
            )
    
    mat_custom_properties: BoolProperty(
            name="Material Properties",
            description="Exports the user-defined custom property data of materials",
            default=False,
            )

    use_kin: BoolProperty(
            name="Export Animation",
            description="Create a .kin animation file",
            default=True,
            )

    use_skel: BoolProperty(
            name="Use SKEL Hierarchy",
            description="Use a SKEL hierarchy instead of INFL to store bone data. Will break skinning, but can reduce file size",
            default=False,
            )

    export_anim_scale: BoolProperty(
            name="Export Scaling Data",
            description="Export additional scaling data in animations",
            default=False,
            )

    use_relative_positioning: BoolProperty(
            name="Use Relative Positioning",
            description="Use relative positioning in animation data. (Only supported in TANE+)",
            default=False,
            )

    global_scale: FloatProperty(
            name="Scale",
            min=0.01, max=1000.0,
            default=1.0,
            )

    path_mode: path_reference_mode

    check_extension = True

    def execute(self, context):
        from . import export_im

        from mathutils import Matrix
        keywords = self.as_keywords(ignore=("axis_forward",
                                            "axis_up",
                                            "global_scale",
                                            "check_existing",
                                            "filter_glob",
                                            ))

        global_matrix = (Matrix.Scale(self.global_scale, 4) @
                         axis_conversion(to_forward=self.axis_forward,
                                         to_up=self.axis_up,
                                         ).to_4x4())

        keywords["global_matrix"] = global_matrix
        return export_im.save(self, context, **keywords)

    def draw(self, context):
        pass


class IM_PT_export_include(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Include"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "EXPORT_SCENE_OT_im"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        col = layout.column(heading="Limit to", align = True)
        col.prop(operator, 'use_selection')

        #layout.separator()

        col = layout.column(heading = "Data", align = True)

        #col.prop(operator, 'export_tangents')
        col.prop(operator, 'export_bounds')
        col.prop(operator, 'export_neighbor_info')
        col.prop(operator, 'use_wide_strings')
        col.prop(operator, 'subsurf_ambient')
        col.prop(operator, 'mat_custom_properties')


class IM_PT_export_geometry(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Geometry"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "EXPORT_SCENE_OT_im"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, 'use_mesh_modifiers')
        layout.prop(operator, 'export_tangents')
        layout.prop(operator, 'export_curves')
        layout.prop(operator, 'global_scale')
        layout.prop(operator, 'path_mode')
        layout.prop(operator, 'use_texturetxt')
        #layout.prop(operator, 'use_triangles')

class IM_PT_export_animation(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Animation"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "EXPORT_SCENE_OT_im"

    def draw_header(self, context):
        sfile = context.space_data
        operator = sfile.active_operator

        self.layout.prop(operator, 'use_kin', text="")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.enabled = operator.use_kin
        layout.prop(operator, 'use_skel')
        layout.prop(operator, 'export_anim_scale')
        layout.prop(operator, 'use_relative_positioning')

def menu_func_export(self, context):
    self.layout.operator(ExportIM.bl_idname, text="Indexed Mesh (.im)")


classes = (
    ExportIM,
    IM_PT_export_include,
    IM_PT_export_geometry,
    IM_PT_export_animation
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)

    for cls in classes:
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
