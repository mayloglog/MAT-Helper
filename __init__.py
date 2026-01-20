bl_info = {
    "name": "MAT Helper",
    "author": "maylog",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "Shader Editor > Sidebar > MAT Helper",
    "description": "Automated texture import and node linking for UModel .mat files",
    "warning": "",
    "doc_url": "",
    "category": "Node",
}

import bpy
import os
from pathlib import Path

# --- 核心逻辑类 ---
class SHADER_OT_ImportMatTextures(bpy.types.Operator):
    """Import textures from a .mat file and optionally link them to Principled BSDF"""
    bl_idname = "shader.import_umodel_mat"
    bl_label = "Import and Process Textures"
    bl_options = {'REGISTER', 'UNDO'}

    # 模式选择：仅读取 或 读取并连线
    mode: bpy.props.EnumProperty(
        items=[
            ('READ_ONLY', "Read Only", "Import texture nodes without linking"),
            ('CONNECT', "Read and Connect", "Import and link to Principled BSDF"),
        ],
        name="Import Mode",
        default='CONNECT'
    )

    def execute(self, context):
        scene = context.scene
        
        # 1. 路径验证
        if not scene.umodel_mat_path or not scene.umodel_tex_dir:
            self.report({'ERROR'}, "Please specify both MAT file and Texture directory.")
            return {'CANCELLED'}

        mat_path = Path(bpy.path.abspath(scene.umodel_mat_path))
        tex_dir = Path(bpy.path.abspath(scene.umodel_tex_dir))

        if not mat_path.exists():
            self.report({'ERROR'}, f"MAT file not found: {mat_path}")
            return {'CANCELLED'}
        if not tex_dir.exists():
            self.report({'ERROR'}, f"Texture directory not found: {tex_dir}")
            return {'CANCELLED'}

        # 2. 获取目标材质
        obj = context.active_object
        if not obj or not obj.active_material or not obj.active_material.use_nodes:
            self.report({'ERROR'}, "Active object must have a material with 'Use Nodes' enabled.")
            return {'CANCELLED'}

        mat = obj.active_material
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # 3. 解析 .mat 文件
        tex_mapping = {}
        try:
            with open(mat_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if "=" in line:
                        parts = line.split('=', 1)
                        if len(parts) == 2:
                            key, val = parts
                            clean_val = val.strip()
                            if clean_val:
                                tex_mapping[clean_val] = key.strip().lower()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to parse .mat file: {str(e)}")
            return {'CANCELLED'}

        if not tex_mapping:
            self.report({'WARNING'}, "No texture data found in .mat file.")
            return {'FINISHED'}

        # 4. 准备处理
        bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
        supported_ext = {'.png', '.jpg', '.tga', '.dds', '.bmp', '.jpeg', '.tiff'}
        
        # 预先扫描目录以提高性能
        try:
            dir_files = list(tex_dir.iterdir())
        except Exception as e:
            self.report({'ERROR'}, f"Access denied to directory: {str(e)}")
            return {'CANCELLED'}

        start_x, start_y = -1100, 400
        count = 0

        # 5. 执行导入
        for tex_name, tex_type in tex_mapping.items():
            # 查找匹配文件
            found_file = next((f for f in dir_files if f.stem == tex_name and f.suffix.lower() in supported_ext), None)
            
            if found_file:
                # 如果已存在同名节点则删除（可选，保持工作区干净）
                # for n in nodes:
                #     if n.type == 'TEX_IMAGE' and n.image and n.image.name.startswith(tex_name):
                #         nodes.remove(n)

                tex_node = nodes.new(type='ShaderNodeTexImage')
                try:
                    img = bpy.data.images.load(str(found_file))
                    tex_node.image = img
                except Exception as e:
                    self.report({'WARNING'}, f"Could not load {found_file.name}: {e}")
                    continue

                tex_node.location = (start_x, start_y)
                
                # 颜色空间设定
                is_diffuse = "diffuse" in tex_type
                img.colorspace_settings.name = 'sRGB' if is_diffuse else 'Non-Color'

                # 自动连线逻辑
                if self.mode == 'CONNECT' and bsdf:
                    if is_diffuse:
                        links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
                    
                    elif "specular" in tex_type:
                        inv = nodes.new(type='ShaderNodeInvert')
                        inv.location = (start_x + 300, start_y)
                        links.new(tex_node.outputs['Color'], inv.inputs['Color'])
                        # 4.0+ 版本 Roughness 索引通常正确，使用名称引用更安全
                        if 'Roughness' in bsdf.inputs:
                            links.new(inv.outputs['Color'], bsdf.inputs['Roughness'])
                    
                    elif "metallic" in tex_type:
                        if 'Metallic' in bsdf.inputs:
                            links.new(tex_node.outputs['Color'], bsdf.inputs['Metallic'])

                    elif "normal" in tex_type:
                        nm_node = nodes.new(type='ShaderNodeNormalMap')
                        nm_node.location = (start_x + 300, start_y)
                        links.new(tex_node.outputs['Color'], nm_node.inputs['Color'])
                        if 'Normal' in bsdf.inputs:
                            links.new(nm_node.outputs['Normal'], bsdf.inputs['Normal'])
                
                start_y -= 320
                count += 1

        self.report({'INFO'}, f"MAT Helper: Imported {count} textures.")
        return {'FINISHED'}

# --- UI 界面类 ---
class SHADER_PT_MatHelperPanel(bpy.types.Panel):
    """Panel in the Shader Editor N-panel"""
    bl_label = "MAT Helper"
    bl_idname = "SHADER_PT_mat_helper"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "MAT Helper"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # 路径配置区
        box = layout.box()
        col = box.column(align=True)
        col.label(text="MAT File Path:", icon='FILE_TEXT')
        col.prop(scene, "umodel_mat_path", text="")
        
        layout.separator()
        
        col = box.column(align=True)
        col.label(text="Image Location:", icon='FILE_FOLDER')
        col.prop(scene, "umodel_tex_dir", text="")

        layout.separator(factor=1.5)

        # 动作区
        col = layout.column(align=True)
        
        # 仅读取
        op_read = col.operator(SHADER_OT_ImportMatTextures.bl_idname, text="Read Only", icon='IMAGE_DATA')
        op_read.mode = 'READ_ONLY'
        
        layout.separator()
        
        # 读取并连线 (高亮显示)
        op_conn = layout.operator(SHADER_OT_ImportMatTextures.bl_idname, text="Read and Connect", icon='NODE_SEL')
        op_conn.mode = 'CONNECT'
        layout.active_default_key_config = False # 占位，确保 row.scale_y 生效
        
        # 使用 row 缩放按钮高度
        row = layout.row()
        row.scale_y = 1.6
        # 重新定义主操作按钮以便应用缩放
        op = row.operator(SHADER_OT_ImportMatTextures.bl_idname, text="Read and Connect", icon='NODE_SEL')
        op.mode = 'CONNECT'

# --- 注册 ---
def register():
    bpy.utils.register_class(SHADER_OT_ImportMatTextures)
    bpy.utils.register_class(SHADER_PT_MatHelperPanel)
    
    bpy.types.Scene.umodel_mat_path = bpy.props.StringProperty(
        name="MAT Path",
        description="Select the .mat file exported from UModel",
        subtype='FILE_PATH'
    )
    bpy.types.Scene.umodel_tex_dir = bpy.props.StringProperty(
        name="Texture Path",
        description="Select the folder containing images",
        subtype='DIR_PATH'
    )

def unregister():
    bpy.utils.unregister_class(SHADER_OT_ImportMatTextures)
    bpy.utils.unregister_class(SHADER_PT_MatHelperPanel)
    del bpy.types.Scene.umodel_mat_path
    del bpy.types.Scene.umodel_tex_dir

if __name__ == "__main__":
    register()