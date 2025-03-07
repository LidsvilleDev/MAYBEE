import bpy
from bpy_extras.io_utils import ExportHelper
from bpy.props import *
from bpy.utils import unregister_class
from .yabee_libs import egg_writer

bl_info = {
    "name": "Panda3D Egg Exporter (MAYBEE)",
    "blender": (2, 80, 0),
    "version": (2, 2, 0),
    "location": "File > Import-Export",
    "description": ("Export to Panda3D EGG: meshes, uvs, materials, textures, "
                    "armatures, animation and curves"),
    # "wiki_url": "http://www.panda3d.org/forums/viewtopic.php?t=11441",
    "category": "Import-Export"
}


# --------------- Properties --------------------


class EGGBakeProperty(bpy.types.PropertyGroup):
    """ Texture baker settings """
    res_x: IntProperty(name = "Res. X", default = 512)
    res_y: IntProperty(name = "Res. Y", default = 512)
    export: BoolProperty(default = False)

    def draw(self, row, name):
        row.prop(self, "res_x")
        row.prop(self, "res_y")
        row.prop(self, "export")
        row.label(text = name)


class EGGAnimationProperty(bpy.types.PropertyGroup):
    """ One animation record """
    name: StringProperty(name = "Name", default = "Unknown")
    from_frame: IntProperty(name = "From", default = 1)
    to_frame: IntProperty(name = "To", default = 2)
    fps: IntProperty(name = "FPS", default = 24)

    def __get_idx(self):
        return list(bpy.context.scene.yabee_settings.opt_anim_list.anim_collection).index(self)

    index = property(__get_idx)


class EGGAnimList(bpy.types.PropertyGroup):
    """ Animations list settings """
    active_index: IntProperty()
    anim_collection: CollectionProperty(type = EGGAnimationProperty)

    def get_anim_dict(self):
        anim_dict = {}
        for anim in self.anim_collection:
            anim_dict[anim.name] = (anim.from_frame, anim.to_frame, anim.fps)
        return anim_dict


class YABEEProperty(bpy.types.PropertyGroup):
    """ Main YABEE class for store settings """
    opt_tex_proc: StringProperty(
        name = "Tex. processing",
        description = "Export all textures as MODULATE or bake texture layers",
        default = 'BAKE',
    )

    opt_bake_diffuse: PointerProperty(type = EGGBakeProperty)
    opt_bake_normal: PointerProperty(type = EGGBakeProperty)
    opt_bake_gloss: PointerProperty(type = EGGBakeProperty)
    opt_bake_glow: PointerProperty(type = EGGBakeProperty)
    opt_bake_AO: PointerProperty(type = EGGBakeProperty)
    opt_bake_shadow: PointerProperty(type = EGGBakeProperty)

    opt_tbs_proc: EnumProperty(
        name = "TBS generation",
        description = "Export all textures as MODULATE or bake texture layers",
        items = (
            ('PANDA', "Panda", "Use egg-trans to calculate TBS (Need installed Panda3D)."),
            ('BLENDER', "Blender", "Use Blender to calculate TBS"),
            ('NO', "No", "Do not generate TBS.")
        ),
        default = 'NO',
    )

    opt_export_uv_as_texture: BoolProperty(
        name = "UV as texture",
        description = "export uv image as texture",
        default = False,
    )

    opt_copy_tex_files: BoolProperty(
        name = "Copy texture files",
        description = "Copy texture files together with EGG",
        default = True,
    )

    opt_anims_from_actions: BoolProperty(
        name = "All actions as animations",
        description = "Export an animation for every Action",
        default = False,
    )

    opt_separate_anim_files: BoolProperty(
        name = "Separate animation files",
        description = "Write an animation data into the separate files",
        default = True,
    )

    opt_anim_only: BoolProperty(
        name = "Animation only",
        description = "Write only animation data",
        default = False,
    )

    opt_tex_path: StringProperty(
        name = "Tex. path",
        description = "Path for the copied textures. Relative to the main EGG file dir",
        default = './tex',
    )

    opt_merge_actor: BoolProperty(
        name = "Merge actor",
        description = "Merge meshes, armatured by single Armature",
        default = False,
    )

    opt_apply_modifiers: BoolProperty(
        name = "Apply modifiers",
        description = "Apply modifiers on exported objects (except Armature)",
        default = True,
    )

    opt_pview: BoolProperty(
        name = "Pview",
        description = "Run pview after exporting",
        default = False,
    )

    opt_use_loop_normals: BoolProperty(
        name = "Use custom vertex normals",
        description = "Use loop normals created by applying 'Normal Edit' Modifier as vertex normals.",
        default = False,
    )

    opt_export_pbs: BoolProperty(
        name = "Export PBS",
        description = "Export Physically Based Properties, requires the BAM Exporter",
        default = False
    )

    opt_force_export_vertex_colors: BoolProperty(
        name = "Force export vertex colors",
        description = "when False, writes only vertex color if polygon material is using it ",
        default = False,
    )

    opt_anim_list: PointerProperty(type = EGGAnimList)

    first_run: BoolProperty(default = True)

    def draw(self, layout):
        row = layout.row()
        row.operator("export.yabee_reset_defaults", icon = "FILE_REFRESH", text = "Reset to defaults")
        row.operator("export.yabee_help", icon = "URL", text = "Help")

        layout.row().label(text = 'Animation:')
        layout.row().prop(self, 'opt_anims_from_actions')
        if not self.opt_anims_from_actions:
            row = layout.row()
            row.template_list(
                "UI_UL_list",
                "anim_collection",
                self.opt_anim_list,
                "anim_collection",
                self.opt_anim_list,
                "active_index",
                rows = 2
            )
            col = row.column(align = True)
            col.operator("export.egg_anim_add", icon = 'ZOOM_IN', text = "")
            col.operator("export.egg_anim_remove", icon = 'ZOOM_OUT', text = "")
            sett = self.opt_anim_list
            if len(sett.anim_collection):
                p = sett.anim_collection[sett.active_index]
                layout.row().prop(p, 'name')
                row = layout.row(align = True)
                row.prop(p, 'from_frame')
                row.prop(p, 'to_frame')
                row.prop(p, 'fps')

        layout.separator()

        layout.row().label(text = 'Options:')
        layout.row().prop(self, 'opt_anim_only')
        layout.row().prop(self, 'opt_separate_anim_files')
        if not self.opt_anim_only:
            layout.row().prop(self, 'opt_tbs_proc')

            # Hide Texture Baking dialog until Texture Baking will be reimplemented
            """box = layout.box()
            box.row().prop(self, 'opt_tex_proc')
            if self.opt_tex_proc == 'BAKE':
                self.opt_bake_diffuse.draw(box.row(align=True), "Diffuse")
                self.opt_bake_normal.draw(box.row(align=True), "Normal")
                self.opt_bake_gloss.draw(box.row(align=True), "Gloss")
                self.opt_bake_glow.draw(box.row(align=True), "Glow")
            if self.opt_tex_proc != 'RAW':
                self.opt_bake_AO.draw(box.row(align=True), "AO")
                self.opt_bake_shadow.draw(box.row(align=True), "Shadow")"""

            if self.opt_copy_tex_files or self.opt_tex_proc == 'BAKE':
                box = layout.box()
                box.row().prop(self, 'opt_tex_path')
            else:
                layout.row().prop(self, 'opt_copy_tex_files')
            layout.row().prop(self, 'opt_merge_actor')
            layout.row().prop(self, 'opt_apply_modifiers')
            layout.row().prop(self, 'opt_pview')
            layout.row().prop(self, 'opt_use_loop_normals')

            layout.row().prop(self, 'opt_export_pbs')
            layout.row().prop(self, 'opt_force_export_vertex_colors')

    def get_bake_dict(self):
        texture_bake_dict = {}
        options = (
            (self.opt_bake_diffuse, 'diffuse'),
            (self.opt_bake_normal, 'normal'),
            (self.opt_bake_gloss, 'gloss'),
            (self.opt_bake_glow, 'glow'),
            (self.opt_bake_AO, 'AO'),
            (self.opt_bake_shadow, 'shadow')
        )
        for opt, texture_type in options:
            if self.opt_tex_proc == 'SIMPLE':
                if texture_type in ('AO', 'shadow'):
                    texture_bake_dict[texture_type] = (opt.res_x, opt.res_y, opt.export)
                else:
                    texture_bake_dict[texture_type] = (opt.res_x, opt.res_y, False)
            else:
                texture_bake_dict[texture_type] = (opt.res_x, opt.res_y, opt.export)
        return texture_bake_dict

    def check_warns(self, context):
        warns = []
        if len(context.selected_objects) == 0:
            warns.append('Nothing to export. Please, select "Mesh", \n' + \
                         '"Armature" or "Curve" objects.')
        for name, param in self.opt_anim_list.get_anim_dict().items():
            if param[0] == param[1]:
                warns.append(('Animation "%s" has same "from" and "to" frames\n' +
                              'Keep in mind that "To frame" value is exclusive.\n' +
                              'It means that in this case your animation contains\n' +
                              'zero of frames. YABEE will automatically add one frame\n' +
                              'to the "to" value of "%s" animation.') % (name, name))

        return warns

    def reset_defaults(self):
        self.opt_tex_proc = 'BAKE'
        self.opt_tbs_proc = 'NO'
        self.opt_bake_diffuse.export = True
        self.opt_bake_diffuse.res_x, self.opt_bake_diffuse.res_y = 512, 512
        self.opt_bake_normal.export = False
        self.opt_bake_normal.res_x, self.opt_bake_normal.res_y = 512, 512
        self.opt_bake_gloss.export = False
        self.opt_bake_gloss.res_x, self.opt_bake_gloss.res_y = 512, 512
        self.opt_bake_glow.export = False
        self.opt_bake_glow.res_x, self.opt_bake_glow.res_y = 512, 512
        self.opt_bake_AO.export = False
        self.opt_bake_AO.res_x, self.opt_bake_AO.res_y = 512, 512
        self.opt_bake_shadow.export = False
        self.opt_bake_shadow.res_x, self.opt_bake_shadow.res_y = 512, 512
        self.opt_export_uv_as_texture = False
        self.opt_copy_tex_files = True
        self.opt_separate_anim_files = True
        self.opt_anim_only = False
        self.opt_tex_path = './tex'
        self.opt_merge_actor = True
        self.opt_apply_modifiers = True
        self.opt_pview = False
        self.opt_use_loop_normals = False
        self.opt_export_pbs = False
        self.opt_force_export_vertex_colors = False
        while self.opt_anim_list.anim_collection[:]:
            bpy.ops.export.egg_anim_remove('INVOKE_DEFAULT')
        self.first_run = False


# ------------------ Operators ----------------------------------
class YABEEHelp(bpy.types.Operator):
    bl_idname = "export.yabee_help"
    bl_label = "YABEE Help."

    def execute(self, context):
        bpy.ops.wm.url_open("INVOKE_DEFAULT", url = "http://www.panda3d.org/forums/viewtopic.php?t=11441")
        return {"FINISHED"}


class WarnDialog(bpy.types.Operator):
    """ Warning messages operator """
    bl_idname = "export.yabee_warnings"
    bl_label = "YABEE Warnings."

    def draw(self, context):
        warns = context.scene.yabee_settings.check_warns(context)
        for warn in warns:
            for n, line in enumerate(warn.splitlines()):
                if n == 0:
                    self.layout.row().label(line, icon = "ERROR")
                else:
                    self.layout.row().label('    ' + line, icon = "NONE")

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)


class ResetDefault(bpy.types.Operator):
    """ Reset YABEE settings to default operator """
    bl_idname = "export.yabee_reset_defaults"
    bl_label = "YABEE reset default settings"

    def execute(self, context):
        context.scene.yabee_settings.reset_defaults()
        return {'FINISHED'}


class AddAnim(bpy.types.Operator):
    """ Add animation record operator """
    bl_idname = "export.egg_anim_add"
    bl_label = "Add EGG animation"

    def execute(self, context):
        prop = context.scene.yabee_settings.opt_anim_list.anim_collection.add()
        prop.name = 'Anim' + str(prop.index)
        return {'FINISHED'}


class RemoveAnim(bpy.types.Operator):
    """ Remove active animation record operator """
    bl_idname = "export.egg_anim_remove"
    bl_label = "Remove EGG animation"

    def execute(self, context):
        anim_settngs = context.scene.yabee_settings.opt_anim_list
        anim_settngs.anim_collection.remove(anim_settngs.active_index)
        if len(anim_settngs.anim_collection):
            if anim_settngs.active_index not in [p.index for p in anim_settngs.anim_collection]:
                anim_settngs.active_index = anim_settngs.anim_collection[-1].index
        return {'FINISHED'}


class ExportPanda3DEGG(bpy.types.Operator, ExportHelper):
    """ Export selected to the Panda3D EGG format """
    bl_idname = "export.panda3d_egg"
    bl_label = "Export to Panda3D EGG"

    # ExportHelper mixin class uses this
    filename_ext = ".egg"

    filter_glob: StringProperty(
        default = "*.egg",
        options = {'HIDDEN'},
    )

    filepath: bpy.props.StringProperty(subtype = "FILE_PATH")

    def execute(self, context):
        import importlib
        importlib.reload(egg_writer)
        sett = context.scene.yabee_settings
        errors = egg_writer.write_out(
            self.filepath,
            sett.opt_anim_list.get_anim_dict(),
            sett.opt_anims_from_actions,
            sett.opt_export_uv_as_texture,
            sett.opt_separate_anim_files,
            sett.opt_anim_only,
            sett.opt_copy_tex_files,
            sett.opt_tex_path,
            sett.opt_tbs_proc,
            sett.opt_tex_proc,
            sett.get_bake_dict(),
            sett.opt_merge_actor,
            sett.opt_apply_modifiers,
            sett.opt_pview,
            sett.opt_use_loop_normals,
            sett.opt_export_pbs,
            sett.opt_force_export_vertex_colors
        )

        if errors:
            rep_msg = ''
            if 'ERR_UNEXPECTED' in errors:
                rep_msg += 'Unexpected error during export! See console for traceback.\n'
            if 'ERR_MK_HIERARCHY' in errors:
                rep_msg += 'Error while creating hierarchy. Check parent objects and armatures.'
            if 'ERR_MK_OBJ' in errors:
                rep_msg += 'Unexpected error while creating object. See console for traceback.'
            self.report({'ERROR'}, rep_msg)
            return {'CANCELLED'}
        return {'FINISHED'}

    def invoke(self, context, evt):
        if context.scene.yabee_settings.first_run:
            context.scene.yabee_settings.reset_defaults()
        return ExportHelper.invoke(self, context, evt)

    def draw(self, context):
        warns = context.scene.yabee_settings.check_warns(context)
        if warns:
            self.layout.row().operator('export.yabee_warnings', icon = 'ERROR', text = 'Warning!')
        context.scene.yabee_settings.draw(self.layout)


def menu_func_export(self, context):
    self.layout.operator(ExportPanda3DEGG.bl_idname, text = "Panda3D (.egg)")


classes = (
    EGGBakeProperty,
    EGGAnimationProperty,
    EGGAnimList,
    YABEEProperty,
    YABEEHelp,
    WarnDialog,
    ResetDefault,
    AddAnim,
    RemoveAnim,
    ExportPanda3DEGG
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    # Good or bad, but I'll store settings in the scene
    bpy.types.Scene.yabee_settings = PointerProperty(type = YABEEProperty)
    # Hack again. I use custom property to be able to get basic object name in the copy of the scene.
    bpy.types.Object.yabee_name = StringProperty(name = "YABEE_Name", default = "Unknown")
    bpy.types.Mesh.yabee_name = StringProperty(name = "YABEE_Name", default = "Unknown")
    bpy.types.Material.yabee_name = StringProperty(name = "YABEE_Name", default = "Unknown")
    # Can't directly add property to MaterialTextureSlot ("this type doesn't support IDProperties"),
    # so this stores original names for each embedded texture slot
    # in a string like: "Texture\1Texture2\1..." (see NAME_SEPARATOR)
    bpy.types.Material.yabee_texture_slots = StringProperty(name = "YABEE_Texture_Slots", default = "Unknown")
    bpy.types.Texture.yabee_name = StringProperty(name = "YABEE_Name", default = "Unknown")
    bpy.types.Armature.yabee_name = StringProperty(name = "YABEE_Name", default = "Unknown")
    bpy.types.Curve.yabee_name = StringProperty(name = "YABEE_Name", default = "Unknown")
    # bpy.types.ShapeKey.yabee_name = StringProperty(name="YABEE_Name", default="Unknown")
    bpy.types.Key.yabee_name = StringProperty(name = "YABEE_Name", default = "Unknown")
    bpy.types.Image.yabee_name = StringProperty(name = "YABEE_Name", default = "Unknown")
    bpy.types.Bone.yabee_name = StringProperty(name = "YABEE_Name", default = "Unknown")
    bpy.types.PoseBone.yabee_name = StringProperty(name = "YABEE_Name", default = "Unknown")

    if bpy.app.version < (2, 80):
        bpy.types.INFO_MT_file_export.append(menu_func_export)
    else:
        bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    # Add link for export function to use in another addon
    __builtins__['p3d_egg_export'] = egg_writer.write_out


def unregister():
    # https://blender.stackexchange.com/questions/123611/registering-classes-in-blender-2-8
    # https://developer.blender.org/docs/release_notes/2.80/python_api/addons/
    if bpy.app.version < (2, 80):
        bpy.utils.unregister_module(__name__)
        bpy.types.INFO_MT_file_export.remove(menu_func_export)
    else:
        for cls in reversed(classes):
            unregister_class(cls)
            bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)

    del (__builtins__['p3d_egg_export'])


if __name__ == "__main__":
    register()

    # test call
    # bpy.ops.export.panda3d_egg('INVOKE_DEFAULT')
