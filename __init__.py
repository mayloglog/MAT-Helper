bl_info = {
    "name": "MAT Helper",
    "author": "maylog",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "Shader Editor > Sidebar > MAT Helper",
    "description": "Auto-import and link UModel .mat textures to BSDF nodes",
    "category": "Node",
}

import bpy
import os
from pathlib import Path

# --- 核心逻辑类 ---
class SHADER_OT_ImportMatTextures(bpy.types.Operator):
    """读取 .mat 文件并导入贴图"""
    bl_idname = "shader.import_umodel_mat"
    bl_label = "Import Textures"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        items=[
            ('READ_ONLY', "Read Only", ""),
            ('CONNECT', "Read and Connect", ""),
        ],
        default='CONNECT'
    )

    def execute(self, context):
        scene = context.scene
        mat_path = Path(bpy.path.abspath(scene.umodel_mat_path))
        tex_dir = Path(bpy.path.abspath(scene.umodel_tex_dir))

        if not mat_path.exists() or not tex_dir.exists():
            self.report({'ERROR'}, "Invalid Path: Check your MAT file and Image directory.")
            return {'CANCELLED'}

        # 1. 解析 .mat 文件
        tex_mapping = {}
        try:
            with open(mat_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if "=" in line:
                        key, val = line.split('=', 1)
                        clean_val = val.strip()
                        if clean_val:
                            tex_mapping[clean_val] = key.strip().lower()
        except Exception as e:
            self.report({'ERROR'}, f"Read error: {str(e)}")
            return {'CANCELLED'}

        # 2. 检查活动材质
        obj = context.active_object
        if not obj or not obj.active_material or not obj.active_material.use_nodes:
            self.report({'ERROR'}, "No active material found.")
            return {'CANCELLED'}

        mat = obj.active_material
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
        
        supported_ext = {'.png', '.jpg', '.tga', '.dds', '.bmp', '.jpeg'}
        start_x, start_y = -1000, 400
        count = 0
        dir_files = list(tex_dir.iterdir())

        # 3. 处理贴图
        for tex_name, tex_type in tex_mapping.items():
            found_file = next((f for f in dir_files if f.stem == tex_name and f.suffix.lower() in supported_ext), None)
            
            if found_file:
                tex_node = nodes.new(type='ShaderNodeTexImage')
                img = bpy.data.images.load(str(found_file))
                tex_node.image = img
                tex_node.label = "" 
                tex_node.location = (start_x, start_y)
                
                # 颜色空间逻辑
                is_color = "diffuse" in tex_type
                img.colorspace_settings.name = 'sRGB' if is_color else 'Non-Color'

                if self.mode == 'CONNECT' and bsdf:
                    if "diffuse" in tex_type:
                        links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
                    elif "specular" in tex_type:
                        inv = nodes.new(type='ShaderNodeInvert')
                        inv.location = (start_x + 300, start_y)
                        links.new(tex_node.outputs['Color'], inv.inputs['Color'])
                        links.new(inv.outputs['Color'], bsdf.inputs['Roughness'])
                    elif "metallic" in tex_type:
                        links.new(tex_node.outputs['Color'], bsdf.inputs['Metallic'])
                    elif "normal" in tex_type:
                        nm = nodes.new(type='ShaderNodeNormalMap')
                        nm.location = (start_x + 300, start_y)
                        links.new(tex_node.outputs['Color'], nm.inputs['Color'])
                        links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
                
                start_y -= 320
                count += 1

        self.report({'INFO'}, f"Successfully processed {count} textures.")
        return {'FINISHED'}

# --- UI 界面类 ---
class SHADER_PT_MatHelperPanel(bpy.types.Panel):
    bl_label = "MAT Helper"
    bl_idname = "SHADER_PT_mat_helper"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "MAT Helper"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # --- 路径输入区 ---
        # 标签和路径框分行，实现路径框占满宽度
        col = layout.column(align=True)
        col.label(text="mat:")
        col.prop(scene, "umodel_mat_path", text="")

        layout.separator()

        col = layout.column(align=True)
        col.label(text="Image Location:")
        col.prop(scene, "umodel_tex_dir", text="")

        layout.separator(factor=2.0)

        # --- 按钮操作区 ---
        # 仅读取按钮
        row_read = layout.row()
        op_read = row_read.operator("shader.import_umodel_mat", text="Read Only", icon='IMAGE_DATA')
        op_read.mode = 'READ_ONLY'

        layout.separator()

        # 读取并连线按钮 (加高显示)
        row_conn = layout.row()
        row_conn.scale_y = 1.6
        op_conn = row_conn.operator("shader.import_umodel_mat", icon='NODE_SEL', text="Read and Connect")
        op_conn.mode = 'CONNECT'

# --- 注册 ---
classes = (
    SHADER_OT_ImportMatTextures,
    SHADER_PT_MatHelperPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.umodel_mat_path = bpy.props.StringProperty(name="MAT Path", subtype='FILE_PATH')
    bpy.types.Scene.umodel_tex_dir = bpy.props.StringProperty(name="Texture Path", subtype='DIR_PATH')

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.umodel_mat_path
    del bpy.types.Scene.umodel_tex_dir

if __name__ == "__main__":
    register()