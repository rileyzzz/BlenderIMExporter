# BlenderIMExporter
A WIP, modern, post-2.8 indexed mesh exporter for Trainz and the Auran JET engine.

This exporter is designed to be a replacement for the well-used legacy exporter written by USCHI0815 (Torsten), which became unusable after the Python API changes made in Blender 2.8.
Rather than relying on the old and frustratingly slow importer executable the pre-2.8 exporter used (TrainzMeshImporter.exe, created by N3V Games), the 2.8 exporter writes to the indexed mesh file directly instead of using XML as a middleman. This results in a much tidier and easily maintained codebase, faster exports for content creators, and fine-tuned control over what versions of the JET/E2 game engines the file will work in and what data the file will contain (tangents, skinning, texture slots, etc).

The exporter currently supports the serialization of vertex and index data of triangle meshes (meshes will be automatically triangulated on export), texture coordinates, both per-vertex and per-face normals, vertex tangents (optional), bounding box export (optional), material data from the Principled BSDF node (see below, both solid RGB colors and texture slots supported), animated scenes (for either armature or dummy object hierarchies) through the generation of separate .kin files, and automatic texture.txt metadata generation for any of the mesh's dependent texture files.

Once again, this exporter is a work in progress, so if you find any bugs, make sure to create a GitHub issue or bring it to my attention so I can investigate it.

Each of the material data from the principled BSDF node is mapped to the file according to the table below, with target slot types referenced from the Auran JET specification.
If a texture slot is denoted as "Unused by Trainz", I have not found any meshes using the existing Trainz material types that utilize these texture slots. They are maintained to ensure maximum compatibility with the Auran JET specification. Note however that the unused texture's solid color counterpart is separate from the texture data, and if a Solid Color slot is not marked as N/A and has a value that isn't a texture during export, it WILL be written to the .im material data, which is ALL used by Trainz.

Be aware that some of the material slots can share two places in the file at once (for example, a specular texture may be used to influence the specularity of a mesh, but all .im materials contain an RGB Specular value anyway). Because Blender cannot support both a texture and a value at the same time, the exporter will use whatever is supplied to the slot during export.

Material Slot | Target .IM Data (Solid Color)   | Target .IM Data (Texture)
------------- | ------------------------------- | -------------------------
Base Color    | Material Diffuse & Ambient      | Diffuse Texture
Specular      | Material Specular {0-1 to RGB}  | Specular Texture (unused by Trainz?)
Roughness     | Shininess {(1.0 - rough) * 128} | Shine Texture (unused by Trainz?)
Metallic      | N/A                             | Reflection Texture (spheremap used by m.reflect, etc)
Normal        | N/A                             | Normal Map Texture (must have a Normal Map node between the texture and Principled BSDF)
Alpha         | Material Opacity                | Opacity Texture (should support the diffuse texture's node for both diffuse and alpha slots)
Emission      | Emissive Color                  | Selfillum Texture (unused by Trainz?)
IOR           | N/A                             | Refraction Texture (unused by Trainz?)

There were several additional texture slots in the JET spec that are likely unsupported by Trainz (TEX_Ambient, TEX_Filtercolor, and TEX_Displacement). They are not currently supported by the exporter, but the exporter could be modified to support these texture slots if the need arises.

Additionally, the exported Emissive Color (only if supplied by a color rather than a texture) will be multiplied by the Principled BSDF Emission Strength value, to allow for overbright materials (this influences bloom in TRS19).

The strength of the normal map texture in the file will be influenced by the Strength value of the Normal Map node.

The "Specular Tint" value of the Principled BSDF node will influence how much the specular value of the material is muliplied (and colored) by the diffuse color.

An additional export option is provided that instructs the exporter to use the "Subsurface Color" input of the Principled BSDF node as the material ambient color. As most .im files have their ambient color as a repeat of the diffuse color, this may lead to unexpected results.

## Installation
1. Select `Code -> Download ZIP` at the top of this page.
2. In Blender, go to `Edit -> Preferences -> Add-ons`, select `Install`, and navigate to the downloaded zip file.
3. Search for `Indexed Mesh` in the addons list and click the checkbox to enable the addon.
4. `Save Preferences` in the menu at the bottom left of the window.
