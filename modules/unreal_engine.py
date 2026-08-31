import os
import sys
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

# Ensure local modules directory is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

try:
    import remote_execution
except ImportError:
    from modules import remote_execution



import re
import ast

BLOCKED_CONSOLE_COMMANDS = {
    "quit", "exit", "crash", "exec", "open", "travel", "restart", "debug",
    "obj", "python", "py", "run", "system", "cmd"
}

ALLOWED_MODULES = {
    'unreal', 'math', 'string', 'enum', 'dataclasses', 'typing',
    'collections', 'functools', 'itertools', 'json',
    're', 'datetime', 'hashlib', 'random', 'uuid', 'decimal',
    'copy', 'statistics', 'time'
}

FORBIDDEN_CALLS = {
    "open", "exec", "eval", "compile", "__import__", "globals",
    "locals", "vars", "getattr", "setattr", "delattr", "breakpoint",
    "run_path", "run_module"
}

FORBIDDEN_ATTRIBUTES = {
    "__class__", "__bases__", "__subclasses__", "__globals__",
    "__code__", "__dict__", "__builtins__", "__import__",
    "__mro__", "__members__",
    "system", "popen", "remove", "unlink", "rmdir", "spawn",
    "import_module", "load_module", "modules", "run_path", "run_module",
    "walk_stack", "extractall"
}

RAW_BLOCKED_PATTERNS = [
    r'\b(exec|eval|compile|__import__|open|run_path|run_module)\s*\(',
    r'\b(getattr|setattr|delattr)\s*\(',
    r'__subclasses__',
    r'__globals__',
    r'__class__',
    r'__bases__',
    r'__code__',
    r'__dict__',
    r'\bchr\s*\(\s*\d+\s*\)',
    r'modules\s*\[',
]


class UnrealASTSecurityValidator(ast.NodeVisitor):
    """AST visitor to enforce strict import allowlist, dynamic call blocks, and sandbox jailbreak protection."""
    def __init__(self):
        self.errors = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            base_mod = alias.name.split(".")[0].lower()
            if base_mod not in ALLOWED_MODULES:
                self.errors.append(f"Module '{alias.name}' is not in the allowed modules allowlist.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if not node.module or node.level > 0:
            self.errors.append("Relative imports and empty module imports are strictly prohibited.")
        else:
            base_mod = node.module.split(".")[0].lower()
            if base_mod not in ALLOWED_MODULES:
                self.errors.append(f"Module '{node.module}' is not in the allowed modules allowlist.")
        for alias in node.names:
            sym_lower = alias.name.lower()
            if (sym_lower in FORBIDDEN_CALLS or
                sym_lower in FORBIDDEN_ATTRIBUTES or
                sym_lower in {"modules", "argv", "executable", "path", "audit", "addaudithook"}):
                self.errors.append(f"Forbidden imported symbol: '{alias.name}'")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            func_name = node.func.id.lower()
            if func_name in FORBIDDEN_CALLS:
                self.errors.append(f"Forbidden built-in function call: '{node.func.id}'")
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr.lower()
            if attr_name in FORBIDDEN_ATTRIBUTES or attr_name in FORBIDDEN_CALLS:
                self.errors.append(f"Forbidden attribute call: '{node.func.attr}'")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        attr_name = node.attr.lower()
        if attr_name in FORBIDDEN_ATTRIBUTES:
            self.errors.append(f"Forbidden dunder/system attribute access: '{node.attr}'")
        self.generic_visit(node)


def _validate_unreal_python_code(code: str) -> None:
    """Validate submitted Unreal Python code against AST rules and raw patterns."""
    clean_code = str(code).strip()
    if not clean_code:
        raise ValueError("Code cannot be empty.")

    # 1. Raw string pattern checks
    for pat in RAW_BLOCKED_PATTERNS:
        if re.search(pat, clean_code, re.IGNORECASE):
            raise PermissionError(f"Security Shield: Prohibited Python pattern detected: '{pat}'")

    # 2. AST parsing & tree validation (Fail-closed on SyntaxError)
    try:
        tree = ast.parse(clean_code)
    except SyntaxError as se:
        raise PermissionError(f"Security Shield: Syntax error in submitted Python code: {se}")

    validator = UnrealASTSecurityValidator()
    validator.visit(tree)
    if validator.errors:
        raise PermissionError(f"Security Shield: Unreal Engine Python code blocked: {'; '.join(validator.errors)}")


def _validate_console_command(command: str) -> None:
    """Validate Unreal Engine console command against dangerous administrative or crash commands."""
    clean = str(command).strip()
    if not clean:
        raise ValueError("Console command cannot be empty.")

    # Check for chained commands separated by semicolons
    sub_cmds = clean.split(";")
    for sc in sub_cmds:
        tokens = sc.strip().split()
        if not tokens:
            continue
        first_token = tokens[0].lower().strip("'\"`")
        if first_token in BLOCKED_CONSOLE_COMMANDS:
            raise PermissionError(f"Console command '{first_token}' is blocked for security.")

_last_ue_call_time = 0.0

def _rate_limit_ue(min_interval: float = 0.1):
    global _last_ue_call_time
    now = time.time()
    if now - _last_ue_call_time < min_interval:
        time.sleep(min_interval - (now - _last_ue_call_time))
    _last_ue_call_time = time.time()

def _get_remote_execution_client() -> remote_execution.RemoteExecution:
    """Instantiate RemoteExecution with api_token from server config for HMAC handshakes."""
    try:
        from config import load_config
        cfg = load_config()
        tok = cfg.get("server", {}).get("api_token", "")
    except Exception:
        tok = ""
    conf = remote_execution.RemoteExecutionConfig(api_token=tok)
    return remote_execution.RemoteExecution(config=conf)


class UnrealEngineBridge:
    """High-performance bridge to Epic Games Unreal Engine 5 & 4 Python Remote Execution."""

    def __init__(self):
        pass

    def _get_active_node(self, wait_seconds: float = 1.2) -> Optional[Dict[str, Any]]:
        """Start client, scan for running Unreal Engine nodes, return first active node."""
        client = _get_remote_execution_client()
        try:
            client.start()
            start = time.time()
            while time.time() - start < wait_seconds:
                nodes = client.remote_nodes
                if nodes:
                    client.stop()
                    return nodes[0]
                time.sleep(0.08)
            client.stop()
        except Exception:
            try:
                client.stop()
            except Exception:
                pass
        return None

    def execute(self, code: str, exec_mode_str: str = "ExecuteFile") -> Dict[str, Any]:
        """Execute Python code in the active Unreal Engine editor instance."""
        client = _get_remote_execution_client()
        try:
            client.start()
            start = time.time()
            active_node = None
            while time.time() - start < 1.5:
                nodes = client.remote_nodes
                if nodes:
                    active_node = nodes[0]
                    break
                time.sleep(0.08)

            if not active_node:
                client.stop()
                return {
                    "success": False,
                    "error": (
                        "Unreal Engine Editor not detected. Ensure Unreal Engine is running and "
                        "'Enable Remote Execution' is checked in Project Settings -> Python."
                    )
                }

            node_id = active_node.get("node_id")
            client.open_command_connection(node_id)
            time.sleep(0.08)

            mode = remote_execution.MODE_EXEC_FILE
            if exec_mode_str.lower() == "executestatement":
                mode = remote_execution.MODE_EXEC_STATEMENT
            elif exec_mode_str.lower() == "evaluatestatement":
                mode = remote_execution.MODE_EVAL_STATEMENT

            res = client.run_command(code, exec_mode=mode)
            client.close_command_connection()
            client.stop()

            # Parse JSON output from print lines if present
            structured_data = None
            logs = res.get("output", [])
            for line in logs:
                text = line.get("output", "") if isinstance(line, dict) else str(line)
                text = text.strip()
                if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
                    try:
                        structured_data = json.loads(text)
                        break
                    except Exception:
                        pass

            return {
                "success": res.get("success", False),
                "result": res.get("result"),
                "output": logs,
                "data": structured_data,
                "project": active_node.get("project_name", "Unknown"),
                "engine_version": active_node.get("engine_version", "Unknown")
            }
        except Exception as e:
            try:
                client.close_command_connection()
            except Exception:
                pass
            try:
                client.stop()
            except Exception:
                pass
            return {"success": False, "error": f"Remote execution error: {str(e)}"}

    def ping(self) -> Dict[str, Any]:
        """Check connectivity to Unreal Engine Editor."""
        node = self._get_active_node(wait_seconds=1.2)
        if node:
            return {
                "status": "connected",
                "method": "Epic Python Remote Execution (UDP/TCP)",
                "project_name": node.get("project_name", "Unknown"),
                "engine_version": node.get("engine_version", "Unknown"),
                "node_id": node.get("node_id", "Unknown"),
                "project_root": node.get("project_root", "Unknown"),
                "user": node.get("user", "Unknown"),
                "machine": node.get("machine", "Unknown")
            }

        return {
            "status": "offline",
            "message": "No active Unreal Engine instance found with Remote Execution enabled.",
            "instructions": "In Unreal Editor: Edit -> Project Settings -> Python -> check 'Enable Remote Execution'."
        }


bridge = UnrealEngineBridge()


# =====================================================================
# 1. CORE & SCRIPT EXECUTION TOOLS
# =====================================================================

def unreal_ping() -> Dict[str, Any]:
    """Check connectivity to a running Unreal Engine 5/4 Editor instance."""
    return bridge.ping()


def unreal_execute_python(code: str, exec_mode: str = "ExecuteFile") -> Dict[str, Any]:
    """Execute Python code directly inside the running Unreal Engine Editor.
    
    You have full access to the 'unreal' library inside the Editor.
    """
    try:
        _validate_unreal_python_code(code)
    except Exception as e:
        return {"success": False, "error": str(e)}

    _rate_limit_ue()
    return bridge.execute(str(code).strip(), exec_mode_str=exec_mode)


def unreal_execute_console_command(command: str) -> Dict[str, Any]:
    """Execute an in-editor console command in Unreal Engine (e.g. 'stat fps', 'r.SetRes 1920x1080', 'HighResShot 2')."""
    clean_cmd = str(command).strip()
    try:
        _validate_console_command(clean_cmd)
    except Exception as e:
        return {"success": False, "error": str(e)}

    cmd_json = json.dumps(clean_cmd)
    py_code = f"""
import unreal
import json
try:
    unreal.SystemLibrary.execute_console_command(None, {cmd_json})
    print(json.dumps({{"success": True, "command": {cmd_json}}}))
except Exception as e:
    print(json.dumps({{"success": False, "error": str(e)}}))
"""
    return bridge.execute(py_code)


def unreal_get_project_info() -> Dict[str, Any]:
    """Get project directory, current map, loaded plugins, and project settings."""
    py_code = """
import unreal
import json

try:
    proj_dir = unreal.Paths.project_dir()
    proj_name = unreal.Paths.get_project_file_path()
    engine_ver = unreal.SystemLibrary.get_engine_version()
    current_map = unreal.EditorLevelLibrary.get_editor_world().get_path_name() if unreal.EditorLevelLibrary.get_editor_world() else "None"
    
    data = {
        "success": True,
        "project_path": proj_name,
        "project_directory": proj_dir,
        "engine_version": engine_ver,
        "current_level": current_map
    }
    print(json.dumps(data))
except Exception as e:
    print(json.dumps({"success": False, "error": str(e)}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


# =====================================================================
# 2. ACTOR & WORLD OUTLINER MANAGEMENT
# =====================================================================

def unreal_get_actors(class_filter: str = "", tag_filter: str = "", limit: int = 100) -> Dict[str, Any]:
    """Query actors in the active level filtered by class or tag.
    
    Args:
        class_filter: Substring filter for class name (e.g. 'StaticMeshActor', 'PointLight', 'Camera').
        tag_filter: Substring filter for actor tags.
        limit: Max actors to return (default 100, max 500).
    """
    c_json = json.dumps(str(class_filter).lower())
    t_json = json.dumps(str(tag_filter).lower())
    clean_limit = max(1, min(int(limit), 500))
    py_code = f"""
import unreal
import json

actors = unreal.EditorLevelLibrary.get_all_level_actors()
results = []
c_filter = {c_json}
t_filter = {t_json}

for a in actors:
    if not a:
        continue
    c_name = a.get_class().get_name()
    label = a.get_actor_label()
    
    if c_filter and (c_filter not in c_name.lower() and c_filter not in label.lower()):
        continue
        
    tags = [str(t) for t in a.tags] if hasattr(a, 'tags') else []
    if t_filter and not any(t_filter in t.lower() for t in tags):
        continue

    loc = a.get_actor_location()
    rot = a.get_actor_rotation()
    scale = a.get_actor_scale3d()
    
    results.append({{
        "name": a.get_name(),
        "label": label,
        "class": c_name,
        "location": [round(loc.x, 2), round(loc.y, 2), round(loc.z, 2)],
        "rotation": [round(rot.pitch, 2), round(rot.yaw, 2), round(rot.roll, 2)],
        "scale": [round(scale.x, 2), round(scale.y, 2), round(scale.z, 2)],
        "tags": tags
    }})
    if len(results) >= {limit}:
        break

print(json.dumps({{"actors": results, "count": len(results)}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_spawn_actor(
    actor_class: str,
    location: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
    actor_label: str = ""
) -> Dict[str, Any]:
    """Spawn an Actor (Class, StaticMesh, Blueprint, Light, Camera) into the active Unreal Engine level.
    
    Args:
        actor_class: Class name (e.g. 'StaticMeshActor', 'PointLight', 'DirectionalLight', 'CameraActor') or Blueprint path.
        location: [X, Y, Z] world position (default [0,0,0]).
        rotation: [Pitch, Yaw, Roll] in degrees (default [0,0,0]).
        scale: [X, Y, Z] scale multiplier (default [1,1,1]).
        actor_label: Optional label/name in the World Outliner.
    """
    loc = location or [0.0, 0.0, 0.0]
    rot = rotation or [0.0, 0.0, 0.0]
    sc = scale or [1.0, 1.0, 1.0]

    py_code = f"""
import unreal
import json

loc = unreal.Vector({loc[0]}, {loc[1]}, {loc[2]})
rot = unreal.Rotator({rot[0]}, {rot[1]}, {rot[2]})
sc = unreal.Vector({sc[0]}, {sc[1]}, {sc[2]})
target_class = "{actor_class}"

cls = None
try:
    cls = getattr(unreal, target_class)
except Exception:
    pass

if not cls:
    cls = unreal.EditorAssetLibrary.load_blueprint_class(target_class)

if cls:
    actor_obj = unreal.EditorLevelLibrary.spawn_actor_from_class(cls, loc, rot)
    if actor_obj:
        actor_obj.set_actor_scale3d(sc)
        if "{actor_label}":
            actor_obj.set_actor_label("{actor_label}")
        
        print(json.dumps({{
            "success": True,
            "name": actor_obj.get_name(),
            "label": actor_obj.get_actor_label(),
            "class": actor_obj.get_class().get_name(),
            "location": [{loc[0]}, {loc[1]}, {loc[2]}],
            "rotation": [{rot[0]}, {rot[1]}, {rot[2]}],
            "scale": [{sc[0]}, {sc[1]}, {sc[2]}]
        }}))
    else:
        print(json.dumps({{"success": False, "error": "Spawn returned null."}}))
else:
    print(json.dumps({{"success": False, "error": f"Could not load class or blueprint '{{target_class}}'."}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_spawn_shape_actor(
    shape_type: str = "Cube",
    location: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
    material_path: str = "",
    actor_label: str = ""
) -> Dict[str, Any]:
    """Spawn a standard geometric primitive shape (Cube, Sphere, Cylinder, Plane, Cone) for rapid level greyboxing.
    
    Args:
        shape_type: 'Cube', 'Sphere', 'Cylinder', 'Plane', or 'Cone'.
        location: [X, Y, Z] world coordinates.
        rotation: [Pitch, Yaw, Roll] in degrees.
        scale: [X, Y, Z] scale multipliers.
        material_path: Optional material asset path to assign (e.g. '/Engine/BasicShapes/BasicShapeMaterial').
        actor_label: Optional label for the Outliner.
    """
    loc = location or [0.0, 0.0, 0.0]
    rot = rotation or [0.0, 0.0, 0.0]
    sc = scale or [1.0, 1.0, 1.0]

    mesh_map = {
        "cube": "/Engine/BasicShapes/Cube.Cube",
        "sphere": "/Engine/BasicShapes/Sphere.Sphere",
        "cylinder": "/Engine/BasicShapes/Cylinder.Cylinder",
        "plane": "/Engine/BasicShapes/Plane.Plane",
        "cone": "/Engine/BasicShapes/Cone.Cone"
    }
    mesh_path = mesh_map.get(shape_type.lower(), "/Engine/BasicShapes/Cube.Cube")
    lbl = actor_label or f"SM_{shape_type.capitalize()}"

    py_code = f"""
import unreal
import json

loc = unreal.Vector({loc[0]}, {loc[1]}, {loc[2]})
rot = unreal.Rotator({rot[0]}, {rot[1]}, {rot[2]})
sc = unreal.Vector({sc[0]}, {sc[1]}, {sc[2]})

mesh_asset = unreal.EditorAssetLibrary.load_asset("{mesh_path}")
if not mesh_asset:
    print(json.dumps({{"success": False, "error": "Failed to load basic mesh '{mesh_path}'."}}))
else:
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.StaticMeshActor, loc, rot)
    if actor:
        actor.set_actor_scale3d(sc)
        actor.set_actor_label("{lbl}")
        sm_comp = actor.static_mesh_component
        sm_comp.set_static_mesh(mesh_asset)
        
        if "{material_path}":
            mat = unreal.EditorAssetLibrary.load_asset("{material_path}")
            if mat:
                sm_comp.set_material(0, mat)
                
        print(json.dumps({{
            "success": True,
            "label": actor.get_actor_label(),
            "name": actor.get_name(),
            "shape": "{shape_type}",
            "location": [{loc[0]}, {loc[1]}, {loc[2]}],
            "scale": [{sc[0]}, {sc[1]}, {sc[2]}]
        }}))
    else:
        print(json.dumps({{"success": False, "error": "Failed to spawn StaticMeshActor."}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_set_actor_transform(
    actor_name: str,
    location: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
    scale: Optional[List[float]] = None
) -> Dict[str, Any]:
    """Update world location, rotation, or scale of an existing actor in the active level."""
    loc_snippet = f"a.set_actor_location(unreal.Vector({location[0]}, {location[1]}, {location[2]}), False, False)" if location else ""
    rot_snippet = f"a.set_actor_rotation(unreal.Rotator({rotation[0]}, {rotation[1]}, {rotation[2]}), False)" if rotation else ""
    scale_snippet = f"a.set_actor_scale3d(unreal.Vector({scale[0]}, {scale[1]}, {scale[2]}))" if scale else ""

    py_code = f"""
import unreal
import json

target = "{actor_name}".lower()
actors = unreal.EditorLevelLibrary.get_all_level_actors()
found = False

for a in actors:
    if not a:
        continue
    if a.get_name().lower() == target or a.get_actor_label().lower() == target:
        found = True
        {loc_snippet}
        {rot_snippet}
        {scale_snippet}
        loc = a.get_actor_location()
        rot = a.get_actor_rotation()
        sc = a.get_actor_scale3d()
        print(json.dumps({{
            "success": True,
            "actor": a.get_actor_label(),
            "location": [round(loc.x, 2), round(loc.y, 2), round(loc.z, 2)],
            "rotation": [round(rot.pitch, 2), round(rot.yaw, 2), round(rot.roll, 2)],
            "scale": [round(sc.x, 2), round(sc.y, 2), round(sc.z, 2)]
        }}))
        break

if not found:
    print(json.dumps({{"success": False, "error": f"Actor '{actor_name}' not found in current level."}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_delete_actor(actor_name: str) -> Dict[str, Any]:
    """Delete an actor from the active level by name or label."""
    py_code = f"""
import unreal
import json

target = "{actor_name}".lower()
actors = unreal.EditorLevelLibrary.get_all_level_actors()
deleted = False

for a in actors:
    if not a:
        continue
    if a.get_name().lower() == target or a.get_actor_label().lower() == target:
        label = a.get_actor_label()
        unreal.EditorLevelLibrary.destroy_actor(a)
        deleted = True
        print(json.dumps({{"success": True, "deleted_actor": label}}))
        break

if not deleted:
    print(json.dumps({{"success": False, "error": f"Actor '{actor_name}' not found."}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_get_selected_actors() -> Dict[str, Any]:
    """Get all actors currently selected by the user in the Unreal Editor viewport."""
    py_code = """
import unreal
import json

selected = unreal.EditorLevelLibrary.get_selected_level_actors()
res = []
for a in selected:
    if not a:
        continue
    loc = a.get_actor_location()
    res.append({
        "name": a.get_name(),
        "label": a.get_actor_label(),
        "class": a.get_class().get_name(),
        "location": [round(loc.x, 2), round(loc.y, 2), round(loc.z, 2)]
    })
print(json.dumps({"selected_actors": res, "count": len(res)}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_set_selected_actors(actor_names: List[str]) -> Dict[str, Any]:
    """Set the active selection in the Unreal Editor viewport."""
    names_json = json.dumps(actor_names)
    py_code = f"""
import unreal
import json

targets = [x.lower() for x in {names_json}]
actors = unreal.EditorLevelLibrary.get_all_level_actors()
to_select = []

for a in actors:
    if not a:
        continue
    if a.get_name().lower() in targets or a.get_actor_label().lower() in targets:
        to_select.append(a)

unreal.EditorLevelLibrary.set_selected_level_actors(to_select)
print(json.dumps({{"success": True, "selected_count": len(to_select)}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_focus_actor(actor_name: str) -> Dict[str, Any]:
    """Frame/focus the active Editor viewport camera on a specific actor."""
    py_code = f"""
import unreal
import json

target = "{actor_name}".lower()
actors = unreal.EditorLevelLibrary.get_all_level_actors()
found = None

for a in actors:
    if not a:
        continue
    if a.get_name().lower() == target or a.get_actor_label().lower() == target:
        found = a
        break

if found:
    unreal.EditorLevelLibrary.set_selected_level_actors([found])
    unreal.EditorLevelLibrary.editor_invalidate_viewports()
    unreal.SystemLibrary.execute_console_command(None, "CAMERA ALIGN")
    print(json.dumps({{"success": True, "focused_actor": found.get_actor_label()}}))
else:
    print(json.dumps({{"success": False, "error": f"Actor '{actor_name}' not found."}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


# =====================================================================
# 3. LEVEL & MAP MANAGEMENT
# =====================================================================

def unreal_get_current_level() -> Dict[str, Any]:
    """Get the name and path of the currently open level in the Unreal Editor."""
    py_code = """
import unreal
import json

world = unreal.EditorLevelLibrary.get_editor_world()
if world:
    print(json.dumps({
        "success": True,
        "level_name": world.get_name(),
        "level_path": world.get_path_name()
    }))
else:
    print(json.dumps({"success": False, "error": "No editor world loaded."}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_load_level(level_asset_path: str) -> Dict[str, Any]:
    """Load an existing level/map into the Unreal Editor (e.g. '/Game/Maps/MainMap')."""
    py_code = f"""
import unreal
import json

path = "{level_asset_path}"
success = unreal.EditorLevelLibrary.load_level(path)
print(json.dumps({{"success": success, "loaded_level": path}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_save_current_level() -> Dict[str, Any]:
    """Save the active level and any dirty packages in the Unreal Editor."""
    py_code = """
import unreal
import json

saved_level = unreal.EditorLevelLibrary.save_current_level()
saved_dirty = unreal.EditorAssetLibrary.save_dirty_packages(True, True)
print(json.dumps({
    "success": saved_level,
    "saved_current_level": saved_level,
    "saved_dirty_packages": saved_dirty
}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_new_level(level_asset_path: str) -> Dict[str, Any]:
    """Create and open a new level in the project (e.g. '/Game/Maps/NewMap')."""
    py_code = f"""
import unreal
import json

path = "{level_asset_path}"
success = unreal.EditorLevelLibrary.new_level(path)
print(json.dumps({{"success": success, "new_level": path}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


# =====================================================================
# 4. ASSETS & MATERIALS MANAGEMENT
# =====================================================================

def unreal_list_assets(directory_path: str = "/Game", recursive: bool = True, asset_class: str = "") -> Dict[str, Any]:
    """List assets in the Unreal Content Browser.
    
    Args:
        directory_path: Root package path (default '/Game').
        recursive: Whether to scan subfolders.
        asset_class: Optional class filter (e.g. 'StaticMesh', 'Material', 'Texture2D', 'Blueprint').
    """
    py_code = f"""
import unreal
import json

dir_path = "{directory_path}"
rec = {str(recursive)}
filter_cls = "{asset_class}".lower()

asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
asset_data_list = unreal.EditorAssetLibrary.list_assets(dir_path, recursive=rec, include_folder=False)

results = []
for p in asset_data_list[:200]:
    if filter_cls:
        data = unreal.EditorAssetLibrary.find_asset_data(p)
        if data and filter_cls not in data.asset_class_path.asset_name.to_slug().lower():
            continue
    results.append(p)

print(json.dumps({{"assets": results, "count": len(results), "directory": dir_path}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_get_asset_info(asset_path: str) -> Dict[str, Any]:
    """Retrieve detailed metadata, class, and tags for a specific asset in the project."""
    py_code = f"""
import unreal
import json

path = "{asset_path}"
if not unreal.EditorAssetLibrary.does_asset_exist(path):
    print(json.dumps({{"success": False, "error": f"Asset '{path}' does not exist."}}))
else:
    data = unreal.EditorAssetLibrary.find_asset_data(path)
    tags = {{str(k): str(v) for k, v in data.get_tags().items()}} if hasattr(data, 'get_tags') else {{}}
    print(json.dumps({{
        "success": True,
        "asset_name": str(data.asset_name),
        "package_name": str(data.package_name),
        "class": str(data.asset_class_path.asset_name),
        "tags": tags
    }}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_create_material(
    material_name: str,
    destination_path: str = "/Game/Materials",
    base_color: Optional[List[float]] = None,
    metallic: float = 0.0,
    roughness: float = 0.5
) -> Dict[str, Any]:
    """Create a new Material asset with basic PBR parameters."""
    b_color = base_color or [0.8, 0.8, 0.8]
    py_code = f"""
import unreal
import json

mat_name = "{material_name}"
dest = "{destination_path}"
pkg_path = f"{{dest}}/{{mat_name}}"

asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
factory = unreal.MaterialFactoryNew()

mat = asset_tools.create_asset(mat_name, dest, unreal.Material, factory)
if mat:
    # Set Base Color Vector Constant
    color_node = unreal.MaterialEditingLibrary.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -300, 0)
    color_node.constant = unreal.LinearColor({b_color[0]}, {b_color[1]}, {b_color[2]}, 1.0)
    unreal.MaterialEditingLibrary.connect_material_property(color_node, "", unreal.MaterialProperty.MP_BASE_COLOR)
    
    # Set Metallic & Roughness
    metal_node = unreal.MaterialEditingLibrary.create_material_expression(mat, unreal.MaterialExpressionConstant, -200, 100)
    metal_node.r = {metallic}
    unreal.MaterialEditingLibrary.connect_material_property(metal_node, "", unreal.MaterialProperty.MP_METALLIC)
    
    rough_node = unreal.MaterialEditingLibrary.create_material_expression(mat, unreal.MaterialExpressionConstant, -200, 200)
    rough_node.r = {roughness}
    unreal.MaterialEditingLibrary.connect_material_property(rough_node, "", unreal.MaterialProperty.MP_ROUGHNESS)
    
    unreal.MaterialEditingLibrary.recompile_material(mat)
    unreal.EditorAssetLibrary.save_asset(pkg_path)
    
    print(json.dumps({{"success": True, "material_path": pkg_path}}))
else:
    print(json.dumps({{"success": False, "error": "Failed to create material."}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_assign_material_to_actor(actor_name: str, material_path: str, element_index: int = 0) -> Dict[str, Any]:
    """Assign a Material asset to an actor's StaticMesh or SkeletalMesh component."""
    py_code = f"""
import unreal
import json

target = "{actor_name}".lower()
mat_path = "{material_path}"
mat_asset = unreal.EditorAssetLibrary.load_asset(mat_path)

if not mat_asset:
    print(json.dumps({{"success": False, "error": f"Material '{mat_path}' not found."}}))
else:
    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    found = False
    for a in actors:
        if not a:
            continue
        if a.get_name().lower() == target or a.get_actor_label().lower() == target:
            found = True
            comp = a.get_component_by_class(unreal.MeshComponent)
            if comp:
                comp.set_material({element_index}, mat_asset)
                print(json.dumps({{"success": True, "actor": a.get_actor_label(), "material": mat_path}}))
            else:
                print(json.dumps({{"success": False, "error": "Actor has no MeshComponent."}}))
            break
    if not found:
        print(json.dumps({{"success": False, "error": f"Actor '{actor_name}' not found."}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_delete_asset(asset_path: str) -> Dict[str, Any]:
    """Delete an asset from the Content Browser."""
    py_code = f"""
import unreal
import json

path = "{asset_path}"
deleted = unreal.EditorAssetLibrary.delete_asset(path)
print(json.dumps({{"success": deleted, "deleted_asset": path}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


# =====================================================================
# 5. LIGHTING, CAMERAS & VIEWPORT RENDERING
# =====================================================================

def unreal_spawn_light(
    light_type: str = "PointLight",
    location: Optional[List[float]] = None,
    intensity: float = 5000.0,
    light_color: Optional[List[float]] = None,
    attenuation_radius: float = 1000.0,
    actor_label: str = ""
) -> Dict[str, Any]:
    """Spawn and configure a light (PointLight, DirectionalLight, SpotLight, SkyLight, RectLight).
    
    Args:
        light_type: 'PointLight', 'DirectionalLight', 'SpotLight', 'SkyLight', or 'RectLight'.
        location: [X, Y, Z] world position.
        intensity: Intensity of the light.
        light_color: [R, G, B] normalized color values (0.0 to 1.0).
        attenuation_radius: Reach radius of the light.
        actor_label: Optional label for the Outliner.
    """
    loc = location or [0.0, 0.0, 300.0]
    col = light_color or [1.0, 1.0, 1.0]
    lbl = actor_label or f"{light_type}"

    py_code = f"""
import unreal
import json

l_type = "{light_type}".lower()
cls = unreal.PointLight
if "dir" in l_type:
    cls = unreal.DirectionalLight
elif "spot" in l_type:
    cls = unreal.SpotLight
elif "sky" in l_type:
    cls = unreal.SkyLight
elif "rect" in l_type:
    cls = unreal.RectLight

loc = unreal.Vector({loc[0]}, {loc[1]}, {loc[2]})
rot = unreal.Rotator(0, 0, 0)
actor = unreal.EditorLevelLibrary.spawn_actor_from_class(cls, loc, rot)

if actor:
    actor.set_actor_label("{lbl}")
    comp = actor.get_component_by_class(unreal.LightComponentBase)
    if comp:
        comp.set_intensity({intensity})
        comp.set_light_color(unreal.LinearColor({col[0]}, {col[1]}, {col[2]}, 1.0))
        if hasattr(comp, 'set_attenuation_radius'):
            comp.set_attenuation_radius({attenuation_radius})
            
    print(json.dumps({{
        "success": True,
        "label": actor.get_actor_label(),
        "type": "{light_type}",
        "intensity": {intensity},
        "location": [{loc[0]}, {loc[1]}, {loc[2]}]
    }}))
else:
    print(json.dumps({{"success": False, "error": "Failed to spawn light actor."}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res


def unreal_take_screenshot(filename: str = "", resolution_multiplier: int = 1) -> Dict[str, Any]:
    """Capture a viewport screenshot inside the active Unreal Engine Editor session.
    
    Args:
        filename: Optional output image path (saved to project's Saved/Screenshots/ by default).
        resolution_multiplier: Multiplier for screenshot resolution (1, 2, or 4).
    """
    fname = filename.replace("\\", "/") if filename else ""
    py_code = f"""
import unreal
import json

try:
    cmd = "HighResShot {resolution_multiplier}" if not "{fname}" else "HighResShot {fname} {resolution_multiplier}"
    unreal.EditorLevelLibrary.editor_invalidate_viewports()
    unreal.SystemLibrary.execute_console_command(None, cmd)
    print(json.dumps({{"success": True, "message": "Screenshot triggered successfully.", "command": cmd}}))
except Exception as e:
    print(json.dumps({{"success": False, "error": str(e)}}))
"""
    res = bridge.execute(py_code)
    return res.get("data") or res
