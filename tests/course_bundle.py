"""Source payload for course tests; importing it does not rewrite installers."""
import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('course_bundle_sources',ROOT/'course/pack_course.py')
pack=importlib.util.module_from_spec(spec);spec.loader.exec_module(pack)
sources=pack.build_files

def target_path(root,name):
    return root.parent/name if name.startswith('web/') else root/name
