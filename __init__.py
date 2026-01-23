bl_info = {
    "name": "MAT Helper",
    "author": "maylog",
    "version": (1, 0, 4),
    "blender": (4, 2, 0),
    "location": "Shader Editor > Sidebar & Material Properties",
    "description": "Smart PBR texture importer with Packed map support",
    "category": "Material",
}

import bpy
import os
import re
from pathlib import Path

class SHADER_OT_ImportMatTextures(bpy.types.Operator):
    """Import textures with smart shared-map and Packed map logic"""
    bl_idname = "shader.import_umodel_mat"
    bl_label = "Process MAT"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        items=[
            ('READ_ONLY', "Read Only", "Import nodes without linking"),
            ('CONNECT', "Read and Connect", "Manual selection and link"),
            ('AUTO_NAME', "Auto by Name", "Match .mat with Material name"),
        ],
        default='CONNECT'
    )

    def execute(self, context):
        scene = context.scene
        obj = context.active_object
        
        if not obj or not obj.active_material or not obj.active_material.use_nodes:
            self.report({'ERROR'}, "No active material found.")
            return {'CANCELLED'}
        
        raw_manual_path = scene.umodel_mat_path.strip()
        if not raw_manual_path:
            self.report({'ERROR'}, "Please specify a MAT path first.")
            return {'CANCELLED'}

        tex_dir = Path(bpy.path.abspath(scene.umodel_tex_dir))
        p = Path(bpy.path.abspath(raw_manual_path))
        
        # 1. Path Resolution
        if self.mode == 'AUTO_NAME':
            search_dir = p if p.is_dir() else p.parent
            clean_name = re.sub(r'\.\d+$', '', obj.active_material.name)
            target_file = search_dir / f"{clean_name}.mat"
            if not target_file.exists():
                try:
                    found = [f for f in search_dir.glob("*.mat") if f.stem.lower() == clean_name.lower()]
                    if found: target_file = found[0]
                except: pass
            if not target_file.exists():
                self.report({'ERROR'}, f"File not found: {clean_name}.mat")
                return {'CANCELLED'}
            mat_path = target_file
        else:
            mat_path = p if p.suffix.lower() == ".mat" else p.with_suffix(".mat")

        if not mat_path.exists():
            self.report({'ERROR'}, f"Path does not exist: {mat_path}")
            return {'CANCELLED'}

        # 2. Advanced Parse
        tex_to_types = {} 
        unique_tex_order = []
        has_opacity_standard = False

        try:
            with open(mat_path, 'r', encoding='utf-8') as f:
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
        except Exception as e:
            self.report({'ERROR'}, f"Parse error: {str(e)}")
            return {'CANCELLED'}

        # 3. Setup Node Environment
        mat = obj.active_material
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
        supported_ext = {'.png', '.jpg', '.tga', '.dds', '.bmp', '.jpeg'}
        
        if not tex_dir.exists():
            self.report({'ERROR'}, "Image Location is invalid.")
            return {'CANCELLED'}
        dir_files = list(tex_dir.iterdir())

        current_y = 400
        rough_linked = any("specular" in t for types in tex_to_types.values() for t in types)
        metal_linked = any("metallic" in t for types in tex_to_types.values() for t in types)

        # 4. Process unique textures
        for tex_name in unique_tex_order:
            types = tex_to_types[tex_name]
            found_file = next((f for f in dir_files if f.stem == tex_name and f.suffix.lower() in supported_ext), None)
            
            if found_file:
                tex_node = nodes.new(type='ShaderNodeTexImage')
                img = bpy.data.images.load(str(found_file))
                tex_node.image = img
                tex_node.location = (-1000, current_y)
                
                # Logic: Color maps (Diffuse, Emissive) use sRGB
                is_color_map = any(t in ["diffuse", "emissive"] for t in types)
                img.colorspace_settings.name = 'sRGB' if is_color_map else 'Non-Color'

                if self.mode != 'READ_ONLY' and bsdf:
                    # --- NEW: Separate Color for Packed Maps (ORM/MRO/RMA) ---
                    upper_name = tex_name.upper()
                    is_packed = any(suffix in upper_name for suffix in ["_ORM", "_MRO", "_RMA", "_MSK", "_MEP"])
                    
                    if scene.mat_helper_auto_sep_color and is_packed:
                        sep_node = nodes.new(type='ShaderNodeSeparateColor')
                        sep_node.location = (-700, current_y)
                        links.new(tex_node.outputs['Color'], sep_node.inputs['Color'])
                        tex_node.label = "Packed Texture"
                    
                    # A. Diffuse Handling
                    if any("diffuse" in t for t in types):
                        links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
                        if scene.mat_helper_auto_alpha and not has_opacity_standard:
                            links.new(tex_node.outputs['Alpha'], bsdf.inputs['Alpha'])
                    
                    # B. Emissive Handling
                    if any("emissive" in t for t in types):
                        links.new(tex_node.outputs['Color'], bsdf.inputs['Emission Color'])
                        if bsdf.inputs['Emission Strength'].default_value == 0.0:
                            bsdf.inputs['Emission Strength'].default_value = 1.0
                    
                    # C. Specular/Roughness Handling (Skip if it's a packed map we just separated)
                    if any("specular" in t for t in types) and not is_packed:
                        inv = nodes.new(type='ShaderNodeInvert')
                        inv.location = (-700, current_y)
                        links.new(tex_node.outputs['Color'], inv.inputs['Color'])
                        links.new(inv.outputs['Color'], bsdf.inputs['Roughness'])
                    
                    # D. Other Slots
                    if any("opacity" in t for t in types):
                        links.new(tex_node.outputs['Color'], bsdf.inputs['Alpha'])
                    if any("metallic" in t for t in types) and not is_packed:
                        links.new(tex_node.outputs['Color'], bsdf.inputs['Metallic'])
                    if any("normal" in t for t in types):
                        nm = nodes.new(type='ShaderNodeNormalMap')
                        nm.location = (-700, current_y)
                        links.new(tex_node.outputs['Color'], nm.inputs['Color'])
                        links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])

                    # E. Suffix logic (Fallback)
                    if not is_color_map and not is_packed: 
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

        self.report({'INFO'}, f"Successfully loaded: {mat_path.name}")
        return {'FINISHED'}

# --- Shared UI Drawing ---
def draw_mat_helper_ui(self, context):
    layout = self.layout
    scene = context.scene
    box = layout.box()
    col = box.column(align=True)
    col.label(text="Image Location:")
    col.prop(scene, "umodel_tex_dir", text="")
    col.separator()
    col.label(text="MAT Path (File or Folder):")
    col.prop(scene, "umodel_mat_path", text="")
    
    col = layout.column(align=True)
    col.prop(scene, "mat_helper_auto_alpha", text="Diffuse.Alpha -> Alpha")
    col.prop(scene, "mat_helper_auto_sep_color", text="Auto Separate Packed Map (_ORM...)")
    col.prop(scene, "mat_helper_auto_rough", text="Suffix _R -> Roughness")
    col.prop(scene, "mat_helper_auto_metal", text="Suffix _M -> Metallic")
    
    layout.separator(factor=1.5)
    col = layout.column(align=True)
    row = col.row()
    row.scale_y = 1.8
    row.operator("shader.import_umodel_mat", text="Auto-Link by Name", icon='SOLO_ON').mode = 'AUTO_NAME'
    col.separator()
    col.operator("shader.import_umodel_mat", text="Read and Connect (Manual)", icon='NODE_SEL').mode = 'CONNECT'
    col.operator("shader.import_umodel_mat", text="Read Nodes Only", icon='IMAGE_DATA').mode = 'READ_ONLY'

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
    bpy.types.Scene.umodel_mat_path = bpy.props.StringProperty(name="MAT Path", subtype='FILE_PATH')
    bpy.types.Scene.umodel_tex_dir = bpy.props.StringProperty(name="Texture Path", subtype='DIR_PATH')
    bpy.types.Scene.mat_helper_auto_alpha = bpy.props.BoolProperty(name="Alpha Link", default=True)
    bpy.types.Scene.mat_helper_auto_sep_color = bpy.props.BoolProperty(name="Sep Color Packed", default=True)
    bpy.types.Scene.mat_helper_auto_rough = bpy.props.BoolProperty(name="Suffix Rough", default=True)
    bpy.types.Scene.mat_helper_auto_metal = bpy.props.BoolProperty(name="Suffix Metal", default=True)

def unregister():
    for cls in reversed(classes): bpy.utils.unregister_class(cls)
    del bpy.types.Scene.umodel_mat_path
    del bpy.types.Scene.umodel_tex_dir
    del bpy.types.Scene.mat_helper_auto_alpha
    del bpy.types.Scene.mat_helper_auto_sep_color
    del bpy.types.Scene.mat_helper_auto_rough
    del bpy.types.Scene.mat_helper_auto_metal

if __name__ == "__main__":
    register()