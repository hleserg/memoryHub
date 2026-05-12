#!/usr/bin/env python3
"""
Automated test updater for SessionExperience refactoring.

This script updates test files to use the new SessionExperience API:
- key_moments=[...] → key_moment_ids=[moment.id]
- Adds avg_emotional_intensity and has_profound_moment fields
"""

import re
import sys
from pathlib import Path


def fix_simple_single_moment(content: str) -> str:
    """Fix simple single-moment case: key_moments=[variable]."""
    
    # Pattern: SessionExperience(..., key_moments=[moment_var], ...)
    pattern = r'SessionExperience\s*\(\s*([^)]*?)key_moments\s*=\s*\[([a-zA-Z_][a-zA-Z0-9_]*)\]([^)]*?)\)'
    
    def replacer(match):
        before = match.group(1)
        moment_var = match.group(2)
        after = match.group(3)
        
        # Check if avg_emotional_intensity already present
        if 'avg_emotional_intensity' in before + after:
            return match.group(0)  # Already updated
        
        # Add new fields with conservative defaults
        new_fields = f'key_moment_ids=[{moment_var}.id], avg_emotional_intensity=0.5, has_profound_moment=False'
        
        return f'SessionExperience({before}{new_fields}{after})'
    
    return re.sub(pattern, replacer, content, flags=re.DOTALL)


def fix_empty_key_moments(content: str) -> str:
    """Fix empty key_moments case: key_moments=[]."""
    
    # This should use key_moment_ids=[] but will likely fail validation (min_length=1)
    # Keep as-is for now to preserve test intent
    return content


def process_file(filepath: Path) -> tuple[bool, str]:
    """Process a single test file."""
    try:
        content = filepath.read_text(encoding='utf-8')
        original = content
        
        # Apply fixes
        content = fix_simple_single_moment(content)
        
        if content != original:
            filepath.write_text(content, encoding='utf-8')
            lines_changed = content.count('\n') - original.count('\n')
            return True, f"Updated {filepath.name} ({len(re.findall('key_moment_ids', content)) - len(re.findall('key_moment_ids', original))} replacements)"
        else:
            return False, f"No changes: {filepath.name}"
            
    except Exception as e:
        return False, f"Error in {filepath.name}: {e}"


def main():
    """Main entry point."""
    tests_dir = Path("/workspace/tests")
    
    if not tests_dir.exists():
        print(f"Tests directory not found: {tests_dir}")
        sys.exit(1)
    
    # Target specific files with known simple patterns
    target_files = [
        "test_session_working_memory.py",
        "test_reflection_prompts_builders.py",
        "test_term_output.py",
        "test_passive_memory_injector.py",
        "test_emotional_echo.py",
        "test_agent_config.py",
        "test_file_state_store.py",
        "test_ollama_reflection_model_with_persistence.py",
    ]
    
    print("Automated SessionExperience test updater")
    print("=" * 60)
    print()
    
    updated_count = 0
    for filename in target_files:
        filepath = tests_dir / filename
        if not filepath.exists():
            print(f"  Skip: {filename} (not found)")
            continue
            
        changed, message = process_file(filepath)
        if changed:
            updated_count += 1
            print(f"✓ {message}")
        else:
            print(f"  {message}")
    
    print()
    print(f"Updated {updated_count}/{len(target_files)} files")
    print("\nNote: Complex cases (multiple moments, queries, assertions) require manual review.")


if __name__ == "__main__":
    main()
