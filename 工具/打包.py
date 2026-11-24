"""把 产品/使用说明.md 和 产品/项目启动包/ 打包成 产品/项目启动包.zip（文件名用 UTF-8，Windows 解压不乱码）。
用法：在项目根目录运行  python3 工具/打包.py
"""
import os, zipfile

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "产品"))
out = "项目启动包.zip"
if os.path.exists(out):
    os.remove(out)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.write("使用说明.md")
    for base, dirs, files in os.walk("项目启动包"):
        dirs.sort()
        z.write(base)
        for f in sorted(files):
            if f != ".DS_Store":
                z.write(os.path.join(base, f))
with zipfile.ZipFile(out) as z:
    print(f"已生成 产品/{out}，共 {len(z.infolist())} 项")
