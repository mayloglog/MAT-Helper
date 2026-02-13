# MAT Helper

**MAT Helper** is a specialized utility designed for technical artists and modders who work with **UModel (UE Viewer)** exports. It automates the tedious process of manual texture importing and shader node setup, bridging the gap between raw data and Blender’s Principled BSDF.

## Key Features

* **One-Click Batch Import:** Read `.mat`/`.JSON` configuration files and automatically load all referenced textures from a specified directory.
* **Smart Node Linking:**
    * **Diffuse** maps are automatically connected to the **Base Color** slot.
    * **Metallic** maps are linked to the **Metallic** slot.
    * **Normal** maps automatically create a **Normal Map node** and link to the **Normal** slot.
    * **Specular** maps are smartly processed through an **Invert node** and linked to the **Roughness** slot, matching common game engine workflows.
* **Automated Color Space Management:** Automatically sets **sRGB** for Diffuse maps and **Non-Color** for Normal, Metallic, and Specular maps to ensure PBR accuracy.
* **Clean Workflow:** Nodes are generated using their original filenames as labels and organized vertically for better readability.
* **Blender 4.2+ Ready:** Fully compatible with the latest Blender Extension system and API.

## How to Use

1.  Open the **Shader Editor** and find the **MAT Helper** tab in the Sidebar (N-panel).
2.  **MAT File Path:** Select your exported `.mat`/`.JSON` file.
3.  **Image Location:** Select the folder containing your texture images.
4.  Click **Read and Connect** to generate a full shader setup, or **Read Only** to just import the nodes into the workspace.

* For best results, it is recommended to keep all texture files and .mat files in the same directory for automatic detection.
