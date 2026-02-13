bl_info = {
    "name": "MAT Helper",
    "author": "maylog",
    "version": (1, 2, 0),
    "blender": (4, 2, 0),
    "location": "Shader Editor > Sidebar & Material Properties",
    "description": "Smart PBR texture importer for UModel .mat & .json exports",
    "category": "Material",
}

import bpy
import os
import re
import json
from pathlib import Path

# --- 数据解析函数 ---

def parse_mat_file(file_path):
    tex_to_types = {}
    unique_tex_order = []
    has_opacity = False
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if "=" in line:
                    k, v = line.split('=', 1)
                    val, key = v.strip(), k.strip().lower()
                    if val:
                        if val not in tex_to_types:
                            tex_to_types[val] = []
                            unique_tex_order.append(val)
                        tex_to_types[val].append(key)
                        if "opacity" in key: has_opacity = True
    except: pass
    return tex_to_types, unique_tex_order, has_opacity

def parse_json_file(file_path):
    tex_to_types = {}
    unique_tex_order = []
    has_opacity = False
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            textures = data.get("Textures", {})
            for key, path_str in textures.items():
                tex_name = path_str.split('.')[-1]
                key_lower = key.lower()
                if tex_name not in tex_to_types:
                    tex_to_types[tex_name] = []
                    unique_tex_order.append(tex_name)
                tex_to_types[tex_name].append(key_lower)
                if "opacity" in key_lower: has_opacity = True
    except: pass
    return tex_to_types, unique_tex_order, has_opacity

# --- 核心连接逻辑 ---

def process_material_data(mat, scene, tex_to_types, unique_tex_order, has_opacity_standard, tex_dir, mode):
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    
    # 自动清理逻辑
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

    bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    supported_ext = {'.png', '.jpg', '.tga', '.dds', '.bmp', '.jpeg'}
    dir_files = list(tex_dir.iterdir()) if tex_dir.exists() else []
    
    current_y = 400
    rough_linked = any("specular" in t for types in tex_to_types.values() for t in types)
    metal_linked = any("metallic" in t for types in tex_to_types.values() for t in types)

    for tex_name in unique_tex_order:
        types = tex_to_types[tex_name]
        found_file = next((f for f in dir_files if f.stem == tex_name and f.suffix.lower() in supported_ext), None)
        
        if not found_file:
            print(f"[MAT Helper] Missing: {tex_name}")
            continue

        # 场景复用
        img = bpy.data.images.get(found_file.name)
        if not img: img = bpy.data.images.load(str(found_file))
        
        tex_node = nodes.new(type='ShaderNodeTexImage')
        tex_node.image = img
        tex_node.location = (-1000, current_y)
        
        is_color_map = any(t in ["diffuse", "emissive", "color", "hitomi", "white"] for t in types)
        img.colorspace_settings.name = 'sRGB' if is_color_map else 'Non-Color'

        # 复合贴图识别
        is_packed = re.search(r'(ORM|ROM|RMA|AO_R_M|NRRO|MSD)', tex_name, re.IGNORECASE)
        if is_packed:
            sep_node = nodes.new(type='ShaderNodeSeparateColor')
            sep_node.location = (-720, current_y - 80)
            sep_node.label = "Split (R:AO G:Rough B:Metal)"
            links.new(tex_node.outputs['Color'], sep_node.inputs['Color'])
            tex_node.label = "Packed Map"
            tex_node.use_custom_color = True
            tex_node.color = (0.5, 0.3, 0.8)

        if mode != 'READ_ONLY' and bsdf:
            if any(t in ["diffuse", "color", "hitomi", "white"] for t in types):
                links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
                if scene.mat_helper_auto_alpha and not has_opacity_standard:
                    links.new(tex_node.outputs['Alpha'], bsdf.inputs['Alpha'])
            
            if any("emissive" in t for t in types):
                links.new(tex_node.outputs['Color'], bsdf.inputs['Emission Color'])
                bsdf.inputs['Emission Strength'].default_value = 1.0
            
            if any(t in ["normal", "pm_normals", "nrm"] for t in types):
                nm = nodes.new(type='ShaderNodeNormalMap')
                nm.location = (-700, current_y)
                links.new(tex_node.outputs['Color'], nm.inputs['Color'])
                links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])

            if not is_packed:
                if any(t in ["specular", "pm_specularmasks", "s"] for t in types):
                    inv = nodes.new(type='ShaderNodeInvert')
                    inv.location = (-700, current_y)
                    links.new(tex_node.outputs['Color'], inv.inputs['Color'])
                    links.new(inv.outputs['Color'], bsdf.inputs['Roughness'])
                if any("metallic" in t for t in types):
                    links.new(tex_node.outputs['Color'], bsdf.inputs['Metallic'])
                
                # 额外后缀识别
                if not is_color_map:
                    if scene.mat_helper_auto_rough and not rough_linked:
                        if re.search(r'(_r)$', tex_name, re.IGNORECASE):
                            links.new(tex_node.outputs['Color'], bsdf.inputs['Roughness'])
                    if scene.mat_helper_auto_metal and not metal_linked:
                        if re.search(r'(_m)$', tex_name, re.IGNORECASE):
                            links.new(tex_node.outputs['Color'], bsdf.inputs['Metallic'])

        current_y -= 320

# --- 操作符 ---

class SHADER_OT_ImportMatTextures(bpy.types.Operator):
    bl_idname = "shader.import_umodel_mat"
    bl_label = "Process Material"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(items=[('READ_ONLY', "R", ""), ('AUTO_NAME', "A", ""), ('BATCH_ALL', "B", "")], default='AUTO_NAME')
    source_choice: bpy.props.EnumProperty(items=[('MAT', ".MAT", ""), ('JSON', ".JSON", "")], name="Select Source", default='MAT')

    def draw(self, context):
        self.layout.label(text="Both .mat and .json found. Select one:")
        self.layout.prop(self, "source_choice", expand=True)

    def invoke(self, context, event):
        scene = context.scene
        if self.mode == 'BATCH_ALL': return self.execute(context)
        
        obj = context.active_object
        if obj and obj.active_material and scene.umodel_mat_path and scene.umodel_json_path:
            clean_name = re.sub(r'\.\d+$', '', obj.active_material.name)
            mat_p = Path(bpy.path.abspath(scene.umodel_mat_path))
            json_p = Path(bpy.path.abspath(scene.umodel_json_path))
            has_mat = (mat_p / f"{clean_name}.mat").exists() or mat_p.suffix == '.mat'
            has_json = (json_p / f"{clean_name}.json").exists() or json_p.suffix == '.json'
            if has_mat and has_json:
                return context.window_manager.invoke_props_dialog(self)
        return self.execute(context)

    def execute(self, context):
        scene = context.scene
        tex_dir = Path(bpy.path.abspath(scene.umodel_tex_dir))
        mat_base = Path(bpy.path.abspath(scene.umodel_mat_path)) if scene.umodel_mat_path else None
        json_base = Path(bpy.path.abspath(scene.umodel_json_path)) if scene.umodel_json_path else None

        mats = [m for m in bpy.data.materials if m.use_nodes] if self.mode == 'BATCH_ALL' else [context.active_object.active_material] if (context.active_object and context.active_object.active_material) else []
        
        for mat in mats:
            clean_name = re.sub(r'\.\d+$', '', mat.name)
            t_to_type, order, opac = {}, [], False
            
            # 决策逻辑
            use_json = False
            if json_base:
                target_json = json_base if json_base.suffix == '.json' else (json_base / f"{clean_name}.json")
                if target_json.exists():
                    if not mat_base or self.source_choice == 'JSON': use_json = True
            
            if use_json:
                target = json_base if json_base.suffix == '.json' else (json_base / f"{clean_name}.json")
                t_to_type, order, opac = parse_json_file(target)
            elif mat_base:
                target = mat_base if mat_base.suffix == '.mat' else (mat_base / f"{clean_name}.mat")
                if target.exists():
                    t_to_type, order, opac = parse_mat_file(target)
            
            if t_to_type:
                process_material_data(mat, scene, t_to_type, order, opac, tex_dir, self.mode)
        
        return {'FINISHED'}

# --- UI 面板 ---

def draw_mat_helper_ui(self, context):
    layout = self.layout
    scene = context.scene
    
    col = layout.column(align=True)
    col.label(text="Paths:", icon='FILE_FOLDER')
    col.prop(scene, "umodel_tex_dir", text="Textures")
    col.prop(scene, "umodel_mat_path", text="MAT Path")
    col.prop(scene, "umodel_json_path", text="JSON Path")
    
    layout.separator()
    box = layout.box()
    box.label(text="Options:", icon='SETTINGS')
    box.prop(scene, "mat_helper_auto_alpha", text="Auto Alpha")
    box.prop(scene, "mat_helper_auto_rough", text="Detect _R")
    box.prop(scene, "mat_helper_auto_metal", text="Detect _M")
    
    layout.separator()
    box = layout.box()
    box.label(text="Cleanup (Before Import):", icon='TRASH')
    box.prop(scene, "mat_helper_clear_links", text="Clear Links")
    box.prop(scene, "mat_helper_clear_nodes", text="Clear All Nodes")

    layout.separator()
    col = layout.column(align=True)
    row = col.row(align=True)
    row.scale_y = 1.5
    row.operator("shader.import_umodel_mat", text="Link Active", icon='NODE_SEL').mode = 'AUTO_NAME'
    row.operator("shader.import_umodel_mat", text="Batch All", icon='PLAY').mode = 'BATCH_ALL'
    col.label(text="* For best results, keep files in same directory.", icon='INFO')

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
    s.umodel_json_path = bpy.props.StringProperty(name="JSON Path", subtype='FILE_PATH')
    s.umodel_tex_dir = bpy.props.StringProperty(name="Texture Path", subtype='DIR_PATH')
    s.mat_helper_auto_alpha = bpy.props.BoolProperty(default=True)
    s.mat_helper_auto_rough = bpy.props.BoolProperty(default=True)
    s.mat_helper_auto_metal = bpy.props.BoolProperty(default=True)
    s.mat_helper_clear_links = bpy.props.BoolProperty(default=False)
    s.mat_helper_clear_nodes = bpy.props.BoolProperty(default=False)

def unregister():
    for cls in reversed(classes): bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()