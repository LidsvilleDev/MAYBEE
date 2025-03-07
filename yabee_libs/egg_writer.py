from mathutils import *
from math import pi
# from .texture_processor import PbrTextures, TextureBaker
from .texture_processor import PbrTextures

from .utils import *
import sys
import subprocess
import importlib
from traceback import print_exc

lib_name = '.'.join(__name__.split('.')[:-1])
importlib.reload(sys.modules[lib_name + '.texture_processor'])
importlib.reload(sys.modules[lib_name + '.utils'])

FILE_PATH = None
ANIMATIONS = None
EXPORT_UV_IMAGE_AS_TEXTURE = None
COPY_TEX_FILES = None
TEX_PATH = None
SEPARATE_ANIM_FILE = None
ANIM_ONLY = None
CALC_TBS = None
TEXTURE_PROCESSOR = None
BAKE_LAYERS = None
MERGE_ACTOR_MESH = None
APPLY_MOD = None
PVIEW = True
EXPORT_PBS = False
FORCE_EXPORT_VERTEX_COLORS = False
USE_LOOP_NORMALS = False
STRF = lambda x: '%.6f' % x
USED_MATERIALS = set()  # type: set
USED_TEXTURES = {}  # type: dict

# const used to pack string array into StringProperty
NAME_SEPARATOR = "\1"


class Group:
    """
    Representation of the EGG <Group> hierarchy structure as the linked list "one to many".
    """

    def __init__(self, obj, arm_owner=None):
        self.object = obj  #: Link to the blender's object
        self._yabee_object = None  # Internal data
        self.children = []  #: List of children (Groups)
        self.arm_owner = None  # Armature as owner for bones

        if arm_owner and obj.__class__ == bpy.types.Bone:
            self.arm_owner = arm_owner

        if self.object and self.object.__class__ != bpy.types.Bone:
            if self.object.type == 'MESH':
                # We are a mesh with an armature modifier, we shall be considered an actor.
                if 'ARMATURE' in [m.type for m in self.object.modifiers]:
                    self._yabee_object = EGGActorObjectData(self.object)
                else:
                    self._yabee_object = EGGMeshObjectData(self.object)
            elif self.object.type == 'CURVE':
                self._yabee_object = EGGNurbsCurveObjectData(self.object)

            # Does this ever get called, and how?
            elif self.object.type == 'ARMATURE':
                pass
            else:
                self._yabee_object = EGGBaseObjectData(self.object)

    def update_joints_data(self, actor_data_list=None):
        if actor_data_list is None:
            actor_data_list = []
            hierarchy_to_list(self, actor_data_list, base_filter = EGGActorObjectData)

        if not self._yabee_object and self.object and self.object.__class__ == bpy.types.Bone:
            vref = []
            for actor_data in actor_data_list:
                if self.object.name in actor_data._yabee_object.joint_vtx_ref.keys():
                    vref.append(actor_data._yabee_object.joint_vtx_ref[self.object.name])
            self._yabee_object = EGGJointObjectData(self.object, vref, self.arm_owner)

        for child in self.children:
            child.update_joints_data(actor_data_list)

    def check_parenting(self, p, o, obj_list):
        # 0 - Not
        # 1 - Object to object
        # 2 - Bone to Bone
        # 3 - Object to Bone
        if o.__class__ == bpy.types.Bone and not o.parent:
            return 0
        if p.__class__ != bpy.types.Bone and o.parent == p and not (p and p.type == 'ARMATURE' and o.parent_bone):
            return 1
        if not p and (str(o.parent) not in map(str, obj_list)):
            return 1
        if p and p.__class__ == bpy.types.Bone and o.__class__ == bpy.types.Bone and o.parent == p:
            return 2
        # ACHTUNG!!! Be careful: If we have two armatures with the
        # same bones name and object, attached to it,
        # then we can get unexpected results!
        if o.__class__ != bpy.types.Bone and o.parent_type == 'BONE' and p and o.parent_bone == p.name:
            return 3
        return 0

    def make_hierarchy_from_list(self, obj_list):
        """
        This function make <Group> hierarchy from the list of Blender's objects.
        Self.object is the top level of the created hierarchy.
        Usually in this case self.object == None

        @param obj_list: tuple or list of blender's objects.
        """
        try:
            if self.object and self.object.__class__ != bpy.types.Bone and self.object.type == 'ARMATURE':
                obj_list += self.object.data.bones
                for bone in self.object.data.bones:
                    if not bone.parent:
                        try:
                            group = self.__class__(bone, self.object)  # type: Group
                        except:
                            print_exc()
                            return ['ERR_MK_OBJ', ]
                        self.children.append(group)
                        group.make_hierarchy_from_list(obj_list)
            for obj in obj_list:
                # If we have a relationship with the current blender objects, whether by obj2obj, bone2bone, or bone2obj
                if self.check_parenting(self.object, obj, obj_list) > 0:
                    if obj.__class__ == bpy.types.Bone:
                        try:
                            group = self.__class__(obj, self.arm_owner)
                        except:
                            print_exc()
                            return ['ERR_MK_OBJ', ]
                    else:
                        try:
                            group = self.__class__(obj)
                        except:
                            print_exc()
                            return ['ERR_MK_OBJ', ]
                    self.children.append(group)
                    group.make_hierarchy_from_list(obj_list)
        except Exception as exc:
            print_exc()
            return ['ERR_MK_HIERARCHY', ]
        return []

    def print_hierarchy(self, level=0):
        """
        Debug function to print out hierarchy to console.

        @param level: starting indent level.
        """
        print('-' * level, self.object)
        for child in self.children:
            child.print_hierarchy(level + 1)

    def get_full_egg_str(self, level=0):
        return ''.join(self.get_full_egg_str_arr(level))

    def get_full_egg_str_arr(self, level=0):
        """
        Create and return representation of the EGG  <Group> with hierarchy, started from self.object.
        It's start point to generating EGG structure.

        @param level: starting indent level.

        @return: full EGG string of group.
        """
        egg_str = []

        if self.object:

            # Add the header for this container
            # Todo: Support for <Instance>
            if self.object.__class__ == bpy.types.Bone:
                egg_str.append('%s<Joint> %s {\n' % ('  ' * level, eggSafeName(self.object.yabee_name)))
            else:
                egg_str.append('%s<Group> %s {\n' % ('  ' * level, eggSafeName(self.object.yabee_name)))

                # Are we an actor and is this related to our nodes?
                if self.object.type == 'ARMATURE' or (
                        self.object.type == 'MESH' and (
                        self.object.data.shape_keys and
                        len(self.object.data.shape_keys.key_blocks) > 1)
                ):
                    egg_str.append('%s<Dart> { 1 }\n' % ('  ' * (level + 1)))

            if self._yabee_object:
                for line in self._yabee_object.get_full_egg_str().splitlines():
                    egg_str.append('%s%s\n' % ('  ' * (level + 1), line))

            for child in self.children:
                egg_str.append(child.get_full_egg_str(level + 1))

            egg_str.append('%s}\n' % ('  ' * level))
        else:
            for child in self.children:
                egg_str.append(child.get_full_egg_str(level + 1))
        return egg_str


class EGGArmature(Group):
    """
    Representation of the EGG <Joint> hierarchy.
    Receives Blender's bones list as obj_list in constructor.
    """

    def get_full_egg_str(self, vrefs, arm_owner, level=0):
        """
        Create and return string representation of the EGG <Joint> with hierarchy.

        @param vrefs: reference of vertices, linked to bones.
        @param arm_owner: Armature object - owner of the bones
        @param level: indent level.

        @return: the EGG string with joints hierarchy
        """
        egg_str = ''

        if self.object:
            egg_str += '%s<Joint> %s {\n' % ('  ' * level, eggSafeName(self.object.yabee_name))
            vref = {}
            if self.object.yabee_name in list(vrefs.keys()):
                vref = vrefs[self.object.yabee_name]

            joint = EGGJointObjectData(self.object, vref, arm_owner)
            for line in joint.get_full_egg_str().splitlines():
                egg_str += '%s%s\n' % ('  ' * (level + 1), line)
            for child in self.children:
                egg_str += child.get_full_egg_str(vrefs, arm_owner, level + 1)
            egg_str += '%s}\n' % ('  ' * level)

        else:
            for child in self.children:
                egg_str += child.get_full_egg_str(vrefs, arm_owner, level + 1)

        return egg_str


# -----------------------------------------------------------------------
#                           BASE OBJECT
# -----------------------------------------------------------------------
class EGGBaseObjectData:
    """
    Base representation of the EGG object data
    """

    def __init__(self, obj):
        self.obj_ref = obj
        if obj.parent:
            self.transform_matrix = obj.matrix_local
        else:
            self.transform_matrix = obj.matrix_world

    def get_transform_str(self):
        """
        Return the EGG string representation of object transforms.
        """
        transform_str = ['<Transform> {\n  <Matrix4> {\n', ]
        for column in self.transform_matrix.col:
            transform_str.append('    ')
            for row in column[:]:
                # transform_str += [STRF( row ), ' ']
                transform_str += [str(row), ' ']
            transform_str.append('\n')
        transform_str.append('  }\n}\n')
        return ''.join(transform_str)

    def get_full_egg_str(self):
        return self.get_transform_str() + '\n'


class EGGNurbsCurveObjectData(EGGBaseObjectData):
    """
    Representation of the EGG NURBS Curve
    """

    def collect_vertices(self):
        vertices = []
        idx = 0
        for spline in self.obj_ref.data.splines:
            for vtx in spline.points:
                co = self.obj_ref.matrix_world * vtx.co
                fixed_co = tuple(map(lambda x: x * co[3], co[:3])) + (co[3],)
                vertices.append('<Vertex> %i {\n  %s\n}\n' % (idx, ' '.join(map(STRF, fixed_co))))
                idx += 1
        return vertices

    def get_vtx_pool_str(self):
        """
        Return the vertex pool string in the EGG syntax.
        """
        vtx_pool = ''
        vertices = self.collect_vertices()
        if vertices:
            vtx_pool = '<VertexPool> %s {\n' % eggSafeName(self.obj_ref.yabee_name)
            for vtx_str in vertices:
                for line in vtx_str.splitlines():
                    vtx_pool += '  ' + line + '\n'
            vtx_pool += '}\n'
        return vtx_pool

    def get_curves_str(self):
        """
        Return the <NURBSCurve> string.
        Blender 2.5 has not contain Knots information, seems it's calculating in runtime.
        I got algorythm for the knots calculation from the OBJ exporter and modified it.
        """
        str2f = lambda x: '%.2f' % x
        cur_str = ''
        idx = 0
        for spline in self.obj_ref.data.splines:
            if spline.type != "NURBS":
                continue
            knots_num = spline.point_count_u + spline.order_u
            knots = [i / (knots_num - 1) for i in range(knots_num)]
            if spline.use_endpoint_u:
                for i in range(spline.order_u - 1):
                    knots[i] = 0.0
                    knots[-(i + 1)] = 1.0
                for i in range(knots_num - (spline.order_u * 2) + 2):
                    knots[i + spline.order_u - 1] = i / (knots_num - (spline.order_u * 2) + 1)
            cur_str += '<NURBSCurve> {\n'
            cur_str += '  <Scalar> subdiv { %i }\n' % (spline.resolution_u * (spline.point_count_u - 1))
            cur_str += '  <Order> { %i }\n' % spline.order_u
            cur_str += '  <Knots> { %s }\n' % ' '.join(map(str2f, knots))
            cur_str += '  <VertexRef> {\n    %s\n    <Ref> { %s } \n  }\n' % (
                ' '.join([str(i) for i in range(idx, idx + spline.point_count_u)]),
                eggSafeName(self.obj_ref.yabee_name)
            )
            cur_str += '}\n'
            idx += spline.point_count_u
        return cur_str

    def get_full_egg_str(self):
        return self.get_transform_str() + self.get_vtx_pool_str() + self.get_curves_str()


class EGGJointObjectData(EGGBaseObjectData):
    """
    Representation of the EGG <Joint> data
    """

    def __init__(self, obj, vref, arm_owner):
        """
        @param vref: reference of vertices, linked to bone.
        @param arm_owner: Armature object - owner of the bone
        """
        self.obj_ref = obj
        self.arm_owner = arm_owner
        if not obj.parent:
            # Get the current transformation matrix by (world space * local space)
            self.transform_matrix = arm_owner.matrix_world @ obj.matrix_local
        else:
            # I think this just negates some world transformation idk
            self.transform_matrix = obj.parent.matrix_local.inverted() @ obj.matrix_local
        self.vref = vref

    def get_vref_str(self):
        """
        Convert vertex reference to the EGG string and return it.
        """
        vref_str = ''
        for meshes in self.vref:
            for vpool, data in meshes.items():
                weightgroups = {}
                for idx, weight in data:
                    weight_str = '%f' % weight
                    if weight_str not in list(weightgroups.keys()):
                        weightgroups[weight_str] = []
                    weightgroups[weight_str].append(idx)
                for wgrp, idxs in weightgroups.items():
                    vref_str += '<VertexRef> {\n'
                    vref_str += '  ' + ' '.join(map(str, idxs)) + '\n'
                    vref_str += '  <Scalar> membership { %s }' % wgrp
                    vref_str += '  <Ref> { %s }\n}\n' % vpool
        return vref_str

    def get_full_egg_str(self):
        egg_str = ''
        egg_str += self.get_transform_str()
        egg_str += self.get_vref_str()
        return egg_str


# -----------------------------------------------------------------------
#                           MESH OBJECT
# -----------------------------------------------------------------------
class EGGMeshObjectData(EGGBaseObjectData):
    """
    EGG data representation of the mesh object
    """

    def __init__(self, obj):
        EGGBaseObjectData.__init__(self, obj)
        self.poly_vtx_ref = self.pre_convert_poly_vtx_ref()
        self.smooth_vtx_list = self.get_smooth_vtx_list()
        self.colors_vtx_ref = self.pre_convert_vtx_color()
        self.uvs_list = self.pre_convert_uvs()
        self.tangent_layers = None
        if CALC_TBS == 'BLENDER':
            self.tangent_layers = self.pre_calc_TBS()

        # Check if we may need to generate ORCO coordinates.
        uses_nodes = False
        need_orco = False
        for face in self.obj_ref.data.polygons:
            if face.material_index >= len(obj.data.materials):
                continue
            if not obj.data.materials[face.material_index]:
                continue
            if obj.data.materials[face.material_index]:
                if obj.data.materials[face.material_index].use_nodes:
                    uses_nodes = True

        # Store current active UV name
        self.active_uv = None

        # now there is no uv_layers attribute, instead uv_layers
        auv = [uv for uv in obj.data.uv_layers if uv.active]

        # if we use nodes we don't want the active-uv name to be empty later on.
        # (we need those to access from uv-map nodes)
        if not uses_nodes and auv:
            self.active_uv = auv[0].name

    # -------------------------------------------------------------------
    #                           AUXILIARY

    def get_smooth_vtx_list(self):
        """
        Collect the smoothed polygon vertices for write normals of the vertices.
        In the EGG for the smooth shading used normals of vertices. For solid - polygons.
        """
        vtx_list = []
        for poly_index, polygon in enumerate(self.obj_ref.data.polygons):
            if polygon.use_smooth:
                for vertex in self.poly_vtx_ref[poly_index]:
                    vtx_list.append(vertex)
        vtx_list = set(vtx_list)

        if hasattr(self.obj_ref.data, "use_auto_smooth") and self.obj_ref.data.use_auto_smooth:
            sharp_edges = [edge.key for edge in self.obj_ref.data.edges if edge.use_edge_sharp]
            for poly_index, polygon in enumerate(self.obj_ref.data.polygons):
                for poly_edge in polygon.edge_keys:
                    if poly_edge in sharp_edges:
                        for edge_vertex in poly_edge:
                            edge_index = list(polygon.vertices).index(edge_vertex)
                            iv = self.poly_vtx_ref[poly_index][edge_index]
                            if iv in vtx_list:
                                vtx_list.remove(iv)
        return vtx_list

    def pre_convert_uvs(self):
        """
        Blender uses shared vertices, but for the correct working UV and shading in the Panda needs to convert
        they are in the individual vertices for each polygon.
        """
        uv_list = []
        for uv_layer in self.obj_ref.data.uv_layers:
            data = []
            for uv_data in uv_layer.data:
                u, v = uv_data.uv.to_2d()
                data.append((u, v))
            uv_list.append((uv_layer.name, data))
        return uv_list

    def pre_convert_poly_vtx_ref(self):
        """
        Blender uses shared vertices, but for the correct working UV and shading in the Panda
        needs to convert they are in the individual vertices for each polygon.
        """
        poly_vtx_ref = []
        idx = 0
        for face in self.obj_ref.data.polygons:
            vtxs = []
            for vertex in face.vertices:
                vtxs.append(idx)
                idx += 1
            poly_vtx_ref.append(vtxs)
        return poly_vtx_ref

    def pre_convert_vtx_color(self):
        color_vtx_ref = []
        if self.obj_ref.data.vertex_colors.active:
            for col in self.obj_ref.data.vertex_colors.active.data:
                color_vtx_ref.append(col.color)  # We have one color per data color
        return color_vtx_ref

    def pre_calc_TBS(self):
        """
        Use Blender internal algorithm to generate tangent and bitangent (binormal) for each UV layer
        """
        tangent_layers = []
        for idx, uv_layer in enumerate(self.obj_ref.data.uv_layers):
            tangents = []
            self.obj_ref.data.calc_tangents(uvmap = uv_layer.name)

            for loop in self.obj_ref.data.loops:
                tangents.append(loop.tangent[:] + loop.bitangent[:])
            tangent_layers.append(tangents)
        return tangent_layers

    def pre_calc_ORCO(self):
        """
        Generate texture coordinates for ORCO slots

        Generated/ Original coordinate (ORCO) is a 'normalized' local coordinate of the vertex.
        Basically, given the local bounding box of the object: Orco(v) = 2*(v-center)/size.
        """
        print("precalculating orco")
        # To get a bounding box, we first have to calculate the min and max vertex position...
        minmax = None
        for face in self.obj_ref.data.polygons:
            for vertex in face.vertices:
                pos = self.obj_ref.data.vertices[vertex].co
                if minmax is None:
                    minmax = (list(pos), list(pos))
                for i in range(3):
                    minmax[0][i] = min(pos[i], minmax[0][i])
                    minmax[1][i] = max(pos[i], minmax[1][i])

        if not minmax:
            return

        # uvw?
        inv_dims = [0, 0, 0]
        for i in (0, 1, 2):
            delta = (minmax[1][i] - minmax[0][i])
            if delta > 0:  # Prevent divide by zero
                inv_dims[i] = 1.0 / delta

        data = []
        for face in self.obj_ref.data.polygons:
            for vertex in face.vertices:
                pos = self.obj_ref.data.vertices[vertex].co
                orco = [(pos[i] - minmax[0][i]) * inv_dims[i] for i in (0, 1, 2)]
                data.append(orco)

        self.uvs_list.append(('ORCO', data))

    # -------------------------------------------------------------------
    #                           VERTICES

    def collect_vtx_xyz(self, vidx, attributes):
        """
        Add coordinates of the vertex to the vertex attributes list

        @param vidx: Blender's internal vertex index.
        @param attributes: list of vertex attributes

        @return: list of vertex attributes.
        """
        # get coords relative to itself?
        co = self.obj_ref.matrix_world @ self.obj_ref.data.vertices[vidx].co
        attributes.append('%f %f %f' % co[:])
        return attributes

    def collect_vtx_dxyz(self, vidx, attributes):
        """
        Add morph target <Dxyz> to the vertex attributes list.

        @param vidx: Blender's internal vertex index.
        @param attributes: list of vertex attributes

        @return: list of vertex attributes.
        """
        if self.obj_ref.data.shape_keys and (len(self.obj_ref.data.shape_keys.key_blocks) > 1):
            for i in range(1, len(self.obj_ref.data.shape_keys.key_blocks)):
                key = self.obj_ref.data.shape_keys.key_blocks[i]
                vtx = self.obj_ref.data.vertices[vidx]
                co = key.data[vidx].co @ self.obj_ref.matrix_world - vtx.co @ self.obj_ref.matrix_world
                if co.length > 0.000001:
                    attributes.append('<Dxyz> %s { %f %f %f }\n' % (eggSafeName(key.name), co[0], co[1], co[2]))
        return attributes

    def collect_vtx_normal(self, v, idx, attributes):
        """
        Add <Normal> to the vertex attributes list.

        @param v: Blender vertex index.
        @param idx: the EGG (converted) vertex index.
        @param attributes: list of vertex attributes

        @return: list of vertex attributes.
        """
        if idx in self.smooth_vtx_list:
            no = self.obj_ref.matrix_world.to_euler().to_matrix() @ self.obj_ref.data.vertices[v].normal
            # no = self.obj_ref.data.vertices[v].normal
            # no = self.obj_ref.data.loops[idx].normal
            attributes.append('<Normal> { %f %f %f }' % no[:])

        return attributes

    def collect_vtx_normal_from_loop(self, v, idx, attributes):
        """
        Add <Normal> to the vertex attributes list, using the loop normal associated with this Blender vertex index.

        @param v: Blender vertex index.
        @param idx: the EGG (converted) vertex index.
        @param attributes: list of vertex attributes

        @return: list of vertex attributes.
        """
        if idx in self.smooth_vtx_list:
            no = self.obj_ref.matrix_world.to_euler().to_matrix() @ self.obj_ref.data.loops[
                self.map_vertex_to_loop[v]].normal
            attributes.append('  <Normal> { %f %f %f }' % no[:])
        return attributes

    def collect_vtx_rgba(self, vidx, face, attributes):
        if self.colors_vtx_ref:
            # Don't write out vertex colors unless a material actually uses it.
            if face.material_index < len(self.obj_ref.data.materials):
                mat = self.obj_ref.data.materials[face.material_index]
                if FORCE_EXPORT_VERTEX_COLORS or mat:
                    vcolors = self.colors_vtx_ref[vidx]
                    attributes.append('  <RGBA> { %f %f %f %f }' % vcolors[:])
            else:
                # Write out vertex colors if no material applied
                vcolors = self.colors_vtx_ref[vidx]
                attributes.append('  <RGBA> { %f %f %f %f }' % vcolors[:])
        else:
            # if material has no texture:
            for mat in self.obj_ref.data.materials:
                nodeTree = mat.node_tree
                if nodeTree and nodeTree.nodes:
                    for pandaShaderNode in nodeTree.links:
                        if pandaShaderNode.to_node.name == "Material Output":
                            attributes.append('  <RGBA> { 1 1 1 1 }')
        return attributes

    def collect_vtx_uv(self, vidx, ividx, attributes):
        """
        Add <UV> to the vertex attributes list.

        @param vidx: the EGG (converted) vertex index.
        @param ividx: Blender internal vertex index.
        @param attributes: list of vertex attributes

        @return: list of vertex attributes.
        """
        for i, uv in enumerate(self.uvs_list):
            name, data = uv
            if name == self.active_uv and name != 'ORCO':
                name = ''
            tbs = ''
            if self.tangent_layers:
                tbs = '\n    <Tangent> {%f %f %f}\n    <Binormal> {%f %f %f}' % self.tangent_layers[i][ividx]

            uv_str = '  <UV> %s {\n    %f %f %s\n  }' % (
                eggSafeName(name), data[ividx][0], data[ividx][1], tbs
            )
            attributes.append(uv_str)

        return attributes

    def collect_vertices(self):
        """
        Convert and collect vertices' info.
        """
        xyz = self.collect_vtx_xyz
        dxyz = self.collect_vtx_dxyz
        rgba = self.collect_vtx_rgba
        uv = self.collect_vtx_uv

        if USE_LOOP_NORMALS and self.obj_ref.data.has_custom_normals:
            self.map_vertex_to_loop = {
                self.obj_ref.data.loops[loop_idx].vertex_index: loop_idx
                for face in self.obj_ref.data.polygons for loop_idx in face.loop_indices
            }
            normal = self.collect_vtx_normal_from_loop
        else:
            normal = self.collect_vtx_normal

        vertices = []
        idx = 0
        for face in self.obj_ref.data.polygons:
            for vertex in face.vertices:
                # vertex - Blender inner vertex index
                # idx - Vertex index for the EGG
                attributes = []
                xyz(vertex, attributes)
                dxyz(vertex, attributes)
                normal(vertex, idx, attributes)
                rgba(idx, face, attributes)
                uv(vertex, idx, attributes)
                str_attr = '\n'.join(attributes)
                vtx = '\n<Vertex> %i {%s\n}' % (idx, str_attr)
                vertices.append(vtx)
                idx += 1
        return vertices

    # -------------------------------------------------------------------
    #                           POLYGONS

    def collect_poly_tref(self, face, attributes):
        """
        Add <TRef> to the polygon's attributes list.

        @param face: face index.
        @param attributes: list of polygon's attributes.

        @return: list of polygon's attributes.
        """
        global USED_TEXTURES, TEXTURE_PROCESSOR
        if TEXTURE_PROCESSOR in 'BAKE':
            # Store all texture references here.
            # It is important that this is a list so the texture order is preserved.
            textures = []

            # Find the material assigned to that polygon:
            # First, check if that polygon has a material at all
            material = None
            matIsFancyPBRNode = False
            if face.material_index < len(self.obj_ref.data.materials):
                material = self.obj_ref.data.materials[face.material_index]

            if material:
                if material.use_nodes:
                    nodeTree = material.node_tree
                    if nodeTree.nodes:
                        matIsFancyPBRNode = True

                        if matIsFancyPBRNode:
                            # we need to find a couple of textures here
                            # we do need an empty for specular but it's added somewhere else
                            nodeNames = {
                                "Base Color": None,
                                "Normal": None
                            }

                            # let's crawl all links, find the ones connected to the Principled BSDF,
                            for link in material.node_tree.links:
                                # if the link connects to the Principled BSDF node
                                # and it connects to one of our known sockets...
                                if link.to_node.name == "Principled BSDF":
                                    if link.to_socket.name in nodeNames.keys():
                                        textureNode = link.from_node
                                        # we have to find the texture name here.
                                        nodeNames[link.to_socket.name] = textureNode.name

                            for texNodes in ['Base Color', 'Normal']:
                                tex = nodeNames[texNodes]
                                if tex:
                                    textures.append(tex)

                    else:
                        # The object has no material, that means it will get no textures
                        print("WARNING: Object", self.obj_ref.name, "has no material assigned!")

                    # Store all textures
                    for tex_name in textures:
                        if tex_name in USED_TEXTURES:
                            # Make sure that  we'll have this texture in header
                            # todo:add this back once empties are added for PBR nodes
                            attributes.append('<TRef> { %s }' % eggSafeName(tex_name))

                else:
                    if self.obj_ref.data.uv_layers and material.use_nodes:
                        for btype, params in BAKE_LAYERS.items():
                            if len(params) == 2:
                                params = (params[0], params[0], params[1])
                            if params[2]:
                                attributes.append('<TRef> { %s }' % eggSafeName(self.obj_ref.yabee_name + '_' + btype))

        return attributes

    def collect_poly_mref(self, face, attributes):
        """
        Add <MRef> to the polygon's attributes list.

        @param face: face index.
        @param attributes: list of polygon's attributes.

        @return: list of polygon's attributes.
        """
        if face.material_index < len(self.obj_ref.data.materials):
            mat = self.obj_ref.data.materials[face.material_index]
            if mat:
                attributes.append('<MRef> { %s }' % eggSafeName(mat.yabee_name))
        return attributes

    def collect_poly_normal(self, face, attributes):
        """
        Add <Normal> to the polygon's attributes list.

        @param face: face index.
        @param attributes: list of polygon's attributes.

        @return: list of polygon's attributes.
        """
        # normalized normal
        no = self.obj_ref.matrix_world.to_euler().to_matrix() @ face.normal
        attributes.append('<Normal> {%f %f %f}' % no[:])
        return attributes

    def collect_poly_rgba(self, face, attributes):
        # is this suppose to behave similarly to collect_poly_mref ?
        if face.material_index < len(self.obj_ref.data.materials):
            return attributes

    def collect_poly_bface(self, face, attributes):
        """
        Add <BFace> to the polygon's attributes list.

        @param face: face index.
        @param attributes: list of polygon's attributes.

        @return: list of polygon's attributes.
        """
        if face.material_index < len(self.obj_ref.data.materials):
            if not self.obj_ref.data.materials[face.material_index]:
                return attributes

            if not self.obj_ref.data.materials[face.material_index].use_backface_culling:
                attributes.append('<BFace> { 1 }')

        return attributes

    def collect_poly_vertexref(self, face, attributes):
        """
        Add <VertexRef> to the polygon's attributes list.

        @param face: face index.
        @param attributes: list of polygon's attributes.

        @return: list of polygon's attributes.
        """
        vref = ' '.join(map(str, self.poly_vtx_ref[face.index]))
        attributes.append('<VertexRef> { %s <Ref> { %s }}' % (vref, eggSafeName(self.obj_ref.yabee_name)))
        return attributes

    def collect_polygons(self):
        """
        Convert and collect polygons info
        """
        tref = self.collect_poly_tref
        mref = self.collect_poly_mref
        normal = self.collect_poly_normal
        rgba = self.collect_poly_rgba
        bface = self.collect_poly_bface
        vertexref = self.collect_poly_vertexref
        polygons = []
        for face in self.obj_ref.data.polygons:
            attributes = []
            tref(face, attributes)
            mref(face, attributes)
            normal(face, attributes)
            rgba(face, attributes)
            vertexref(face, attributes)
            poly = '<Polygon> {\n  %s \n}\n' % ('\n  '.join(attributes),)

            polygons.append(poly)
        return polygons

    def get_vtx_pool_str(self):
        """
        Return the vertex pool string in the EGG syntax.
        """
        vtx_pool = '<VertexPool> %s {\n' % eggSafeName(self.obj_ref.yabee_name)
        vtxs = ''.join(self.collect_vertices())
        vtxs = vtxs.replace('\n', '\n  ')
        vtx_pool += vtxs
        vtx_pool += '}\n'
        return vtx_pool

    def get_polygons_str(self):
        """
        Return polygons string in the EGG syntax
        """
        polygons = '\n' + ''.join(self.collect_polygons())
        return polygons

    def get_full_egg_str(self):
        """
        Return full mesh data representation in the EGG string syntax
        """
        return '\n'.join((self.get_transform_str(),
                          self.get_vtx_pool_str(),
                          self.get_polygons_str()))


# -----------------------------------------------------------------------
#                           ACTOR OBJECT
# -----------------------------------------------------------------------

class EGGActorObjectData(EGGMeshObjectData):
    """
    Representation of the EGG animated object data
    """

    def __init__(self, obj):
        EGGMeshObjectData.__init__(self, obj)
        self.joint_vtx_ref = self.pre_convert_joint_vtx_ref()

    def pre_convert_joint_vtx_ref(self):
        """
        Collect and convert vertices, assigned to the bones
        """
        joint_vref = {}
        idx = 0
        for face in self.obj_ref.data.polygons:
            for vertex in face.vertices:
                for vertgroup in self.obj_ref.data.vertices[vertex].groups:
                    group_name = self.obj_ref.vertex_groups[vertgroup.group].name

                    # Group name = Joint (bone) name
                    if group_name not in list(joint_vref.keys()):
                        joint_vref[group_name] = {}

                    # Object name = vertices pool name
                    if self.obj_ref.yabee_name not in list(joint_vref[group_name].keys()):
                        joint_vref[group_name][self.obj_ref.yabee_name] = []

                    joint_vref[group_name][self.obj_ref.yabee_name].append((idx, vertgroup.weight))

                idx += 1
        return joint_vref

    def get_joints_str(self):
        """
        Make the EGGArmature object from the bones, pass the vertex reference to it,

        :return: the EGG string representation of the joints/bone hierarchy.
        """
        joints_str = ''
        for mod in self.obj_ref.modifiers:
            if mod.type != 'ARMATURE':
                continue
            armature = EGGArmature(None)
            armature.make_hierarchy_from_list(mod.object.data.bones)
            joints_str += armature.get_full_egg_str(self.joint_vtx_ref, mod.object, -1)
        return joints_str


class EGGAnimJoint(Group):
    """
    Representation of the <Joint> animation data.
    Has the same hierarchy as the character's skeleton.
    """

    def make_hierarchy_from_list(self, obj_list):
        """
        Old <Group> function
        -------------------------------
        This function make <Group> hierarchy from the list of
        Blender's objects. Self.object is the top level of the created
        hierarchy. Usually in this case self.object == None

        @param obj_list: tuple or list of blender's objects.
        """
        for obj in obj_list:
            if (
                    (obj.parent == self.object) or
                    ((self.object is None) and
                     (str(obj.parent) not in map(str, obj_list)) and
                     (str(obj) not in [str(child.object) for child in self.children]))
            ):
                try:
                    group = self.__class__(obj)
                except:
                    print_exc()
                    return ['ERR_MK_OBJ', ]
                self.children.append(group)
                group.make_hierarchy_from_list(obj_list)
        return []

    def get_full_egg_str(self, anim_info, framerate, level=0):
        """
        Create and return the string representation of the <Joint> animation data, included all joints hierarchy.
        """
        egg_str = ''
        if self.object:
            egg_str += '%s<Table> %s {\n' % ('  ' * level, eggSafeName(self.object.yabee_name))
            bone_data = anim_info['<skeleton>'][self.object.yabee_name]
            egg_str += '%s  <Xfm$Anim> xform {\n' % ('  ' * level)
            egg_str += '%s    <Scalar> order { sprht }\n' % ('  ' * level)
            egg_str += '%s    <Scalar> fps { %i }\n' % ('  ' * level, framerate)
            egg_str += '%s    <Scalar> contents { ijkprhxyz }\n' % ('  ' * level)
            egg_str += '%s    <V> {\n' % ('  ' * level)
            for i in range(len(bone_data['r'])):
                egg_str += '%s      %s %s %s %s %s %s %s %s %s\n' % (
                    '  ' * level,
                    STRF(bone_data['i'][i]),
                    STRF(bone_data['j'][i]),
                    STRF(bone_data['k'][i]),
                    STRF(bone_data['p'][i]),
                    STRF(bone_data['r'][i]),
                    STRF(bone_data['h'][i]),
                    STRF(bone_data['x'][i]),
                    STRF(bone_data['y'][i]),
                    STRF(bone_data['z'][i]))
            egg_str += '%s    }\n' % ('  ' * level)
            egg_str += '%s  }\n' % ('  ' * level)
            for child in self.children:
                egg_str += child.get_full_egg_str(anim_info, framerate, level + 1)
            egg_str += '%s}\n' % ('  ' * level)

        else:
            for child in self.children:
                egg_str += child.get_full_egg_str(anim_info, framerate, level + 1)

        return egg_str


class AnimCollector:
    """
    Collect an armature and a shapekeys animation data and convert it to the EGG string.
    """

    def __init__(self, obj_list, start_f, stop_f, framerate, name, action=None):
        """
        @param obj_list: list or tuple of the Blender's objects for which needed to collect animation data.
        @param start_f: number of the "from" frame.
        @param stop_f: number of the "to" frame.
        @param framerate: framerate for the given animation.
        @param name: name of the animation for access in the Panda.
        """
        self.obj_list = obj_list
        self.start_f = start_f
        self.stop_f = stop_f
        if self.start_f == self.stop_f:
            self.stop_f += 1
        self.framerate = framerate
        self.name = name
        self.bone_groups = {}
        for arm in bpy.data.armatures:
            arm.pose_position = 'POSE'
        self.obj_anim_ref = {}

        for obj in obj_list:
            if obj.__class__ != bpy.types.Bone:
                if obj.type == 'MESH':
                    if obj.data.shape_keys and (len(obj.data.shape_keys.key_blocks) > 1):
                        if obj.yabee_name not in list(self.obj_anim_ref.keys()):
                            self.obj_anim_ref[obj.yabee_name] = {}
                        self.obj_anim_ref[obj.yabee_name]['morph'] = self.collect_morph_anims(obj)

                elif obj.type == 'ARMATURE':
                    if action and obj.animation_data:
                        obj.animation_data.action = action
                    self.bone_groups[obj.yabee_name] = EGGAnimJoint(None)
                    self.bone_groups[obj.yabee_name].make_hierarchy_from_list(obj.data.bones)
                    if obj.yabee_name not in list(self.obj_anim_ref.keys()):
                        self.obj_anim_ref[obj.yabee_name] = {}
                    self.obj_anim_ref[obj.yabee_name]['<skeleton>'] = self.collect_arm_anims(obj)

    def collect_morph_anims(self, obj):
        """
        Collect an animation data for the morph target (shapekeys).

        @param obj: Blender's object for which need to collect an animation data
        """
        keys = {}
        if obj.data.shape_keys and (len(obj.data.shape_keys.key_blocks) > 1):
            current_frame = bpy.context.scene.frame_current
            anim_dict = {}
            for frame in range(self.start_f, self.stop_f):
                bpy.context.scene.frame_current = frame
                bpy.context.scene.frame_set(frame)
                for i in range(1, len(obj.data.shape_keys.key_blocks)):
                    key = obj.data.shape_keys.key_blocks[i]
                    if key.name not in list(keys.keys()):
                        keys[key.name] = []
                    keys[key.name].append(key.value)
            bpy.context.scene.frame_current = current_frame
        return keys

    def collect_arm_anims(self, arm):
        """
        Collect an animation data for the skeleton (Armature).

        @param arm: Blender's Armature for which need to collect an animation data
        """
        current_f = bpy.context.scene.frame_current
        anim_dict = {}
        for frame in range(self.start_f, self.stop_f):
            bpy.context.scene.frame_current = frame
            bpy.context.scene.frame_set(frame)
            for bone in arm.pose.bones:
                if bone.yabee_name not in list(anim_dict.keys()):
                    anim_dict[bone.yabee_name] = {}
                for keyword in 'ijkabcrphxyz':
                    if keyword not in list(anim_dict[bone.yabee_name].keys()):
                        anim_dict[bone.yabee_name][keyword] = []
                if bone.parent:
                    matrix = bone.parent.matrix.inverted() @ bone.matrix
                else:
                    matrix = arm.matrix_world @ bone.matrix

                i, j, k = matrix.to_scale()
                anim_dict[bone.yabee_name]['i'].append(i)
                anim_dict[bone.yabee_name]['j'].append(j)
                anim_dict[bone.yabee_name]['k'].append(k)
                p, r, h = matrix.to_euler()
                anim_dict[bone.yabee_name]['p'].append(p / pi * 180)
                anim_dict[bone.yabee_name]['r'].append(r / pi * 180)
                anim_dict[bone.yabee_name]['h'].append(h / pi * 180)
                x, y, z = matrix.to_translation()
                anim_dict[bone.yabee_name]['x'].append(x)
                anim_dict[bone.yabee_name]['y'].append(y)
                anim_dict[bone.yabee_name]['z'].append(z)
        bpy.context.scene.frame_current = current_f
        return anim_dict

    def get_morph_anim_str(self, obj_name):
        """ Create and return the EGG string of the morph animation for
        the given object.

        @param obj_name: name of the Blender's object
        """
        morph_str = ''
        data = self.obj_anim_ref[obj_name]
        if 'morph' in list(data.keys()):
            morph_str += '<Table> morph {\n'
            for key, anim_vals in data['morph'].items():
                morph_str += '  <S$Anim> %s {\n' % eggSafeName(key)
                morph_str += '    <Scalar> fps { %i }\n' % self.framerate
                morph_str += '    <V> { %s }\n' % (' '.join(map(STRF, anim_vals)))
                morph_str += '  }\n'
            morph_str += '}\n'
        return morph_str

    def get_skeleton_anim_str(self, obj_name):
        """
        Create and return the EGG string of the Armature animation for the given object.

        @param obj_name: name of the Blender's object
        """
        skel_str = ''
        data = self.obj_anim_ref[obj_name]
        if '<skeleton>' in list(data.keys()):
            skel_str += '<Table> "<skeleton>" {\n'
            for line in self.bone_groups[obj_name].get_full_egg_str(data, self.framerate, -1).splitlines():
                skel_str += '  %s\n' % line
            skel_str += '}\n'
        return skel_str

    def get_full_egg_str(self):
        """
        Create and return the full EGG string for the animation, which has been setup in the object's constructor
        """
        egg_str = ''
        if self.obj_anim_ref:
            egg_str += '<Table> {\n'
            for obj_name, obj_data in self.obj_anim_ref.items():
                yabee_obj_name = bpy.data.objects[obj_name].yabee_name
                if self.name:
                    anim_name = self.name
                else:
                    anim_name = obj_name

                if SEPARATE_ANIM_FILE or ANIM_ONLY:
                    egg_str += '  <Bundle> %s {\n' % eggSafeName(yabee_obj_name)
                else:
                    egg_str += '  <Bundle> %s {\n' % eggSafeName(anim_name)

                for line in self.get_skeleton_anim_str(obj_name).splitlines():
                    egg_str += '    %s\n' % line

                for line in self.get_morph_anim_str(obj_name).splitlines():
                    egg_str += '    %s\n' % line

                egg_str += '  }\n'
            egg_str += '}\n'
        return egg_str


# -----------------------------------------------------------------------
#                     SCENE MATERIALS & TEXTURES
# -----------------------------------------------------------------------
def get_used_materials(objects):
    """
    Collect Materials used in the selected object.
    """
    mat_list = []
    for obj in objects:
        if obj.type != 'MESH':
            continue

        for face in obj.data.polygons:
            if face.material_index < len(obj.data.materials):
                if not obj.data.materials[face.material_index]:
                    continue
                mat_list.append(obj.data.materials[face.material_index].yabee_name)

    return set(mat_list)


def get_egg_materials_str(object_names=None):
    """
    Return the EGG string of used materials
    """
    if not object_names:
        objects = bpy.context.selected_objects
    else:
        objects = []
        for name in object_names:
            for obj in bpy.context.scene.objects:
                if obj.yabee_name == name:
                    objects.append(obj)
    if not objects:
        return ''

    mat_str = ''
    used_materials = get_used_materials(objects)
    print('INFO: Used materials: ', used_materials)

    containsPBRNodes = False
    for m_idx in used_materials:
        mat = bpy.data.materials[m_idx]
        mat_str += '<Material> %s {\n' % eggSafeName(mat.yabee_name)
        # MARK

        matIsFancyPBRNode = False
        matFancyType = 0
        nodeTree = None
        if mat and mat.use_nodes:
            nodeTree = mat.node_tree
            if nodeTree.nodes:
                matIsFancyPBRNode = True
                containsPBRNodes = True
                matFancyType = 0

        if matIsFancyPBRNode:
            if matFancyType == 0:
                if nodeTree.links[0].to_node.name == "Principled BSDF":
                    principled_bsdf = nodeTree.links[0].to_node

                    basecol = list(principled_bsdf.inputs["Base Color"].default_value)
                    metallic = principled_bsdf.inputs["Metallic"].default_value
                    roughness = principled_bsdf.inputs["Roughness"].default_value

                    base_r = basecol[0]
                    base_g = basecol[1]
                    base_b = basecol[2]
                    base_a = basecol[3]

                    mat_str += '  <Scalar> baser { %s }\n' % STRF(base_r)
                    mat_str += '  <Scalar> baseg { %s }\n' % STRF(base_g)
                    mat_str += '  <Scalar> baseb { %s }\n' % STRF(base_b)
                    mat_str += '  <Scalar> basea { %s }\n' % STRF(base_a)

                    # ("DEFAULT", "EMISSIVE", "CLEARCOAT", "TRANSPARENT","SKIN", "FOLIAGE")
                    mat_str += '  <Scalar> roughness { %s }\n' % STRF(roughness)
                    mat_str += '  <Scalar> metallic { %s }\n' % STRF(metallic)
                    mat_str += '  <Scalar> local { %s }\n' % STRF(0.0)

                elif nodeTree.links[0].to_node.name == 'Material Output':
                    print("INFO: {} is using for!".format(nodeTree.links[0].to_node.name)),
                    objects = bpy.context.selected_objects
                    if bpy.data.materials[0].node_tree is not None:
                        for node in bpy.data.materials[0].node_tree.nodes:
                            if node.name == "Principled BSDF":
                                principled_bsdf = node
                                basecol = list(principled_bsdf.inputs["Base Color"].default_value)
                                metallic = principled_bsdf.inputs["Metallic"].default_value
                                roughness = principled_bsdf.inputs["Roughness"].default_value

                                base_r = basecol[0]
                                base_g = basecol[1]
                                base_b = basecol[2]
                                base_a = basecol[3]

                                mat_str += '  <Scalar> baser { %s }\n' % STRF(base_r)
                                mat_str += '  <Scalar> baseg { %s }\n' % STRF(base_g)
                                mat_str += '  <Scalar> baseb { %s }\n' % STRF(base_b)
                                mat_str += '  <Scalar> basea { %s }\n' % STRF(base_a)

                                # ("DEFAULT", "EMISSIVE", "CLEARCOAT", "TRANSPARENT","SKIN", "FOLIAGE")
                                mat_str += '  <Scalar> roughness { %s }\n' % STRF(roughness)
                                mat_str += '  <Scalar> metallic { %s }\n' % STRF(metallic)
                                mat_str += '  <Scalar> local { %s }\n' % STRF(0.0)

        if matIsFancyPBRNode is False:
            print("INFO: Non-Shader Mode is using for!")
            if matFancyType == 0:
                for m_val in used_materials:
                    mat = bpy.data.materials[m_val]
                    if mat.use_nodes is False:
                        color = mat.diffuse_color
                        metallic = 0
                        basecol = list(color)
                        base_r = basecol[0]
                        base_g = basecol[1]
                        base_b = basecol[2]
                        # diff_a = diffcol[3]

                        mat_str += '  <Scalar> baser { %s }\n' % STRF(base_r)
                        mat_str += '  <Scalar> baseg { %s }\n' % STRF(base_g)
                        mat_str += '  <Scalar> baseb { %s }\n' % STRF(base_b)
                        # mat_str += '  <Scalar> basea { %s }\n' % STRF(base_a)

                        # ("DEFAULT", "EMISSIVE", "CLEARCOAT", "TRANSPARENT","SKIN", "FOLIAGE")
                        mat_str += '  <Scalar> roughness { %s }\n' % STRF(mat.roughness)
                        mat_str += '  <Scalar> metallic { %s }\n' % STRF(mat.metallic)
                        mat_str += '  <Scalar> local { %s }\n' % STRF(0.0)

        if TEXTURE_PROCESSOR == 'BAKE' and mat.use_nodes:
            mat_str += '  <Scalar> diffr { 1.0 }\n'
            mat_str += '  <Scalar> diffg { 1.0 }\n'
            mat_str += '  <Scalar> diffb { 1.0 }\n'

        mat_str += '}\n\n'

    used_textures = {}

    if containsPBRNodes:
        print("Found Panda3D compatible Principled BSDF shader. Collecting PBR textures")
        pbrtex = PbrTextures(objects,
                             EXPORT_UV_IMAGE_AS_TEXTURE,
                             COPY_TEX_FILES,
                             FILE_PATH, TEX_PATH)
        used_textures.update(pbrtex.get_used_textures())

    else:
        print("Panda3D compatible Principled BSDF shader not found, See Manual to create it first...")

    """if TEXTURE_PROCESSOR == 'BAKE':
        tb = TextureBaker(objects, FILE_PATH, TEX_PATH)
        used_textures.update(tb.bake(BAKE_LAYERS))"""

    for name, params in used_textures.items():
        mat_str += '<Texture> %s {\n' % eggSafeName(name)
        mat_str += '  "' + convertFileNameToPanda(params['path']) + '"\n'

        for scalar in params['scalars']:
            mat_str += ('  <Scalar> %s { %s }\n' % scalar)

        if 'transform' in params and len(params['transform']) > 0:
            mat_str += '  <Transform> {\n'
            for ttype, transform in params['transform']:
                transform = ' '.join(map(str, transform))
                mat_str += '    <%s> { %s }\n' % (ttype, transform)
            mat_str += '  }\n'
        mat_str += '}\n\n'
    return mat_str, used_materials, used_textures


# -----------------------------------------------------------------------
#                   Preparing & auxiliary functions
# -----------------------------------------------------------------------
def hierarchy_to_list(obj, hierarchy, base_filter=None):
    if base_filter:
        if obj._yabee_object.__class__ == base_filter:
            hierarchy.append(obj)
    else:
        hierarchy.append(obj)
    for child in obj.children:
        if child not in hierarchy:
            hierarchy_to_list(child, hierarchy, base_filter)


def merge_objects():
    """
    Merge objects, which armatured by single Armature.
    """
    join_to_arm = {}
    selection = []

    for selected_obj in bpy.context.selected_objects:
        # If our selected object has an armature modifier, this will be True
        to_join = False

        if selected_obj.type == 'MESH':
            for mod in selected_obj.modifiers:
                # This mesh has an armature modifier on it, therefore it is an actor.
                if mod and mod.type == 'ARMATURE':
                    # what differentiates mod.object from selected_obj.?
                    # what is mod.object?
                    if mod.object not in join_to_arm.keys():
                        join_to_arm[mod.object] = []

                    join_to_arm[mod.object].append(selected_obj)
                    to_join = True

        if not to_join:
            selection.append(selected_obj)

    # These objects are our lineup Actors
    for actor_obj in join_to_arm.values():
        bpy.ops.object.select_all(action = 'DESELECT')
        for actor_child_obj in actor_obj:
            actor_child_obj.select = True

        if len(bpy.context.selected_objects[:]) > 1:
            bpy.context.scene.objects.active = bpy.context.selected_objects[0]
            bpy.ops.object.join()

        # Build our ultimate node selection...
        selection += bpy.context.selected_objects[:]

    bpy.ops.object.select_all(action = 'DESELECT')

    for obj in selection:
        obj.select = True


def parented_to_armatured():
    """
    Convert parented to bone objects to armatured objects.
    """
    arm_objects = []
    old_selection = bpy.context.selected_objects[:]
    bpy.ops.object.select_all(action = 'DESELECT')

    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and obj.parent and obj.parent.type == 'ARMATURE' and obj.parent_bone:
            bpy.ops.object.select_all(action = 'DESELECT')
            obj.select = True
            arm = obj.parent
            bone = obj.parent_bone
            bpy.ops.object.select_hierarchy(direction = 'CHILD', extend = True)
            has_selected = [obj for obj in bpy.context.selected_objects if obj in old_selection]
            if has_selected:
                for selected_obj in has_selected:
                    arm_objects.append((selected_obj, arm, bone))

    for obj, arm, bone in arm_objects:
        modifiers = [mod.type for mod in obj.modifiers]
        if 'ARMATURE' not in modifiers:
            obj.vertex_groups.new(bone)
            obj.modifiers.new(type = 'ARMATURE', name = 'PtA')
            obj.modifiers['PtA'].object = arm
            idxs = [vtx.index for vtx in obj.data.vertices]
            obj.vertex_groups[bone].add(index = idxs, weight = 1.0, type = 'ADD')
            obj.matrix_local = obj.matrix_parent_inverse * obj.matrix_world
            obj.parent = None

    for obj in old_selection:
        obj.select = True


def reparenting_to_armature(obj_list):
    for obj in obj_list:
        for mod in obj.modifiers:
            if mod and mod.type == 'ARMATURE' and mod.show_viewport:
                if mod.object and obj.parent != mod.object:
                    print('WARNING:Reparent %s to %s' % (obj.yabee_name, mod.object.yabee_name))
                    m = Matrix(obj.matrix_world)
                    obj.parent = mod.object
                    obj.matrix_world = m


def apply_modifiers(obj_list=None):
    if not obj_list:
        obj_list = bpy.context.selected_objects

    for obj in obj_list:
        for mod in obj.modifiers:
            if mod and mod.type != 'ARMATURE' and mod.show_viewport:
                obj = bpy.context.window.scene.objects[0]
                bpy.context.view_layer.objects.active = obj
                try:
                    bpy.ops.object.modifier_apply(modifier = mod.name)
                    print('INFO: Applying modifier', mod.name)
                except:
                    print('WARNING: Can\'t apply modifier', mod.name)


def generate_shadow_uvs():
    auvs = {}
    for obj in [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']:
        auvs[obj.name] = obj.data.uv_layers.active
        if 'yabee_shadow' not in obj.data.uv_layers.keys():
            obj.data.uv_layers.new('yabee_shadow')
        # else:
        #    obj.data.uv_layers.active = obj.data.uv_layers['yabee_shadow']
        #    obj.data.uv_layers.active = obj.data.uv_layers['yabee_shadow']
    # bpy.ops.object.mode_set.poll()
    obj.data.uv_layers.active = obj.data.uv_layers['yabee_shadow']
    obj.data.update()
    bpy.ops.uv.smart_project(angle_limit = 66, island_margin = 0.03)
    for obj in [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']:
        obj.data.uv_layers.active = auvs[obj.name]
        obj.data.update()
    bpy.context.scene.update()


# -----------------------------------------------------------------------
#                           WRITE OUT
# -----------------------------------------------------------------------
def write_out(fname, anims, from_actions, uv_img_as_tex, sep_anim, a_only,
              copy_tex, t_path, tbs, tex_processor, b_layers,
              m_actor, apply_m, pview, loop_normals, export_pbs, force_export_vertex_colors, objects=None):
    global FILE_PATH, ANIMATIONS, ANIMS_FROM_ACTIONS, EXPORT_UV_IMAGE_AS_TEXTURE, \
        COPY_TEX_FILES, TEX_PATH, SEPARATE_ANIM_FILE, ANIM_ONLY, \
        STRF, CALC_TBS, TEXTURE_PROCESSOR, BAKE_LAYERS, \
        MERGE_ACTOR_MESH, APPLY_MOD, PVIEW, USED_MATERIALS, USED_TEXTURES, \
        USE_LOOP_NORMALS, EXPORT_PBS, FORCE_EXPORT_VERTEX_COLORS
    importlib.reload(sys.modules[lib_name + '.texture_processor'])
    importlib.reload(sys.modules[lib_name + '.utils'])
    errors = []
    # === prepare to write ===
    FILE_PATH = fname
    ANIMATIONS = anims
    ANIMS_FROM_ACTIONS = from_actions
    EXPORT_UV_IMAGE_AS_TEXTURE = uv_img_as_tex
    SEPARATE_ANIM_FILE = sep_anim
    ANIM_ONLY = a_only
    CALC_TBS = tbs
    COPY_TEX_FILES = copy_tex
    TEX_PATH = t_path
    TEXTURE_PROCESSOR = tex_processor
    BAKE_LAYERS = b_layers
    MERGE_ACTOR_MESH = m_actor
    APPLY_MOD = apply_m
    PVIEW = pview
    USE_LOOP_NORMALS = loop_normals
    EXPORT_PBS = export_pbs
    FORCE_EXPORT_VERTEX_COLORS = force_export_vertex_colors
    s_acc = '%.6f'

    def str_f(x):
        return s_acc % x

    STRF = str_f
    # Prepare copy of the scene.
    # Sync objects names with custom property "yabee_name" to be able to get basic object name in the copy of the scene.
    # selected_obj = [obj.name for obj in bpy.context.selected_objects if obj.type != 'ARMATURE']

    # i'm not sure if objects is ever not None
    selected_obj = objects
    if not selected_obj:
        selected_obj = [obj.name for obj in bpy.context.selected_objects]

    for obj in bpy.data.objects:
        obj.yabee_name = obj.name

    for item in (bpy.data.meshes, bpy.data.textures, bpy.data.curves, bpy.data.shape_keys, bpy.data.images):
        for obj in item:
            obj.yabee_name = obj.name

    # Looping the node tree to get texture and its name
    for mat in bpy.data.materials:
        mat.yabee_name = mat.name
        ms_names = []
        for obj in bpy.data.objects:
            for mat_slot in obj.material_slots:
                if mat_slot.material and mat_slot.material.node_tree:
                    for tex in mat_slot.material.node_tree.nodes:
                        if tex.type == 'TEX_IMAGE':
                            ms_names.append(tex.image and tex.image.name or "")

    for arm in bpy.data.armatures:
        arm.yabee_name = arm.name
        for bone in arm.bones:
            bone.yabee_name = bone.name

    for obj in bpy.context.scene.objects:
        if obj.type == 'ARMATURE':
            for bone in obj.pose.bones:
                bone.yabee_name = bone.name

    old_data = {}
    for data in (bpy.data.materials, bpy.data.objects, bpy.data.textures,
                 bpy.data.armatures, bpy.data.actions, bpy.data.brushes,
                 bpy.data.cameras, bpy.data.curves, bpy.data.collections,
                 bpy.data.images, bpy.data.lights, bpy.data.meshes,
                 bpy.data.metaballs, bpy.data.movieclips,
                 bpy.data.node_groups, bpy.data.particles, bpy.data.screens,
                 bpy.data.shape_keys, bpy.data.sounds,
                 bpy.data.speakers, bpy.data.texts, bpy.data.window_managers,
                 bpy.data.worlds, bpy.data.grease_pencils):
        old_data[data] = data[:]

    # we need this?
    precopy_obj_list = None

    if USE_LOOP_NORMALS:
        # even obj.data.copy() will not contain loop normals
        precopy_obj_list = [obj for obj in bpy.context.scene.objects if obj.yabee_name in selected_obj]

    bpy.ops.scene.new(type = 'FULL_COPY')
    try:
        obj_list = [obj for obj in bpy.context.scene.objects if obj.yabee_name in selected_obj]
        if USE_LOOP_NORMALS:
            for old, new in zip(precopy_obj_list, obj_list):
                if old.type != "MESH":
                    continue
                print("{} has custom normals!".format(
                    old.name) if old.data.has_custom_normals else "{} has no custom normals.".format(old.name))
                bpy.context.scene.objects.active = new
                bpy.ops.object.modifier_add(type = 'DATA_TRANSFER')
                bpy.context.object.modifiers["DataTransfer"].object = old
                bpy.context.object.modifiers["DataTransfer"].use_loop_data = True
                # bpy.context.object.modifiers["DataTransfer"].loop_mapping = 'POLYINTERP_LNORPROJ'
                bpy.context.object.modifiers["DataTransfer"].loop_mapping = 'TOPOLOGY'
                bpy.context.object.modifiers["DataTransfer"].data_types_loops = {'CUSTOM_NORMAL'}
                bpy.ops.object.modifier_apply(apply_as = 'DATA', modifier = "DataTransfer")
                new.data.calc_normals_split()

        if CALC_TBS == 'BLENDER':
            for obj in obj_list:
                if not hasattr(obj.data, "polygons"):
                    print('WARNING: Skipping non-geometry object:', obj.name)
                    continue

                for face in obj.data.polygons:
                    if len(face.vertices) > 4:
                        obj.modifiers.new('triangulate_for_TBS', 'TRIANGULATE')
                        print('WARNING:TBS: Triangulate %s to avoid non tris/quads polygons' % obj.yabee_name)
                        bpy.context.scene.objects.active = obj
                        bpy.ops.object.modifier_apply(modifier = 'triangulate_for_TBS')
                        break

        if APPLY_MOD:
            apply_modifiers(obj_list)

        reparenting_to_armature(obj_list)
        # parented_to_armatured()
        # if MERGE_ACTOR_MESH:
        #    merge_objects()
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode = 'OBJECT')

        # Generate UV layers for shadows
        if BAKE_LAYERS and (BAKE_LAYERS['AO'][2] or BAKE_LAYERS['shadow'][2]):
            generate_shadow_uvs()

        gr = Group(None)

        included_armature = []
        for obj in bpy.context.scene.objects:
            if obj.yabee_name in selected_obj:
                for mod in obj.modifiers:
                    if mod and mod.type == 'ARMATURE' \
                            and mod.object not in included_armature \
                            and mod.object not in obj_list:
                        included_armature.append(mod.object)
                if obj.parent and obj.parent_type == 'BONE' \
                        and obj.parent not in included_armature \
                        and obj.parent not in obj_list:
                    included_armature.append(obj.parent)

        obj_list += included_armature
        # print("DEBUG: ", obj_list)
        print('Objects for export:', [obj.yabee_name for obj in obj_list])

        errors += gr.make_hierarchy_from_list(obj_list)
        if not errors:
            # gr.print_hierarchy()
            gr.update_joints_data()

            fdir, fname = os.path.split(os.path.abspath(FILE_PATH))
            if not os.path.exists(fdir):
                print('PATH %s not exist. Trying to make path' % fdir)
                os.makedirs(fdir)

            # === write egg data ===
            print('WRITE main EGG to %s' % os.path.abspath(FILE_PATH))
            if (not ANIM_ONLY) or (not SEPARATE_ANIM_FILE):
                file = open(FILE_PATH, 'w')
            if not ANIM_ONLY:
                file.write('<CoordinateSystem> { Z-up } \n')
                materials_str, USED_MATERIALS, USED_TEXTURES = get_egg_materials_str(selected_obj)
                file.write(materials_str)
                file.write(gr.get_full_egg_str())

            anim_collectors = []
            if ANIMS_FROM_ACTIONS:
                # Export an animation for each action.
                fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base

                for action in bpy.data.actions:
                    frange = action.frame_range
                    ac = AnimCollector(obj_list, int(frange[0]), int(frange[1]) + 1, fps, action.name, action)
                    anim_collectors.append(ac)
            else:
                # Export animations named in ANIMATIONS dictionary.
                for a_name, frames in ANIMATIONS.items():
                    ac = AnimCollector(obj_list, frames[0], frames[1], frames[2], a_name)
                    anim_collectors.append(ac)

            fpa = []
            for anim_collector in anim_collectors:
                if not SEPARATE_ANIM_FILE:
                    if ANIM_ONLY:
                        file.write('<CoordinateSystem> { Z-up } \n')
                    file.write(anim_collector.get_full_egg_str())
                else:
                    anim_path = FILE_PATH
                    if anim_path[-4:].upper() == '.EGG':
                        anim_path = anim_path[:-4] + '-' + anim_collector.name + anim_path[-4:]
                    else:
                        anim_path = anim_path + '-' + anim_collector.name + '.egg'
                    a_egg_str = anim_collector.get_full_egg_str()
                    if len(a_egg_str) > 0:
                        a_file = open(anim_path, 'w')
                        a_file.write('<CoordinateSystem> { Z-up } \n')
                        a_file.write(anim_collector.get_full_egg_str())
                        a_file.close()
                        fpa.append(anim_path)

            if not ANIM_ONLY or not SEPARATE_ANIM_FILE:
                file.close()

            if CALC_TBS == 'PANDA':
                try:
                    fp = os.path.abspath(FILE_PATH)
                    for line in os.popen('egg-trans -tbnall -ps keep -o "%s" "%s"' % (fp, fp)).readlines():
                        print(line)
                except:
                    print('ERROR: Can\'t calculate TBS through panda\'s egg-trans')
            if PVIEW:
                try:
                    fp = os.path.abspath(FILE_PATH)
                    subprocess.Popen(['pview', '-i', fp] + fpa)
                except:
                    print('ERROR: Can\'t execute pview')
    except Exception as exc:
        errors.append('ERR_UNEXPECTED')
        # print('\n'.join(format_tb(exc.__traceback__)))
        print_exc()
    # Clearing the scene.
    # (!) Possible Incomplete.
    # Whenever we are deleted our copy of the scene,
    # Blender won't to delete other objects, created with the scene, so
    # we should do it by hand. I recommend to save the .blend file before
    # exporting and reload it after.
    bpy.ops.scene.delete()
    for data in old_data:
        for obj in data:
            if obj not in old_data[data]:
                # print("{} has {} users. Proceeding to clear.".format(obj.name, obj.users))
                obj.user_clear()
                try:
                    data.remove(obj, do_unlink = True)
                except:
                    print('WARNING: Can\'t delete', obj, 'from', data)
    return errors


def write_out_test(fname, anims, uv_img_as_tex, sep_anim, a_only, copy_tex,
                   t_path, tbs, tex_processor, b_layers,
                   m_actor, apply_m, pview):
    import profile
    import pstats
    wo = "write_out('%s', %s, %s, %s, %s, '%s', %s, '%s', '%s', %s, %s, %s, %s)" % \
         (fname, anims, uv_img_as_tex, sep_anim, a_only, copy_tex,
          t_path, tbs, tex_processor, b_layers,
          m_actor, apply_m, pview)
    wo = wo.replace('\\', '\\\\')
    profile.runctx(wo, globals(), {}, 'main_prof')
    stats = pstats.Stats('main_prof')
    stats.strip_dirs()
    stats.sort_stats('time')
    stats.print_stats(10)
    return True
