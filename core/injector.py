import os
import shutil
import json
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_CONTROLLER = os.path.join(_HERE, "..", "assets", "pygame_controller.py")

def inject_controller_into_game(game_dir: str, main_py_path: str, game_data: dict = None):
    """
    Copies stroke_controller.py into the game folder, and does naive code
    injection into all .py files to import and load the virtual controller.
    It also applies any specific code_patches defined in the game database.
    """
    if game_data is None: game_data = {}
    game_config = game_data.get("game_config", {})
    config_path = os.path.join(game_dir, "game_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(game_config, f, indent=2)

    # Apply regex code patches
    patches = game_data.get("code_patches", [])
    for patch in patches:
        patch_file = os.path.join(game_dir, patch["file"])
        if os.path.exists(patch_file):
            with open(patch_file, "r", encoding="utf-8") as f:
                content = f.read()
            # Replace using regex
            new_content = re.sub(patch["search"], patch["replace"], content)
            if new_content != content:
                with open(patch_file, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print(f"[Injector] Applied code patch to {patch['file']}")

    dest_controller = os.path.join(game_dir, "stroke_controller.py")
    shutil.copy2(TEMPLATE_CONTROLLER, dest_controller)
    
    # We must scan all .py files because the main loop might be in a submodule
    for root, dirs, files in os.walk(game_dir):
        for file in files:
            if not file.endswith(".py"): continue
            if file == "stroke_controller.py": continue
            
            py_path = os.path.join(root, file)
            with open(py_path, "r", encoding="utf-8") as f:
                code = f.read()
                
            original_code = code
            
            has_pygame_init = "pygame.init()" in code
            has_display_call = "pygame.display.flip()" in code or "pygame.display.update()" in code

            # 1. Add import at the very top of the file.
            #    Check only the first 300 chars so that an inline import inside a
            #    function body (added by code_patches) doesn't satisfy this check.
            if has_pygame_init or has_display_call:
                if "import stroke_controller" not in code[:300]:
                    code = "import stroke_controller\n" + code

            # 2. Inject VirtualController instantiation after pygame.init()
            #    Only do this if the file actually contains pygame.init()
            if has_pygame_init and "stroke_controller.vc =" not in code:
                code = re.sub(r'([ \t]*)pygame\.init\(\)', 
                              r'\1pygame.init()\n\1pygame.joystick.init()\n\1stroke_controller.vc = stroke_controller.VirtualController()', 
                              code)
                
            # 3. Inject update() into the main loop.
            if has_display_call and "stroke_controller.vc.update()" not in code:
                replacement = r'\1if hasattr(stroke_controller, "vc") and stroke_controller.vc:\n\1    stroke_controller.vc.update()\n\1    try:\n\1        stroke_controller.vc.draw_cursor(pygame.display.get_surface())\n\1    except: pass\n\1pygame.display.flip()'
                code = re.sub(r'([ \t]*)pygame\.display\.flip\(\)', replacement, code)
                
                replacement2 = r'\1if hasattr(stroke_controller, "vc") and stroke_controller.vc:\n\1    stroke_controller.vc.update()\n\1    try:\n\1        stroke_controller.vc.draw_cursor(pygame.display.get_surface())\n\1    except: pass\n\1pygame.display.update()'
                code = re.sub(r'([ \t]*)pygame\.display\.update\(\)', replacement2, code)
                
            if code != original_code:
                with open(py_path, "w", encoding="utf-8") as f:
                    f.write(code)
                print(f"[Injector] Successfully injected controller into {py_path}")

