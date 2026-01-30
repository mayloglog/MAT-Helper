bl_info = {
    "name": "MAT Helper",
    "author": "maylog",
    "version": (1, 1, 0),
    "blender": (4, 2, 0),
    "location": "Shader Editor > Sidebar & Material Properties",
    "description": "Auto-import and link UModel .mat textures to BSDF nodes",
    "category": "Material",
}

import bpy
import os
import re
from pathlib import Path

# --- 核心处理函数 ---
def process_single_material(mat, scene, mode, tex_dir, mat_search_path):
    if not mat or not mat.use_nodes:
        return False, []
    
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    
    # 1. 寻找 .mat 文件
    clean_name = re.sub(r'\.\d+$', '', mat.name)
    search_dir = mat_search_path if mat_search_path.is_dir() else mat_search_path.parent
    target_file = search_dir / f"{clean_name}.mat"
    
    if not target_file.exists():
        try:
            found = [f for f in search_dir.glob("*.mat") if f.stem.lower() == clean_name.lower()]
            if found: target_file = found[0]
            else: return False, []
        except: return False, []
        
    # 2. 清理逻辑
    if mode != 'READ_ONLY':
        if scene.mat_helper_clear_nodes:
            nodes.clear()
            bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
            bsdf.location = (0, 0)
            out = nodes.new(type='ShaderNodeOutputMaterial')
            out.location = (300, 0)
            links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        elif scene.mat_helper_clear_links:
            links.clear()

    # 3. 解析 .mat 内容
    tex_to_types = {}
    unique_tex_order = []
    has_opacity_standard = False
    try:
        with open(target_file, 'r', encoding='utf-8') as f:
            for line in f:
                if "=" in line:
                    k, v = line.split('=', 1)
                    val, key = v.strip(), k.strip().lower()
                    if val:
                        if val not in tex_to_types:
                            tex_to_types[val] = []
                            unique_tex_order.append(val)
                        tex_to_types[val].append(key)
                        if "opacity" in key: has_opacity_standard = True
    except: return False, []

    # 4. 节点生成环境
    bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    supported_ext = {'.png', '.jpg', '.tga', '.dds', '.bmp', '.jpeg'}
    dir_files = list(tex_dir.iterdir()) if tex_dir.exists() else []
    
    current_y = 400
    missing = []
    rough_linked = any("specular" in t for types in tex_to_types.values() for t in types)
    metal_linked = any("metallic" in t for types in tex_to_types.values() for t in types)

    for tex_name in unique_tex_order:
        types = tex_to_types[tex_name]
        found_file = next((f for f in dir_files if f.stem == tex_name and f.suffix.lower() in supported_ext), None)
        
        if not found_file:
            missing.append(tex_name)
            continue

        # 场景复用检查
        img = bpy.data.images.get(found_file.name)
        if not img: img = bpy.data.images.load(str(found_file))
        
        tex_node = nodes.new(type='ShaderNodeTexImage')
        tex_node.image = img
        tex_node.location = (-1000, current_y)
        
        is_color_map = any(t in ["diffuse", "emissive"] for t in types)
        img.colorspace_settings.name = 'sRGB' if is_color_map else 'Non-Color'

        # ORM/ROM 识别并生成 Separate Color
        is_packed = re.search(r'(ORM|ROM|RMA|AO_R_M)', tex_name, re.IGNORECASE)
        if is_packed:
            sep_node = nodes.new(type='ShaderNodeSeparateColor')
            sep_node.location = (-720, current_y - 80)
            sep_node.label = "Split (R:AO G:Rough B:Metal)"
            links.new(tex_node.outputs['Color'], sep_node.inputs['Color'])
            tex_node.label = "Packed (ORM/ROM)"
            tex_node.use_custom_color = True
            tex_node.color = (0.5, 0.3, 0.8)

        # 自动连接 BSDF 逻辑
        if mode != 'READ_ONLY' and bsdf:
            if any("diffuse" in t for t in types):
                links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
                if scene.mat_helper_auto_alpha and not has_opacity_standard:
                    links.new(tex_node.outputs['Alpha'], bsdf.inputs['Alpha'])
            
            if any("emissive" in t for t in types):
                links.new(tex_node.outputs['Color'], bsdf.inputs['Emission Color'])
                if bsdf.inputs['Emission Strength'].default_value == 0.0:
                    bsdf.inputs['Emission Strength'].default_value = 1.0
            
            if any("normal" in t for t in types):
                nm = nodes.new(type='ShaderNodeNormalMap')
                nm.location = (-700, current_y)
                links.new(tex_node.outputs['Color'], nm.inputs['Color'])
                links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])

            if not is_packed:
                if any("specular" in t for t in types):
                    inv = nodes.new(type='ShaderNodeInvert')
                    inv.location = (-700, current_y)
                    links.new(tex_node.outputs['Color'], inv.inputs['Color'])
                    links.new(inv.outputs['Color'], bsdf.inputs['Roughness'])
                
                if any("metallic" in t for t in types):
                    links.new(tex_node.outputs['Color'], bsdf.inputs['Metallic'])

                # 额外后缀识别 (Fallback)
                if not is_color_map:
                    if scene.mat_helper_auto_rough and not rough_linked:
                        if re.search(r'(_r)$', tex_name, re.IGNORECASE):
                            inv = nodes.new(type='ShaderNodeInvert')
                            inv.location = (-700, current_y)
                            links.new(tex_node.outputs['Color'], inv.inputs['Color'])
                            links.new(inv.outputs['Color'], bsdf.inputs['Roughness'])
                            rough_linked = True
                    if scene.mat_helper_auto_metal and not metal_linked:
                        if re.search(r'(_m)$', tex_name, re.IGNORECASE):
                            links.new(tex_node.outputs['Color'], bsdf.inputs['Metallic'])
                            metal_linked = True

        current_y -= 320
    
    return True, missing

# --- UI 辅助绘制 ---
def draw_mat_helper_ui(self, context):
    layout = self.layout
    scene = context.scene
    
    box = layout.box()
    col = box.column(align=True)
    col.label(text="Resource Paths:", icon='FILE_FOLDER')
    col.prop(scene, "umodel_tex_dir", text="Images")
    col.prop(scene, "umodel_mat_path", text="MATs")
    
    layout.separator()
    
    box = layout.box()
    box.label(text="Smart Detection Options:", icon='VIEWZOOM')
    box.prop(scene, "mat_helper_auto_alpha", text="Auto Alpha (Diffuse)")
    box.prop(scene, "mat_helper_auto_rough", text="Suffix Detect (_R)")
    box.prop(scene, "mat_helper_auto_metal", text="Suffix Detect (_M)")

    layout.separator()
    
    box = layout.box()
    box.label(text="Cleanup (Destructive):", icon='TRASH')
    box.prop(scene, "mat_helper_clear_links", text="Clear Links")
    box.prop(scene, "mat_helper_clear_nodes", text="Clear Nodes & Textures")
    
    layout.separator()
    
    col = layout.column(align=True)
    col.label(text="Single Material:")
    row = col.row(align=True)
    row.scale_y = 1.2
    row.operator("shader.import_umodel_mat", text="Auto-Link Active", icon='NODE_SEL').mode = 'AUTO_NAME'
    row.operator("shader.import_umodel_mat", text="Nodes Only", icon='IMAGE_DATA').mode = 'READ_ONLY'
    
    layout.separator()
    
    col = layout.column(align=True)
    col.label(text="Scene Batch:")
    op = col.operator("shader.import_umodel_mat", text="Process All Materials", icon='PLAY')
    op.mode = 'BATCH_ALL'
    col.label(text="⚠ Processes every shader by name", icon='TIME')

# --- 类定义 ---
class SHADER_OT_ImportMatTextures(bpy.types.Operator):
    bl_idname = "shader.import_umodel_mat"
    bl_label = "Process MAT"
    bl_options = {'REGISTER', 'UNDO'}
    mode: bpy.props.EnumProperty(items=[('READ_ONLY', "R", ""), ('CONNECT', "C", ""), ('AUTO_NAME', "A", ""), ('BATCH_ALL', "B", "")], default='CONNECT')

    def execute(self, context):
        scene = context.scene
        tex_dir = Path(bpy.path.abspath(scene.umodel_tex_dir))
        mat_path_raw = Path(bpy.path.abspath(scene.umodel_mat_path))

        if not scene.umodel_mat_path or not scene.umodel_tex_dir:
            self.report({'ERROR'}, "Paths missing"); return {'CANCELLED'}

        mats = [m for m in bpy.data.materials if m.use_nodes] if self.mode == 'BATCH_ALL' else [context.active_object.active_material] if (context.active_object and context.active_object.active_material) else []
        
        success_count = 0
        all_missing = {}
        for mat in mats:
            success, missing = process_single_material(mat, scene, self.mode, tex_dir, mat_path_raw)
            if success:
                success_count += 1
                if missing: all_missing[mat.name] = missing
        
        if all_missing:
            print("\n--- MISSING TEXTURES REPORT ---")
            for m, files in all_missing.items(): print(f"[{m}]: {', '.join(files)}")
            self.report({'WARNING'}, "Check console for missing files.")
            
        self.report({'INFO'}, f"Done: {success_count} materials.")
        return {'FINISHED'}

class SHADER_PT_MatHelperSidebar(bpy.types.Panel):
    bl_label = "MAT Helper"
    bl_idname = "SHADER_PT_mat_helper_sidebar"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "MAT Helper"
    def draw(self, context): draw_mat_helper_ui(self, context)

class SHADER_PT_MatHelperMaterial(bpy.types.Panel):
    bl_label = "MAT Helper"
    bl_idname = "SHADER_PT_mat_helper_material"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    def draw(self, context): draw_mat_helper_ui(self, context)

classes = (SHADER_OT_ImportMatTextures, SHADER_PT_MatHelperSidebar, SHADER_PT_MatHelperMaterial)

def register():
    for cls in classes: bpy.utils.register_class(cls)
    s = bpy.types.Scene
    s.umodel_mat_path = bpy.props.StringProperty(name="MAT Path", subtype='FILE_PATH')
    s.umodel_tex_dir = bpy.props.StringProperty(name="Texture Path", subtype='DIR_PATH')
    s.mat_helper_auto_alpha = bpy.props.BoolProperty(name="Alpha Link", default=True)
    s.mat_helper_auto_rough = bpy.props.BoolProperty(name="Suffix Rough", default=True)
    s.mat_helper_auto_metal = bpy.props.BoolProperty(name="Suffix Metal", default=True)
    s.mat_helper_clear_links = bpy.props.BoolProperty(name="Clear Links", default=False)
    s.mat_helper_clear_nodes = bpy.props.BoolProperty(name="Clear Nodes", default=False)

def unregister():
    for cls in reversed(classes): bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()